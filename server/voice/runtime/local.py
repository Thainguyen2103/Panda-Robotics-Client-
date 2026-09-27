"""
Voice (STT) module — Robot Moon
=================================
Pipeline nhận dạng giọng nói kiểu Anki Vector:
  Microphone (VAD năng lượng) → đoạn thoại ngắn → Groq Whisper → transcript
    → bộ lọc chống hallucination
      → phát hiện wake-word "Moon" → callback lên brain.py

Thiết kế tối ưu độ trễ:
  - Ghi âm 16kHz mono int16, block 30ms → phát hiện đầu/cuối câu gần như tức thì
  - Kết thúc câu nhanh (WAKE_SILENCE_SEC ~1.2s khi standby) → gửi Groq ngay
  - Groq whisper-large-v3-turbo với temperature=0.0 (KHÔNG dùng fallback ladder —
    ladder gây hallucination và tăng độ trễ)
  - Noise floor RMS lọc tiếng ồn nền (quạt PC, điều hòa) trước khi gọi API
  - Micro tự dò thiết bị "sống" (có tín hiệu), bỏ qua mic bị mute phần cứng

API công khai (brain.py + test_pipeline.py phụ thuộc):
  register_callbacks(on_transcript, on_wake_word)
  continuous_listen_loop()      # vòng lặp nghe liên tục (chạy trong thread riêng)
  listen_for_question()         # nghe 1 câu hỏi sau wake-word
  pause_listening() / resume_listening()
"""

import os
import sys
import time
import queue
import threading
import collections
from concurrent.futures import ThreadPoolExecutor

# Fix Windows terminal encoding (giống brain.py) — tránh crash khi in emoji/Việt
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from config import settings
from server.voice.audio.processing import (
    denoise_pcm as _denoise_pcm_impl,
    rms_of_block as _rms_of_block_impl,
    spectral_flatness as _spectral_flatness_impl,
    wrap_wav as _wrap_wav_impl,
)
from server.voice.speech.filters import (
    contains_wake_word as _contains_wake_word,
    is_hallucination as _is_hallucination,
    levenshtein as _levenshtein,
    strip_diacritics as _strip_diacritics,
)
from server.voice.speech.transcription import UNSET as _UNSET
from server.voice.speech.transcription import transcribe_bytes as _transcribe_bytes_impl

# ─── MQTT để log transcript lên dashboard ─────────────────────────────────────
try:
    from server import mqtt_bridge
except Exception:
    mqtt_bridge = None

# ─── Cờ TTS đang phát — để mic KHÔNG thu tiếng loa của chính Moon ───────────
try:
    from server.tts import is_speaking as _tts_speaking
except Exception:
    def _tts_speaking() -> bool:
        return False

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 16000                       # Chuẩn của Whisper
BLOCK_MS      = 30
BLOCK_FRAMES  = SAMPLE_RATE * BLOCK_MS // 1000   # 480 frames/block

GROQ_API_KEY  = getattr(settings, "GROQ_API_KEY", None)
STT_MODEL     = getattr(settings, "STT_MODEL", "whisper-large-v3-turbo")
# Pass câu hỏi: ưu tiên CHÍNH XÁC hơn tốc độ → large-v3 bản đầy đủ
STT_MODEL_QUESTION = getattr(settings, "STT_MODEL_QUESTION", "whisper-large-v3")
STT_LANGUAGE  = getattr(settings, "STT_LANGUAGE", None)   # None = tự phát hiện ngôn ngữ

VAD_NOISE_FLOOR   = getattr(settings, "VAD_NOISE_FLOOR", 0.03)   # RMS tối thiểu coi là tiếng nói
# Hệ số nhân ồn nền để ra ngưỡng: 2.0 = nhạy với giọng xa (đo thực tế: quạt 0.02
# → ngưỡng 0.04, chặn gust 0.035 mà vẫn nhận giọng 0.05+). Tăng lên 3.0 nếu phòng ồn.
VAD_AMBIENT_MULT  = getattr(settings, "VAD_AMBIENT_MULT", 2.0)
SPEECH_FLAT_MAX   = getattr(settings, "SPEECH_FLAT_MAX", 0.55)   # flatness > đây = ồn gió/quạt, không phải giọng

