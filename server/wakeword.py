"""
Wake-word engine kiểu Anki Vector — server/wakeword.py
=======================================================
Bắt từ khóa "Panda" BẰNG ÂM HỌC trên thiết bị (Porcupine), KHÔNG đi qua ASR:
  - Không phụ thuộc ngôn ngữ câu nói xung quanh (Việt/Anh/trộn đều được)
  - Không bị Whisper Việt-hóa "Panda" thành "bạn nàng"/"Anna"
  - Độ trễ ~10ms, CPU không đáng kể

Phần nhận diện câu hỏi SAU wake-word vẫn gửi cloud (Groq Whisper) — đúng
kiến trúc của Vector: KWS local + ASR cloud.

Kích hoạt (một lần):
  1. pip install pvporcupine
  2. Tạo tài khoản miễn phí tại https://console.picovoice.ai/ → copy AccessKey
  3. Console → Porcupine → "Create Keyword" → gõ "Panda" → tải file .ppn
     (chọn nền tảng Windows x86_64) → lưu vào server/panda.ppn
  4. Điền PICOVOICE_ACCESS_KEY trong config/settings.py
  5. Khởi động lại hệ thống.

Khi chưa cấu hình: brain tự fallback về wake-word Whisper dual-pass (vi+en).
"""

import os
import sys
import time
import queue

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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

ACCESS_KEY = getattr(settings, "PICOVOICE_ACCESS_KEY", "")
PPN_PATH = getattr(settings, "PANDA_PPN_PATH", "") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "panda.ppn")

_porcupine = None
_init_tried = False


def available() -> bool:
    """True nếu Porcupine đã cấu hình đúng (key + file .ppn) và khởi tạo thành công."""
    global _porcupine, _init_tried
    if _porcupine is not None:
        return True
    if _init_tried:
        return False
    _init_tried = True

    if not ACCESS_KEY:
        return False
    if not os.path.exists(PPN_PATH):
        print(f"⚠️  [WAKEWORD] Chưa có file keyword: {PPN_PATH}")
        return False
    try:
        import pvporcupine
        _porcupine = pvporcupine.create(access_key=ACCESS_KEY, keyword_paths=[PPN_PATH])
        print("✅ [WAKEWORD] Porcupine sẵn sàng — wake-word on-device kiểu Vector!")
        return True
    except ImportError:
        print("⚠️  [WAKEWORD] pvporcupine chưa cài. Chạy: pip install pvporcupine")
        return False
    except Exception as e:
        print(f"❌ [WAKEWORD] Lỗi khởi tạo Porcupine: {e}")
        return False


def run_loop(on_wake, should_listen=None):
    """
    Vòng lặp bắt wake-word on-device (block — chạy trong thread riêng).

    Args:
        on_wake:        callback không tham số, gọi khi nghe thấy "Panda".
        should_listen:  callback trả về False để tạm ngưng (khi AI đang bận).
    """
    if not available():
        return

    import numpy as np
    import sounddevice as sd
    from server import tts

    h = _porcupine
    q = queue.Queue()

    def _cb(indata, frames, t, status):
        q.put(bytes(indata))

    print("🔔 [WAKEWORD] Porcupine đang nghe 'Panda' (on-device, mọi ngôn ngữ)...")
    last_trigger = 0.0

    with sd.InputStream(samplerate=h.sample_rate, channels=1, dtype="int16",
                        device=None, blocksize=h.frame_length, callback=_cb):
        while True:
            try:
                data = q.get(timeout=2.0)
            except queue.Empty:
                continue

            # Chống tự kích: bỏ qua khi loa Panda đang phát ("...Mình là Panda!")
            if tts.is_speaking():
                continue
            if should_listen and not should_listen():
                continue

            keyword_index = h.process(np.frombuffer(data, dtype=np.int16))
            if keyword_index >= 0:
                now = time.time()
                if now - last_trigger > 1.5:   # debounce 1.5s
                    last_trigger = now
                    print("🔔 [WAKEWORD] Porcupine bắt được 'Panda'!")
                    on_wake()
