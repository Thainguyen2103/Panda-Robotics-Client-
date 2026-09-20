"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: vad.py (Lắng nghe & Lọc tiếng ồn)
--------------------------------------------------------------------------------
Nhiệm vụ: Mở micro và tự động ngắt ghi âm khi người dùng ngừng nói.

[CẤU TRÚC CHÍNH]
1. select_input_device(): Tự động duyệt danh sách micro của Windows để tìm cái có tín hiệu tốt nhất.
2. _rms() & _spectral_flatness(): Dùng toán học để phân biệt tiếng người nói với tiếng ồn rộng băng (quạt máy, gió).
3. record_until_silence(): Thu âm thông minh. Nếu người dùng im lặng quá 2 giây (silence_sec), hàm sẽ tự động cắt âm thanh và trả về.
"""
# ==============================================================================
# vad.py — Voice Activity Detection (Phát hiện tiếng nói con người)
# Biến Microphone thành một cái tai thông minh: Chỉ ghi âm khi có người nói,
# Lọc bỏ tiếng ồn môi trường (tiếng quạt, tiếng gió)
# ==============================================================================

import io
import os
import sys
import queue
import wave
import time
import threading
import collections

# Cấu hình UTF-8 để không bị lỗi font khi in chữ Tiếng Việt ra màn hình Console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Trỏ đường dẫn gốc để import file cấu hình settings.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import settings

# ─── Cấu hình Thông số Âm thanh (Audio Specs) ─────────────────────────────────
SAMPLE_RATE    = 16_000                             # Chuẩn tần số lấy mẫu của Whisper (16kHz)
BLOCK_MS       = 30                                 # Cắt âm thanh thành từng cục nhỏ 30 mili-giây để xử lý
BLOCK_FRAMES   = SAMPLE_RATE * BLOCK_MS // 1000     # Tính ra số khung hình (frames) cho mỗi cục (480 frames)

# Ngưỡng phát hiện tiếng nói (Volume tối thiểu để mic kích hoạt)
VAD_NOISE_FLOOR  = getattr(settings, "VAD_NOISE_FLOOR",  0.03)
# Tỷ lệ khuếch đại: Tiếng nói phải to gấp 2 lần tiếng ồn môi trường thì mới tính
VAD_AMBIENT_MULT = getattr(settings, "VAD_AMBIENT_MULT", 2.0)
# Ngưỡng Độ phẳng phổ (Để phân biệt giọng nói có cao độ rõ ràng vs Tiếng quạt máy kêu xè xè)
SPEECH_FLAT_MAX  = getattr(settings, "SPEECH_FLAT_MAX",  0.55)
# Nếu tiếng động quá ngắn (<0.25s) thì coi như là tiếng gõ bàn phím, tiếng tạch tạch -> Bỏ qua
MIN_SPEECH_SEC   = 0.25

# Tùy chọn: Chọn cứng 1 cái Mic thay vì để máy tự dò (Nếu máy có nhiều mic)
MIC_DEVICE_INDEX = getattr(settings, "MIC_DEVICE_INDEX", None)

# ─── Khởi tạo Thư viện phần cứng (Sounddevice & Numpy) ───────────────────────
try:
    import sounddevice as _sd
    import numpy as _np
    print("✅ [VAD] sounddevice sẵn sàng.")
except ImportError:
    _sd = _np = None
    print("❌ [VAD] sounddevice/numpy chưa cài. Hướng dẫn: pip install sounddevice numpy")

# ─── Biến Lưu trữ Trạng thái ──────────────────────────────────────────────────
# Bộ nhớ đệm lưu tên của cái Mic xịn nhất vừa dò được (Để lần sau đỡ mất công dò lại)
_device_cache: tuple | None = None
# Khóa an toàn khi nhiều luồng cùng tranh giành quyền xài Microphone
_mic_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
#  CÁC THUẬT TOÁN TOÁN HỌC ĐỂ NHẬN DIỆN ÂM THANH
# ══════════════════════════════════════════════════════════════════════════════
def _rms(data: bytes) -> float:
    """
    RMS (Root Mean Square): Tính 'Năng lượng' (Độ to) của âm thanh.
    Trả về số từ 0.0 (im lặng tuyệt đối) đến 1.0 (âm thanh to hết cỡ vỡ loa).
    """
    # Ép kiểu dữ liệu dạng Byte thô (int16) sang mảng số thực (float32) để dễ tính toán
    arr = _np.frombuffer(data, dtype=_np.int16).astype(_np.float32) / 32768.0
    # Công thức RMS: Căn bậc hai của trung bình cộng bình phương các biên độ
    return float(_np.sqrt(_np.mean(arr ** 2))) if arr.size else 0.0


def _spectral_flatness(data: bytes) -> float:
    """
    Độ phẳng phổ (Spectral Flatness). Chỉ số từ 0 đến 1.
      - Giọng nói con người có thanh quản -> Tạo ra các Hài âm (Harmonics) nổi bật -> Độ phẳng THẤP (0.1–0.4)
      - Tiếng quạt máy, tiếng gió, tiếng suối chảy -> Năng lượng rải đều ra mọi tần số -> Độ phẳng CAO (0.6–0.9)
    Nhờ thuật toán này, dù bạn bật quạt chĩa thẳng vào Mic, Robot vẫn biết đó không phải là người nói!
    """
    arr = _np.frombuffer(data, dtype=_np.int16).astype(_np.float32) / 32768.0
    if arr.size == 0:
        return 1.0
    
    # Biến đổi Fourier (FFT) để phân tích âm thanh từ 'Miền thời gian' sang 'Miền tần số'
    spec = _np.abs(_np.fft.rfft(arr * _np.hanning(arr.size))) ** 2
    spec = spec[1:]  # Cắt bỏ dòng DC (Tần số 0Hz)
    
    # Tính Trung bình cộng (Arithmetic Mean)
    mean = float(_np.mean(spec))
    if mean <= 1e-12:
        return 1.0
        
    # Tính Trung bình nhân (Geometric Mean)
    geo = float(_np.exp(_np.mean(_np.log(spec + 1e-12))))
    
    # Trả về Tỷ lệ: Trung bình nhân / Trung bình cộng
    return min(1.0, geo / mean)


# ══════════════════════════════════════════════════════════════════════════════
#  TỰ ĐỘNG CHỌN MICROPHONE TỐT NHẤT
# ══════════════════════════════════════════════════════════════════════════════
def _probe_device_rms(dev_index: int, duration: float = 1.0) -> float:
    """
    Mở thử cái Mic trong 1 giây xem nó có hoạt động không, độ ồn là bao nhiêu.
    (Lưu ý: 0.4s đầu tiên các dòng mic Realtek thường bị đơ nhả ra số 0 nên phải bỏ qua).
    """
    try:
        q = queue.Queue()
        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        # Mở thử luồng âm thanh
        with _sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                             device=dev_index, blocksize=BLOCK_FRAMES, callback=_cb):
            deadline = time.time() + duration
            warmup = time.time() + 0.4
            blocks = []
            
            # Thu thập âm thanh tới khi hết thời gian
            while time.time() < deadline:
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    break
                # Bỏ qua 0.4s đầu bị đơ
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
    Chiến lược săn lùng Microphone:
      1. Nếu chủ nhân đã cài cứng (MIC_DEVICE_INDEX) ở settings -> Xài luôn.
      2. Nếu Mic mặc định của Windows xài ngon (Có tín hiệu RMS > 3e-5) -> Xài luôn.
      3. Nếu cắm nhiều mic mà mic mặc định bị điếc -> Quét hết dàn mic, lấy cái nào to nhất.
    """
    global _device_cache
    if _sd is None:
        return None
    # Nếu đã tìm được từ trước rồi thì thôi không dò nữa
    if _device_cache:
        return _device_cache

    # 1. Thủ công từ settings
    if MIC_DEVICE_INDEX is not None:
        try:
            d = _sd.query_devices(MIC_DEVICE_INDEX, "input")
            _device_cache = (MIC_DEVICE_INDEX, d["name"])
            print(f"🎤 [VAD] Mic thủ công: #{MIC_DEVICE_INDEX} — {d['name']}")
            return _device_cache
        except Exception as e:
            print(f"❌ [VAD] Khai báo MIC_DEVICE_INDEX={MIC_DEVICE_INDEX} bị sai: {e}")
            return None

    # Lấy danh sách toàn bộ thiết bị âm thanh
    try:
        devices = _sd.query_devices()
        default_idx = _sd.default.device[0]
    except Exception as e:
        print(f"❌ [VAD] Lỗi thư viện không Liệt kê được danh sách âm thanh: {e}")
        return None

    # Lọc ra những cái nào có 'max_input_channels > 0' (Tức là Microphone, chứ không phải Loa)
    input_idxs = [i for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
    if not input_idxs:
        print("❌ [VAD] Không tìm thấy cái Microphone nào cắm vào máy cả.")
        return None

    # 2. Thử xài cái Mặc định của Windows xem có điếc không
    if default_idx in input_idxs and _probe_device_rms(default_idx) > 3e-5:
        name = devices[default_idx]["name"]
        _device_cache = (default_idx, name)
        print(f"🎤 [VAD] Đã chọn Mic mặc định: #{default_idx} — {name}")
        return _device_cache

    # 3. Mic mặc định bị điếc -> Dò tìm cái khác
    print("🔎 [VAD] Mic mặc định đang im lặng — Dò tìm các mic khác xung quanh...")
    best_idx, best_rms = None, 0.0
    for idx in input_idxs:
        if idx == default_idx:
            continue
        # Mở thử từng cái xem cái nào thu được tiếng to nhất
        rms = _probe_device_rms(idx)
        if rms > best_rms:
            best_idx, best_rms = idx, rms

    if best_idx is not None and best_rms > 3e-5:
        name = devices[best_idx]["name"]
        _device_cache = (best_idx, name)
        print(f"🎤 [VAD] Đã tìm thấy Mic có tín hiệu tốt nhất: #{best_idx} — {name} (RMS={best_rms:.4f})")
        return _device_cache

    # Nếu tất cả đều điếc (phòng im lặng tuyệt đối) -> Đành cắn răng xài lại cái Mặc định
    if default_idx is not None and default_idx >= 0:
        name = devices[default_idx]["name"]
        _device_cache = (default_idx, name)
        print(f"⚠️  [VAD] Nhắm mắt xài đỡ Mic mặc định (Dù tín hiệu đang rất yếu): #{default_idx} — {name}")
        return _device_cache

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  LÕI GHI ÂM THÔNG MINH (CHỈ THU KHI CÓ TIẾNG NGƯỜI)
# ══════════════════════════════════════════════════════════════════════════════
def record_until_silence(
    silence_sec: float = 2.0,
    max_sec: float = 15.0,
    wait_timeout: float = None,
    is_active_fn=None,
) -> bytes | None:
    """
    Quy trình Ghi Âm Thông Minh:
    Mở mic -> Đợi tiếng nói đầu tiên -> Bắt đầu ghi -> Ghi liên tục -> Thấy im lặng 2 giây -> Cắt băng -> Trả kết quả.
    """
    if _sd is None or _np is None:
        return None

    # Khóa lại không cho đứa khác xài chung Mic
    with _mic_lock:
        dev = select_input_device()
        if dev is None:
            time.sleep(1)
            return None

        q = queue.Queue()
        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        frames        = []          # Băng ghi âm chính thức
        # Cuộn băng ghi đệm (Chứa 1.5s âm thanh NGAY TRƯỚC khi người dùng mở miệng, để câu nói không bị mất chữ đầu)
        preroll       = collections.deque(maxlen=int(1.5 * 1000 / BLOCK_MS))
        
        got_speech    = False       # Đã bắt được tiếng nói chưa?
        last_speech_t = 0.0         # Thời gian của chữ cuối cùng
        peak          = 0.0         # Mức âm lượng to nhất từng thu được
        speech_blocks = 0           # Đã thu được bao nhiêu cục âm thanh có tiếng người
        
        ambient_ema   = 0.0         # Thuật toán đo ồn nền tự động theo thời gian (Exponential Moving Average)
        seen          = 0           
        calib_blocks  = int(0.6 * 1000 / BLOCK_MS)  # Cần 0.6s để làm quen với tiếng ồn của phòng
        
        start         = time.time()
        min_blocks    = int(MIN_SPEECH_SEC * 1000 / BLOCK_MS) # Câu quá ngắn (<0.25s) thì bỏ qua

        try:
            # Chính thức MỞ MICROPHONE
            with _sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                 device=dev[0], blocksize=BLOCK_FRAMES, callback=_cb):
                while True:
                    # Nếu Robot bị tắt hoặc chuyển qua trạng thái khác -> Hủy ghi âm
                    if is_active_fn and not is_active_fn():
                        return None

                    try:
                        data = q.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    now = time.time()
                    rms = _rms(data)

                    # ── Khởi động: Bỏ qua 0.4s đầu tiên vì mic hay bị đơ ─────────
                    if (now - start) < 0.4 and not got_speech and rms <= 0.10:
                        preroll.append(data)
                        continue

                    # ── Hiệu chuẩn: Đo tiếng quạt máy xung quanh trong 0.6s ───────
                    if seen < calib_blocks and not got_speech and rms <= 0.10:
                        seen += 1
                        # Cập nhật mức ồn trung bình
                        ambient_ema = rms if seen == 1 else ambient_ema * 0.7 + rms * 0.3
                        preroll.append(data)
                        continue

                    # ── Tính toán Ngưỡng Nghe (Threshold) ─────────────────────────
                    # Ngưỡng kích hoạt = Độ ồn nền x 2 lần (Nhưng ít nhất phải đạt 0.03)
                    threshold = max(VAD_NOISE_FLOOR, ambient_ema * VAD_AMBIENT_MULT)
                    
                    # Nếu lúc trước nói rất to (peak cao) thì bây giờ nói nhỏ xíu sẽ không được tính (Để tránh tiếng vang)
                    rel_gate  = peak * 0.55 if (got_speech and peak > 0) else 0.0
                    
                    # QUYẾT ĐỊNH: ĐÂY CÓ PHẢI LÀ TIẾNG NGƯỜI KHÔNG?
                    is_speech = (rms >= threshold                            # 1. Phải to hơn ồn nền
                                 and rms >= rel_gate                         # 2. Không phải là tiếng vang vọng lại
                                 and _spectral_flatness(data) < SPEECH_FLAT_MAX) # 3. Không phải tiếng quạt (Độ phẳng phổ < 0.55)

                    if is_speech:
                        # NẾU CÓ TIẾNG NGƯỜI
                        if not got_speech:
                            # Đánh dấu đã bắt đầu
                            got_speech = True
                            # Nối phần âm thanh ghi đệm (preroll) vào để không bị mất chữ đầu
                            frames.extend(preroll)
                            
                        peak = max(peak, rms)
                        speech_blocks += 1
                        last_speech_t = now
                        frames.append(data)
                    else:
                        # NẾU IM LẶNG
                        if got_speech:
                            frames.append(data)
                            # Nếu đã im lặng quá 2 giây (silence_sec) -> CẮT BĂNG!
                            if now - last_speech_t >= silence_sec:
                                break
                        else:
                            # Nếu chưa thấy ai nói gì, tiếp tục cập nhật độ ồn nền và nhét vào cuộn băng đệm
                            ambient_ema = ambient_ema * 0.9 + rms * 0.1
                            preroll.append(data)
                            # Nếu đợi quá lâu (wait_timeout) mà không ai nói -> Bỏ cuộc
                            if wait_timeout and (now - start) > wait_timeout:
                                return None

                    # Nếu người dùng nói dông dài lảm nhảm quá 15 giây (max_sec) -> Ép cắt băng!
                    if (now - start) > max_sec:
                        break

        except Exception as e:
            print(f"❌ [VAD] Lỗi phần cứng ghi âm: {e}")
            return None

        # Kiểm tra chất lượng cuộn băng: Nếu rỗng hoặc chỉ là 1 tiếng chạch < 0.25s -> Bỏ đi
        if not got_speech or not frames or speech_blocks < min_blocks:
            return None
            
        # Nối tất cả các mẩu âm thanh 30ms lại thành 1 cục bự và trả về
        return b"".join(frames)


# ══════════════════════════════════════════════════════════════════════════════
#  CHUYỂN ĐỔI ĐỊNH DẠNG ÂM THANH
# ══════════════════════════════════════════════════════════════════════════════
def wrap_wav(pcm: bytes) -> bytes:
    """
    Biến chuỗi dữ liệu thô (PCM) thành định dạng chuẩn (WAV file) để gửi đi lên mạn lưới AI (Groq Whisper).
    Giống như bỏ giấy vào bao thư đóng mộc đàng hoàng.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)                # Mono (1 kênh)
        wf.setsampwidth(2)                # 16-bit (2 bytes)
        wf.setframerate(SAMPLE_RATE)      # 16000 Hz
        wf.writeframes(pcm)
    return buf.getvalue()