# ─── Khử ồn trước STT (tương đương Noise Suppression của Google Dịch) ────────
# Mặc định TẮT: với mic xa, spectral gating nuốt cả giọng nói (đã đo thực tế).
DENOISE_BEFORE_STT = getattr(settings, "DENOISE_BEFORE_STT", False)
try:
    import noisereduce as _nr
except ImportError:
    _nr = None
    print("⚠️  [VOICE] noisereduce chưa cài — bỏ qua khử ồn. pip install noisereduce")
WAKE_SILENCE_SEC  = getattr(settings, "WAKE_SILENCE_SEC", 1.2)   # im lặng kết thúc clip standby
QUESTION_SILENCE_SEC = getattr(settings, "QUESTION_SILENCE_SEC", 3.0)
QUESTION_MAX_SEC  = getattr(settings, "QUESTION_MAX_SEC", 20.0)
MIN_SPEECH_SEC    = 0.25   # tiếng nói thật phải dài tối thiểu 0.25s (loại tiếng ồn ngắn)

MIC_DEVICE_INDEX = getattr(settings, "MIC_DEVICE_INDEX", None)
MIC_SOURCE = getattr(settings, "MIC_SOURCE", "auto")   # auto | local | remote

# ─── Groq client ──────────────────────────────────────────────────────────────
groq_client = None
try:
    from groq import Groq
    if GROQ_API_KEY:
        groq_client = Groq(api_key=GROQ_API_KEY)
        print(f"✅ [VOICE] Groq STT sẵn sàng. Model: {STT_MODEL}")
    else:
        print("⚠️  [VOICE] Chưa có GROQ_API_KEY trong settings.py.")
except ImportError:
    print("⚠️  [VOICE] groq chưa cài. Chạy: pip install groq")
except Exception as e:
    print(f"❌ [VOICE] Lỗi khởi tạo Groq: {e}")

# ─── sounddevice + numpy ──────────────────────────────────────────────────────
sd = None
np = None
try:
    import sounddevice as _sd
    import numpy as _np
    sd = _sd
    np = _np
    print("✅ [VOICE] sounddevice sẵn sàng.")
except ImportError:
    print("❌ [VOICE] sounddevice/numpy chưa cài. Chạy: pip install sounddevice numpy")

# ─── Trạng thái điều khiển ────────────────────────────────────────────────────
_paused_event = threading.Event()    # set = tạm dừng vòng lặp nghe (khi AI bận)
_abort_event  = threading.Event()    # set = ngắt bản ghi âm hiện tại ngay lập tức
_external_mic = threading.Event()    # set = mic trình duyệt đang nghe liên tục → loop server nghỉ
_mic_lock     = threading.Lock()     # chỉ 1 luồng được mở mic tại 1 thời điểm
_standby_stream_lock = threading.Lock()
_standby_stream = None               # stream VAD standby; dừng hẳn khi pipeline chiếm mic
_device_cache = None                 # (index, name) — cache sau lần dò đầu tiên

_on_transcript_cbs = []
_on_wake_word_cbs  = []
_on_wake_rescue_cbs = []   # sửa lỗi ASR để cứu wake khi bản thô trượt
_wake_exec = ThreadPoolExecutor(max_workers=2)   # transcribe nền — tai không ngừng nghe

# ═══════════════════════════════════════════════════════════════════════════════
#  CHỌN MICROPHONE — dò thiết bị có tín hiệu thật (bỏ qua mic bị mute)
# ═══════════════════════════════════════════════════════════════════════════════

def _rms_of_block(data: bytes) -> float:
    return _rms_of_block_impl(data, np)


def _spectral_flatness(data: bytes) -> float:
    return _spectral_flatness_impl(data, np)


