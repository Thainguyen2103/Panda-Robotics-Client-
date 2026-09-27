"""
Wake-word engine kiểu Anki Vector — server/voice/wake/porcupine.py
=======================================================
Bắt từ khóa "Moon" BẰNG ÂM HỌC trên thiết bị (Porcupine), KHÔNG đi qua ASR:
  - Không phụ thuộc ngôn ngữ câu nói xung quanh (Việt/Anh/trộn đều được)
  - Không bị Whisper Việt-hóa "Moon" thành "bạn nàng"/"Anna"
  - Độ trễ ~10ms, CPU không đáng kể

Phần nhận diện câu hỏi SAU wake-word vẫn gửi cloud (Groq Whisper) — đúng
kiến trúc của Vector: KWS local + ASR cloud.

Kích hoạt (một lần):
  1. pip install pvporcupine
  2. Tạo tài khoản miễn phí tại https://console.picovoice.ai/ → copy AccessKey
  3. Console → Porcupine → "Create Keyword" → gõ "Moon" → tải file .ppn
     (chọn nền tảng Windows x86_64) → lưu vào models/voice/moon.ppn
  4. Điền PICOVOICE_ACCESS_KEY trong config/settings.py
  5. Khởi động lại hệ thống.

Khi chưa cấu hình: fallback Whisper một lượt; xem docs/voice.md để test độc lập.
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

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from config import settings
from server.voice.paths import wake_model_path

ACCESS_KEY = getattr(settings, "PICOVOICE_ACCESS_KEY", "")
PPN_PATH = str(wake_model_path())

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


def run_loop(on_wake, should_listen=None, stop_event=None):
    """
    Vòng lặp bắt wake-word on-device (block — chạy trong thread riêng).

    Args:
        on_wake:        callback không tham số, gọi khi nghe thấy "Moon".
        should_listen:  callback trả về False để tạm ngưng (khi AI đang bận).
    """
    if not available():
        return

    import numpy as np
    import sounddevice as sd
    from server import tts

    h = _porcupine
    print("🔔 [WAKEWORD] Porcupine đang nghe 'Moon' (on-device, mọi ngôn ngữ)...")
    last_trigger = 0.0

    stopping = lambda: stop_event is not None and stop_event.is_set()
    while not stopping():
        # Quan trọng: không giữ InputStream mở khi Brain đang thu câu hỏi
        # hoặc phát TTS. Windows không ổn định khi hai stream cùng tranh mic.
        if (should_listen and not should_listen()) or tts.is_speaking():
            time.sleep(0.1)
            continue

        q = queue.Queue()

        def _cb(indata, frames, t, status):
            q.put(bytes(indata))

        detected = False
        with sd.InputStream(samplerate=h.sample_rate, channels=1, dtype="int16",
                            device=None, blocksize=h.frame_length, callback=_cb):
            while (not should_listen or should_listen()) \
                    and not tts.is_speaking() and not stopping():
                try:
                    data = q.get(timeout=0.25)
                except queue.Empty:
                    continue

                keyword_index = h.process(np.frombuffer(data, dtype=np.int16))
                if keyword_index >= 0:
                    now = time.time()
                    if now - last_trigger > 1.5:   # debounce 1.5s
                        last_trigger = now
                        detected = True
                        print("🔔 [WAKEWORD] Porcupine bắt được 'Moon'!")
                        break

        # Stream đã đóng trước khi pipeline mở mic để nghe câu hỏi.
        if detected and not stopping():
            try:
                on_wake()
            except Exception as e:
                print(f"❌ [WAKEWORD] Lỗi callback wake: {e}")
