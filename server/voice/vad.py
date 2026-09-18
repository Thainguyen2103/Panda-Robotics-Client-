"""
vad.py — Voice Activity Detection
==================================
Chọn microphone tự động và ghi âm theo VAD năng lượng.

Thuật toán:
  - Warm-up 0.4s (Realtek array nhả toàn số 0 lúc đầu)
  - Hiệu chuẩn ồn nền 0.6s (quạt, điều hòa)
  - Ngưỡng thích nghi: max(NOISE_FLOOR, ambient * MULT)
  - Kiểm tra spectral flatness để lọc tiếng ồn rộng băng (quạt, gió)
  - Im lặng >= silence_sec → kết thúc clip
"""

import io
import os
import sys
import queue
import wave
import time
import threading
import collections

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 16_000                              # Chuẩn Whisper
BLOCK_MS       = 30
BLOCK_FRAMES   = SAMPLE_RATE * BLOCK_MS // 1000     # 480 frames/block

VAD_NOISE_FLOOR  = getattr(settings, "VAD_NOISE_FLOOR",  0.03)
VAD_AMBIENT_MULT = getattr(settings, "VAD_AMBIENT_MULT", 2.0)
SPEECH_FLAT_MAX  = getattr(settings, "SPEECH_FLAT_MAX",  0.55)
MIN_SPEECH_SEC   = 0.25   # clip ngắn hơn này → bỏ (tiếng ồn ngắn)

MIC_DEVICE_INDEX = getattr(settings, "MIC_DEVICE_INDEX", None)

# ─── Import sounddevice / numpy ───────────────────────────────────────────────
try:
    import sounddevice as _sd
    import numpy as _np
    print("✅ [VAD] sounddevice sẵn sàng.")
except ImportError:
    _sd = _np = None
    print("❌ [VAD] sounddevice/numpy chưa cài. pip install sounddevice numpy")

# ─── State ────────────────────────────────────────────────────────────────────
_device_cache: tuple | None = None
_mic_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
#  TÍNH NĂNG LƯỢNG & SPECTRAL FLATNESS
# ══════════════════════════════════════════════════════════════════════════════

def _rms(data: bytes) -> float:
    """RMS của 1 block PCM int16 → [0.0, 1.0]."""
    arr = _np.frombuffer(data, dtype=_np.int16).astype(_np.float32) / 32768.0
    return float(_np.sqrt(_np.mean(arr ** 2))) if arr.size else 0.0


def _spectral_flatness(data: bytes) -> float:
    """
    Độ phẳng phổ (0→1):
      - Giọng nói có hài âm → flatness thấp (0.1–0.4)
      - Tiếng quạt/gió là ồn rộng băng → flatness cao (0.6–0.9)
    Dùng để gạt tiếng ồn bộc phát mà ngưỡng năng lượng không phân được.
    """
    arr = _np.frombuffer(data, dtype=_np.int16).astype(_np.float32) / 32768.0
    if arr.size == 0:
        return 1.0
    spec = _np.abs(_np.fft.rfft(arr * _np.hanning(arr.size))) ** 2
    spec = spec[1:]  # bỏ bin DC
    mean = float(_np.mean(spec))
    if mean <= 1e-12:
        return 1.0
    geo = float(_np.exp(_np.mean(_np.log(spec + 1e-12))))
    return min(1.0, geo / mean)


# ══════════════════════════════════════════════════════════════════════════════
#  CHỌN MICROPHONE
# ══════════════════════════════════════════════════════════════════════════════

def _probe_device_rms(dev_index: int, duration: float = 1.0) -> float:
    """
    Mở mic `duration` giây, trả về RMS trung bình.
    Bỏ 0.4s đầu (Realtek warm-up nhả toàn số 0).
    """
    try:
        q = queue.Queue()

        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        with _sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                             device=dev_index, blocksize=BLOCK_FRAMES, callback=_cb):
            deadline = time.time() + duration
            warmup = time.time() + 0.4
            blocks = []
            while time.time() < deadline:
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    break
                if time.time() < warmup:
                    continue
                blocks.append(data)
        if not blocks:
            return 0.0
        return _rms(b"".join(blocks))
    except Exception:
        return 0.0