def _probe_device_rms(dev_index: int, duration: float = 1.0) -> float:
    """
    Mở mic trong `duration` giây, trả về RMS trung bình (0.0 nếu lỗi/im lặng).
    Bỏ 0.4s đầu: Realtek array nhả toàn số 0 trong ~0.5s warm-up
    (nếu không bỏ, probe luôn kết luận 'im lặng' dù mic vẫn tốt).
    """
    try:
        q = queue.Queue()

        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            device=dev_index, blocksize=BLOCK_FRAMES, callback=_cb):
            deadline = time.time() + duration
            warmup_until = time.time() + 0.4
            blocks = []
            while time.time() < deadline:
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    break
                if time.time() < warmup_until:
                    continue
                blocks.append(data)
        if not blocks:
            return 0.0
        return _rms_of_block(b"".join(blocks))
    except Exception:
        return 0.0


def _select_input_device():
    """
    Chọn micro input:
      - MIC_DEVICE_INDEX cấu hình thủ công → dùng luôn
      - Ưu tiên default của Windows nếu nó CÓ tín hiệu (RMS > 3e-5)
      - Nếu không → chọn thiết bị có tín hiệu mạnh nhất
    Trả về (index, name) hoặc None.
    """
    global _device_cache
    if sd is None:
        return None
    if _device_cache:
        return _device_cache

    # Thủ công từ settings
    if MIC_DEVICE_INDEX is not None:
        try:
            d = sd.query_devices(MIC_DEVICE_INDEX, "input")
            _device_cache = (MIC_DEVICE_INDEX, d["name"])
            print(f"🎤 [VOICE] Dùng micro thủ công: #{MIC_DEVICE_INDEX} — {d['name']}")
            return _device_cache
        except Exception as e:
            print(f"❌ [VOICE] MIC_DEVICE_INDEX={MIC_DEVICE_INDEX} không hợp lệ: {e}")
            return None

    try:
        devices = sd.query_devices()
        default_idx = sd.default.device[0]
    except Exception as e:
        print(f"❌ [VOICE] Không liệt kê được thiết bị âm thanh: {e}")
        return None

    input_idxs = [i for i, d in enumerate(devices)
                  if d.get("max_input_channels", 0) > 0]
    if not input_idxs:
        print("❌ [VOICE] Không tìm thấy microphone nào.")
        return None

    # 1) Thử default trước — nếu "sống" thì dùng luôn (nhanh nhất)
    if default_idx in input_idxs:
        if _probe_device_rms(default_idx) > 3e-5:
            name = devices[default_idx]["name"]
            _device_cache = (default_idx, name)
            print(f"🎤 [VOICE] Mic default hoạt động tốt: #{default_idx} — {name}")
            return _device_cache

    # 2) Default im lặng (hay bị hardware mute) → dò tất cả, chọn thiết bị mạnh nhất
    print("🔎 [VOICE] Mic default im lặng — đang dò các micro khác...")
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
        print(f"🎤 [VOICE] Chọn micro có tín hiệu: #{best_idx} — {name} (RMS={best_rms:.4f})")
        return _device_cache

    # 3) Fallback: vẫn dùng default (có thể tín hiệu rất nhỏ)
    if default_idx is not None and default_idx >= 0:
        name = devices[default_idx]["name"]
        _device_cache = (default_idx, name)
        print(f"⚠️  [VOICE] Không dò được tín hiệu — dùng default: #{default_idx} — {name}")
        return _device_cache
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  GHI ÂM VỚI VAD (Voice Activity Detection)
# ═══════════════════════════════════════════════════════════════════════════════

