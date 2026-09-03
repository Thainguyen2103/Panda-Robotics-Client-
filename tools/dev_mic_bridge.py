# tools/dev_mic_bridge.py — GIẢ LẬP mic robot bằng mic laptop
# ============================================================
# Bắt clip giọng từ mic laptop (cùng VAD 3 lớp của voice.py) rồi publish
# base64 PCM 16kHz lên đúng topic mà robot ESP32 sẽ dùng sau này
# (panda/ai/clip) → brain xử lý y hệt, KHÔNG phân biệt nguồn.
#
# Mục đích: test hôm nay bằng mic laptop trên ĐÚNG code path của robot,
# để ngày lắp mic thật vào chỉ việc nạp firmware, não không đổi dòng nào.
#
# Cách dùng (2 terminal):
#   Terminal 1 (brain ở chế độ remote):
#       sửa settings: MIC_SOURCE = "remote"
#       python server/brain.py
#   Terminal 2 (bridge này):
#       python tools/dev_mic_bridge.py
#   Rồi nói "Panda..." vào mic laptop.
#
# Sau này robot thật: ESP32 publish clip cùng định dạng → gỡ bridge là xong.

import sys
import os
import time
import base64

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from server import voice, mqtt_bridge


def main():
    print("🎙️ [BRIDGE] Mic laptop → clip base64 →", settings.TOPIC_BROWSER_CLIP)
    print("   (giả lập mic robot — brain phải chạy với MIC_SOURCE='remote')")
    print("   Nói 'Panda...' để thử. Ctrl+C để dừng.\n")

    while True:
        try:
            audio = voice._record_until_silence(
                silence_sec=voice.WAKE_SILENCE_SEC, max_sec=10.0)
        except KeyboardInterrupt:
            print("\n🛑 [BRIDGE] Dừng.")
            return
        if not audio:
            continue
        b64 = base64.b64encode(audio).decode()
        mqtt_bridge.publish(settings.TOPIC_BROWSER_CLIP, b64)
        print(f"📤 [BRIDGE] Đã gửi clip {len(audio) // 1024} KB lên MQTT")


if __name__ == "__main__":
    main()