def select_input_device() -> tuple | None:
    """
    Chọn microphone:
      1. MIC_DEVICE_INDEX thủ công (settings) → dùng luôn
      2. Default Windows nếu có tín hiệu (RMS > 3e-5) → dùng luôn
      3. Quét tất cả, chọn thiết bị có tín hiệu mạnh nhất
    Trả về (index, name) hoặc None.
    """
    global _device_cache
    if _sd is None:
        return None
    if _device_cache:
        return _device_cache

    # Thủ công từ settings
    if MIC_DEVICE_INDEX is not None:
        try:
            d = _sd.query_devices(MIC_DEVICE_INDEX, "input")
            _device_cache = (MIC_DEVICE_INDEX, d["name"])
            print(f"🎤 [VAD] Mic thủ công: #{MIC_DEVICE_INDEX} — {d['name']}")
            return _device_cache
        except Exception as e:
            print(f"❌ [VAD] MIC_DEVICE_INDEX={MIC_DEVICE_INDEX} lỗi: {e}")
            return None

    try:
        devices = _sd.query_devices()
        default_idx = _sd.default.device[0]
    except Exception as e:
        print(f"❌ [VAD] Không liệt kê được thiết bị: {e}")
        return None

    input_idxs = [i for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
    if not input_idxs:
        print("❌ [VAD] Không tìm thấy microphone nào.")
        return None

    # Thử default trước
    if default_idx in input_idxs and _probe_device_rms(default_idx) > 3e-5:
        name = devices[default_idx]["name"]
        _device_cache = (default_idx, name)
        print(f"🎤 [VAD] Mic default tốt: #{default_idx} — {name}")
        return _device_cache

    # Default im lặng → quét tất cả
    print("🔎 [VAD] Mic default im lặng — dò các mic khác...")
    best_idx, best_rms = None, 0.0
    for idx in input_idxs:
        if idx == default_idx:
            continue
        rms = _probe_device_rms(idx)
        if rms > best_rms:
            best_idx, best_rms = idx, rms

    if best_idx is not None and best_rms > 3e-5:
        name = devices[best_idx]["name"]
        _device_cache = (best_idx, name)
        print(f"🎤 [VAD] Mic có tín hiệu: #{best_idx} — {name} (RMS={best_rms:.4f})")
        return _device_cache

    # Fallback: vẫn dùng default
    if default_idx is not None and default_idx >= 0:
        name = devices[default_idx]["name"]
        _device_cache = (default_idx, name)
        print(f"⚠️  [VAD] Dùng default (tín hiệu yếu): #{default_idx} — {name}")
        return _device_cache

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  GHI ÂM THEO VAD
# ══════════════════════════════════════════════════════════════════════════════

def record_until_silence(
    silence_sec: float = 2.0,
    max_sec: float = 15.0,
    wait_timeout: float = None,
    is_active_fn=None,
) -> bytes | None:
    """
    Ghi âm đến khi người dùng ngừng nói.

    Args:
        silence_sec:    Im lặng bao lâu (sau khi có tiếng) thì kết thúc.
        max_sec:        Thời gian clip tối đa.
        wait_timeout:   Chờ tối đa bao lâu cho tiếng nói đầu tiên.
                        None = chờ mãi.
        is_active_fn:   Callback() → bool. Trả False → hủy ghi âm ngay.

    Returns:
        bytes PCM int16 16kHz mono, hoặc None nếu không thu được tiếng nói.
    """
    if _sd is None or _np is None:
        return None

    with _mic_lock:
        dev = select_input_device()
        if dev is None:
            time.sleep(1)
            return None

        q = queue.Queue()

        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        frames        = []
        preroll       = collections.deque(maxlen=int(1.5 * 1000 / BLOCK_MS))
        got_speech    = False
        last_speech_t = 0.0
        peak          = 0.0
        speech_blocks = 0
        ambient_ema   = 0.0
        seen          = 0
        calib_blocks  = int(0.6 * 1000 / BLOCK_MS)
        start         = time.time()
        min_blocks    = int(MIN_SPEECH_SEC * 1000 / BLOCK_MS)

        try:
            with _sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                 device=dev[0], blocksize=BLOCK_FRAMES, callback=_cb):
                while True:
                    # Caller yêu cầu hủy?
                    if is_active_fn and not is_active_fn():
                        return None

                    try:
                        data = q.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    now = time.time()
                    rms = _rms(data)

                    # ── Warm-up 0.4s ────────────────────────────────────────
                    if (now - start) < 0.4 and not got_speech and rms <= 0.10:
                        preroll.append(data)
                        continue

                    # ── Hiệu chuẩn ồn nền 0.6s ─────────────────────────────
                    if seen < calib_blocks and not got_speech and rms <= 0.10:
                        seen += 1
                        ambient_ema = rms if seen == 1 else ambient_ema * 0.7 + rms * 0.3
                        preroll.append(data)
                        continue

                    threshold = max(VAD_NOISE_FLOOR, ambient_ema * VAD_AMBIENT_MULT)
                    rel_gate  = peak * 0.55 if (got_speech and peak > 0) else 0.0
                    is_speech = (rms >= threshold
                                 and rms >= rel_gate
                                 and _spectral_flatness(data) < SPEECH_FLAT_MAX)

                    if is_speech:
                        if not got_speech:
                            got_speech = True
                            frames.extend(preroll)
                        peak = max(peak, rms)
                        speech_blocks += 1
                        last_speech_t = now
                        frames.append(data)
                    else:
                        if got_speech:
                            frames.append(data)
                            if now - last_speech_t >= silence_sec:
                                break
                        else:
                            ambient_ema = ambient_ema * 0.9 + rms * 0.1
                            preroll.append(data)
                            if wait_timeout and (now - start) > wait_timeout:
                                return None

                    if (now - start) > max_sec:
                        break

        except Exception as e:
            print(f"❌ [VAD] Lỗi ghi âm: {e}")
            return None

        if not got_speech or not frames or speech_blocks < min_blocks:
            return None
        return b"".join(frames)


def wrap_wav(pcm: bytes) -> bytes:
    """Đóng gói PCM int16 16kHz mono thành WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()