def _record_until_silence(silence_sec: float = 2.0,
                          max_sec: float = 15.0,
                          wait_timeout: float = None,
                          yield_on_pause: bool = True) -> bytes | None:
    """
    Ghi âm đến khi người dùng ngừng nói.

    Args:
        silence_sec:  im lặng bao lâu (sau khi đã có tiếng nói) thì dừng.
        max_sec:      giới hạn độ dài clip tối đa.
        wait_timeout: chờ tối đa bao lâu cho tiếng nói đầu tiên (None = chờ mãi).

    Returns:
        bytes PCM int16 16kHz mono, hoặc None nếu không thu được tiếng nói.
    """
    if sd is None:
        return None

    with _mic_lock:
        dev = _select_input_device()
        if dev is None:
            time.sleep(1)
            return None

        q = queue.Queue()

        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        frames = []
        preroll = collections.deque(maxlen=int(1.5 * 1000 / BLOCK_MS))  # 1.5s — trùm cả warm-up+calibration
        got_speech = False
        last_speech_time = 0.0
        peak = 0.0            # đỉnh giọng — cho cổng tương đối 55%
        speech_blocks = 0
        ambient_ema = 0.0    # noise floor thích nghi: trung bình động của ồn nền
        seen = 0
        calib_blocks = int(0.6 * 1000 / BLOCK_MS)  # 0.6s đầu: chỉ đo ồn nền (quạt...)
        start = time.time()
        min_speech_blocks = int(MIN_SPEECH_SEC * 1000 / BLOCK_MS)

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                device=dev[0], blocksize=BLOCK_FRAMES, callback=_cb):
                while True:
                    # Bị yêu cầu dừng (pause) → hủy bản ghi
                    if _abort_event.is_set():
                        return None

                    # AI chuyển bận (listening/thinking/speaking) mà chưa có giọng
                    # → nhường mic ngay cho listen_for_question (chống race tranh mic)
                    # (chỉ áp dụng cho bản ghi standby; bản ghi câu hỏi tắt cờ này)
                    if yield_on_pause and _paused_event.is_set() and not got_speech:
                        return None

                    # Loa Moon đang phát TTS → clip sẽ bị bẩn bởi tiếng của chính
                    # Moon (gây tự kích wake-word) → hủy bản ghi này
                    if _tts_speaking():
                        return None

                    try:
                        data = q.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    now = time.time()
                    rms = _rms_of_block(data)

                    # ── Bỏ 0.4s warm-up: Realtek array nhả toàn số 0 khi vừa mở stream ──
                    # Nếu không bỏ, calibration học nhầm mức 0 → ngưỡng tụt về floor
                    # tĩnh → gust quạt (0.03+) lọt cổng năng lượng.
                    # Ngoại lệ: block năng lượng kiểu giọng (RMS > 0.10) hoặc đã có
                    # giọng → đi thẳng vào xử lý, không nuốt mất đầu câu.
                    if (now - start) < 0.4 and not got_speech and rms <= 0.10:
                        preroll.append(data)
                        continue

                    # ── Hiệu chuẩn ồn nền 0.6s (quạt, điều hòa...) ─────────
                    # Sau warm-up, EMA học mức ồn THẬT → ngưỡng = 3× ồn nền
                    # (quạt 0.02 → ngưỡng 0.06: chặn gust quạt, nhận giọng 0.1+).
                    if seen < calib_blocks and not got_speech and rms <= 0.10:
                        seen += 1
                        ambient_ema = rms if seen == 1 else ambient_ema * 0.7 + rms * 0.3
                        preroll.append(data)
                        continue

                    # Ngưỡng thích nghi: ồn nền cao (quạt, loa) → ngưỡng tự nâng
                    threshold = max(VAD_NOISE_FLOOR, ambient_ema * VAD_AMBIENT_MULT)
                    # Cổng tương đối: khi đã có giọng, block phải ≥ 55% đỉnh giọng —
                    # tiếng TV/media (to ngang ngưỡng tuyệt đối) không bị tính là giọng,
                    # nhờ đó chốt im lặng sớm thay vì kẹt tới max_sec
                    rel_gate = peak * 0.55 if (got_speech and peak > 0) else 0.0
                    # Điều kiện kép: năng lượng ĐỦ LỚN + phổ KIỂU GIỌNG NÓI
                    # (loại bộc phát tiếng quạt/gió có năng lượng cao nhưng phổ phẳng)
                    is_speech = (rms >= threshold and rms >= rel_gate
                                 and _spectral_flatness(data) < SPEECH_FLAT_MAX)

                    if is_speech:
                        if not got_speech:
                            got_speech = True
                            frames.extend(preroll)   # ghép phần preroll vào đầu clip
                        peak = max(peak, rms)
                        speech_blocks += 1
                        last_speech_time = now
                        frames.append(data)
                    else:
                        if got_speech:
                            frames.append(data)      # vẫn ghi phần im lặng cuối câu
                            if now - last_speech_time >= silence_sec:
                                break                # đủ im lặng → kết thúc
                        else:
                            ambient_ema = ambient_ema * 0.9 + rms * 0.1
                            preroll.append(data)
                            if wait_timeout and (now - start) > wait_timeout:
                                return None          # chờ quá lâu, không ai nói

                    if (now - start) > max_sec:
                        break
        except Exception as e:
            print(f"❌ [VOICE] Lỗi ghi âm: {e}")
            return None

        if not got_speech or not frames:
            return None
        if speech_blocks < min_speech_blocks:   # < 0.25s → tiếng ồn ngắn, không phải giọng
            return None
        return b"".join(frames)


# ═══════════════════════════════════════════════════════════════════════════════
#  TRANSCRIBE — Groq Whisper
# ═══════════════════════════════════════════════════════════════════════════════

def transcribe_bytes(data: bytes, filename: str = "moon_clip.wav",
                     language=_UNSET, prompt: str = None,
                     model: str = None) -> str:
    return _transcribe_bytes_impl(
        groq_client, data, filename, language=language, prompt=prompt, model=model,
        default_language=STT_LANGUAGE, default_model=STT_MODEL,
    )


def _denoise_pcm(audio: bytes) -> bytes:
    return _denoise_pcm_impl(
        audio, np_module=np, reducer=_nr, enabled=DENOISE_BEFORE_STT,
        sample_rate=SAMPLE_RATE,
    )


def _wrap_wav(audio: bytes) -> bytes:
    return _wrap_wav_impl(audio, SAMPLE_RATE)


def _transcribe(audio: bytes, model: str = None) -> str:
    """PCM int16 16kHz mono → khử ồn → WAV → Groq (1 pass, theo STT_LANGUAGE)."""
    if not audio:
        return ""
    return transcribe_bytes(_wrap_wav(_denoise_pcm(audio)), "moon_clip.wav", model=model)


def _transcribe_dual(audio: bytes) -> str:
    """Compatibility entry point: one STT request, no prompted wake retries."""
    # One request only: prompted retries can invent the wakeword in noise.
    return _transcribe(audio)


# ═══════════════════════════════════════════════════════════════════════════════
#  BỘ LỌC CHỐNG HALLUCINATION + WAKE-WORD
# ═══════════════════════════════════════════════════════════════════════════════

# Whisper hay "bịa" các cụm này khi đầu vào là tiếng ồn
# ═══════════════════════════════════════════════════════════════════════════════
#  API CÔNG KHAI — brain.py sử dụng
# ═══════════════════════════════════════════════════════════════════════════════

def register_callbacks(on_transcript=None, on_wake_word=None, on_wake_rescue=None):
    """Đăng ký callback. Gọi 1 lần trước khi chạy continuous_listen_loop().
    on_wake_rescue: fn(text) → text đã sửa — chỉ gọi khi wake KHÔNG bắt được
    từ bản thô (lớp cứu hộ, không thêm trễ vào đường wake bình thường)."""
    if on_transcript:
        _on_transcript_cbs.append(on_transcript)
    if on_wake_word:
        _on_wake_word_cbs.append(on_wake_word)
    if on_wake_rescue:
        _on_wake_rescue_cbs.append(on_wake_rescue)
    print(f"✅ [VOICE] Callbacks đăng ký: {len(_on_transcript_cbs)} transcript, "
          f"{len(_on_wake_word_cbs)} wake-word.")


def pause_listening():
    """Tạm dừng vòng lặp nghe (khi AI đang listening/thinking/speaking)."""
    _paused_event.set()
    _abort_event.set()      # ngắt cả bản ghi âm đang chạy
    # Không chỉ bỏ qua callback: phải nhả thiết bị để
    # listen_for_question() có thể mở mic mà không tranh stream standby.
    _stop_standby_stream()


def resume_listening():
    """Tiếp tục nghe (khi AI quay về standby)."""
    _abort_event.clear()
    _paused_event.clear()
    if not _external_mic.is_set():
        _start_standby_stream()


def _stop_standby_stream():
    with _standby_stream_lock:
        if _standby_stream is not None:
            try:
                if _standby_stream.active:
                    _standby_stream.stop()
            except Exception as e:
                print(f"⚠️  [VOICE] Không dừng được stream standby: {e}")


def _start_standby_stream():
    with _standby_stream_lock:
        if _standby_stream is not None:
            try:
                if not _standby_stream.active:
                    _standby_stream.start()
            except Exception as e:
                print(f"⚠️  [VOICE] Không khởi động lại được stream standby: {e}")


def set_external_mic(on: bool):
    """Bật/tắt chế độ mic trình duyệt liên tục → vòng lặp server nhường đường."""
    if on:
        _external_mic.set()
        _stop_standby_stream()
        print("🎙️ [VOICE] Mic trình duyệt liên tục BẬT — loop server tạm nghỉ.")
    else:
        _external_mic.clear()
        if not _paused_event.is_set():
            _start_standby_stream()
        print("🎙️ [VOICE] Mic trình duyệt TẮT — loop server nghe lại.")


def external_mic_active() -> bool:
    """True khi dashboard đang sở hữu microphone."""
    return _external_mic.is_set()


def _publish_voice_log(text: str):
    if mqtt_bridge:
        try:
            mqtt_bridge.publish(settings.TOPIC_VOICE_LOG, text)
        except Exception:
            pass


def continuous_listen_loop():
    """
    Vòng lặp nghe liên tục (block — chạy trong thread riêng):
      ghi clip ngắn → Groq STT → lọc hallucination → callback transcript
        → nếu có wake-word → callback wake-word.

    Giống Vector: sau mỗi câu trả lời robot quay về vòng lặp này ngay,
    luôn sẵn sàng nghe "Moon".
    """
    if sd is None or groq_client is None:
        print("❌ [VOICE] Thiếu sounddevice hoặc Groq — không thể nghe.")
        return

    if MIC_SOURCE == "remote":
        print("🎙️ [VOICE] MIC_SOURCE=remote — não chỉ nghe clip từ robot/browser qua MQTT.")
        while True:
            time.sleep(1)

    print("👂 [VOICE] Vòng lặp nghe liên tục bắt đầu. Nói \"Moon\" để gọi mình!")
    dev = _select_input_device()
    while dev is None:
        time.sleep(2)
        dev = _select_input_device()

    q = queue.Queue()

    def _cb(indata, frames, t, status):
        q.put(bytes(indata))

    def _emit_clip(audio: bytes):
        """Transcribe + route trong thread riêng — tai KHÔNG ngừng nghe."""
        def _work():
            text = _transcribe_dual(audio)
            if _paused_event.is_set():
                return
            if not text or _is_hallucination(text):
                return
            _publish_voice_log(text)
            for cb in _on_transcript_cbs:
                try:
                    cb(text)
                except Exception as e:
                    print(f"❌ [VOICE] Lỗi callback transcript: {e}")
            if _contains_wake_word(text):
                for cb in _on_wake_word_cbs:
                    try:
                        cb(text)
                    except Exception as e:
                        print(f"❌ [VOICE] Lỗi callback wake-word: {e}")
            elif _on_wake_rescue_cbs:
                # Cứu hộ: sửa lỗi chính tả rồi thử lại wake (vd 'Hai bạn nàng' → 'Hey Moon')
                for rc in _on_wake_rescue_cbs:
                    try:
                        fixed = rc(text)
                    except Exception:
                        fixed = None
                    if fixed and fixed != text and _contains_wake_word(fixed):
                        print(f"🛟 [VOICE] Wake cứu hộ nhờ sửa ASR: \"{text}\" → \"{fixed}\"")
                        for cb in _on_wake_word_cbs:
                            try:
                                cb(fixed)
                            except Exception as e:
                                print(f"❌ [VOICE] Lỗi callback wake-word: {e}")
                        break
        _wake_exec.submit(_work)

    min_blocks  = int(MIN_SPEECH_SEC * 1000 / BLOCK_MS)
    preroll_max = int(1.5 * 1000 / BLOCK_MS)

    global _standby_stream
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        device=dev[0], blocksize=BLOCK_FRAMES, callback=_cb) as stream:
        with _standby_stream_lock:
            _standby_stream = stream
        # ── warm-up 0.4s + hiệu chuẩn ồn nền 0.6–1s — MỘT lần duy nhất ──
        # Theo THỜI GIAN (không theo số block quiet) → không bao giờ treo
        # kể cả khi phòng ồn hơn 0.10 RMS; lấy trung vị chống outlier giọng nói.
        samples = []
        t0 = time.time()
        while time.time() - t0 < 1.0:
            data = q.get(timeout=2)
            if time.time() - t0 < 0.4:
                continue
            samples.append(_rms_of_block(data))
        if samples:
            samples.sort()
            ambient = samples[len(samples) // 2]
        else:
            ambient = 0.0
        threshold_base = max(VAD_NOISE_FLOOR, ambient * VAD_AMBIENT_MULT)
        print(f"🎚️ [VOICE] ồn nền hiệu chuẩn: {ambient:.3f} → ngưỡng {threshold_base:.3f}")

        # ── VAD streaming: idle → speech → im lặng 0.9s → chốt clip ──
        state = "idle"
        preroll = collections.deque(maxlen=preroll_max)
        clip, peak, speech_blocks = [], 0.0, 0
        last_speech, speech_start = 0.0, 0.0

        try:
            while True:
                # AI bận / mic ngoài / TTS phát → xả hàng đợi & reset (chống tự kích)
                if _paused_event.is_set() or _external_mic.is_set() or _tts_speaking():
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            break
                    state, clip, peak, speech_blocks = "idle", [], 0.0, 0
                    preroll.clear()
                    time.sleep(0.1)
                    continue

                try:
                    data = q.get(timeout=1.0)
                except queue.Empty:
                    continue

                now = time.time()
                rms = _rms_of_block(data)
                rel = peak * 0.55 if state == "speech" else 0.0
                is_sp = (rms >= threshold_base and rms >= rel
                         and _spectral_flatness(data) < SPEECH_FLAT_MAX)

                if state == "idle":
                    if is_sp:
                        state = "speech"
                        clip = list(preroll) + [data]
                        peak, speech_blocks = rms, 1
                        last_speech = speech_start = now
                    else:
                        ambient = ambient * 0.9 + rms * 0.1   # thích nghi liên tục
                        threshold_base = max(VAD_NOISE_FLOOR, ambient * VAD_AMBIENT_MULT)
                        preroll.append(data)
                else:
                    clip.append(data)
                    if is_sp:
                        peak = max(peak, rms)
                        speech_blocks += 1
                        last_speech = now
                    if (state == "speech" and now - last_speech >= WAKE_SILENCE_SEC) \
                            or (state == "speech" and now - speech_start > 8.0):
                        if speech_blocks >= min_blocks:
                            _emit_clip(b"".join(clip))   # nền — không chặn tai
                        state, clip, peak, speech_blocks = "idle", [], 0.0, 0
        finally:
            with _standby_stream_lock:
                if _standby_stream is stream:
                    _standby_stream = None


def listen_for_question() -> str | None:
    """
    Nghe câu hỏi sau khi phát hiện wake-word.
    Chờ tối đa 8s cho tiếng nói đầu tiên, kết thúc sau QUESTION_SILENCE_SEC im lặng.
    """
    if sd is None or groq_client is None:
        return None

    _abort_event.clear()   # cho phép ghi âm dù vòng lặp chính đang pause
    audio = _record_until_silence(silence_sec=QUESTION_SILENCE_SEC,
                                  max_sec=QUESTION_MAX_SEC,
                                  wait_timeout=6.0,
                                  yield_on_pause=False)
    if not audio:
        return None

    text = _transcribe(audio, model=STT_MODEL_QUESTION)
    if not text or _is_hallucination(text):
        return None

    _publish_voice_log(text)
    return text


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST ĐỨNG MỘT MÌNH
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=== Test Voice Module ===")
    print(f"Model: {STT_MODEL} | Language: {STT_LANGUAGE or 'auto'} | "
          f"Noise floor: {VAD_NOISE_FLOOR}")
    dev = _select_input_device()
    if not dev:
        print("❌ Không có microphone.")
        sys.exit(1)

    register_callbacks(
        on_transcript=lambda t: print(f"   → transcript: {t}"),
        on_wake_word=lambda t: print(f"🐼 → WAKE-WORD: {t}"),
    )
    continuous_listen_loop()


if __name__ == "__main__":
    main()
