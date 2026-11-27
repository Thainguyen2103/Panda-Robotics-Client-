"""CHE DO DUA XE: chi lai phan THAN, nhanh het muc. Khong noi dau robot, khong AI, khong camera.

Chay bang dua-xe.bat. Dau robot van cam nguon (man hinh sang) nhung khong ai noi vao nen camera
khong bat (firmware head-demo chi bat camera khi co laptop) -> nhuong dien cho motor.

Lai:
  Ban phim (cua so den "MOON dua xe" dang duoc chon): GIU W/S/A/D nhu xe dieu khien
      W tien, S lui, W+A / W+D cua vong khong dung, A/D mot minh xoay tai cho, tha het = phanh.
  Dien thoai (cung hotspot): mo dia chi in ra, giu ▲ + ◀ ... (2 ngon) giong ban phim.
  E / R tang / giam toc do | O bat/tat tu phanh truoc vat can | , . chinh lech | L phanh | Q thoat

Khac che do thuong (head_demo): toc do 255 (thuong 170), xuat phat boc hon, KHONG tu phanh truoc
vat can (xe ban phia truoc cung la "vat can"), chay lien tuc toi 2 phut.
"""
import os
import sys
import threading
import time

try:
    import msvcrt  # phim go o cua so den (Windows)
except ImportError:
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import body_link  # noqa: E402
from body_link import Body, find_body_port, keyboard_mode  # noqa: E402

TITLE = "MOON dua xe"
RACE_SPEED = 255
# Xuat phat: 120, moi ~40ms +40 -> 255 trong ~0,15 giay. Boc nhung chua giat thang 255 (motor dung
# yen bi dong manh ngay = hut dong lon nhat -> de sut ap, board than tu reset).
RACE_RAMP = (120, 40)


class _Shared:
    """remote.py can doi tuong nay (khung camera...) — che do dua xe khong co camera."""
    lock = threading.Lock()
    frame, frame_id, cam_fps, stop = None, 0, 0.0, False


class _Voice:
    """remote.py goi voice.body / voice.talk() — dua xe khong co giong noi."""

    def __init__(self, body):
        self.body = body

    def talk(self):
        pass


def main():
    if os.name == "nt":
        os.system(f"title {TITLE}")  # ten cua so: chi lai khi cua so nay dang duoc chon
    port = find_body_port()
    body = Body(port, speed=RACE_SPEED, max_run_sec=120, ramp=RACE_RAMP, safety=False)
    print(f"=== {TITLE}: than qua {body.port} ===")
    if port is None:
        print("Than qua WiFi: bat hotspot laptop + bat nguon robot, cho dong 'tim thay board than'.")

    shared = _Shared()
    if "--no-remote" not in sys.argv:
        import remote
        try:
            urls = remote.start(shared, _Voice(body))
            print(f"TAY CAM DIEN THOAI: vao cung hotspot, mo {urls[0] if urls else 'http://<IP laptop>:8080'}")
        except OSError as e:
            print(f"Khong mo duoc tay cam dien thoai ({e}): chay-demo.bat dang mo? Tat no di.")

    print("GIU W/S/A/D de lai (W+A = cua trai) | E/R toc do | O tu phanh vat can | , . chinh lech"
          " | L phanh | Q thoat")
    print(f"Toc do {body.speed}, tu phanh truoc vat can: TAT (bam O de bat)\n")

    key_mode, last_print = None, 0.0
    try:
        while True:
            km = keyboard_mode((TITLE,))
            if km:
                body.drive(km, hold=True)  # goi lai lien tuc khi con giu phim
            elif key_mode:
                body.stop()  # vua tha het phim -> phanh ngay
            key_mode = km

            while msvcrt and msvcrt.kbhit():
                c = msvcrt.getwch().lower()
                if c in ("q", "\x1b"):
                    raise KeyboardInterrupt
                if c == "l":
                    body.stop()
                elif c == "e":
                    print(f"\n[E] toc do {body.faster(body_link.SPEED_STEP)}")
                elif c == "r":
                    print(f"\n[R] toc do {body.faster(-body_link.SPEED_STEP)}")
                elif c == "o":
                    body.safety = not body.safety
                    print(f"\n[O] tu phanh truoc vat can: {'BAT' if body.safety else 'TAT'}")
                elif c in (",", "."):
                    body.nudge(0.02 if c == "," else -0.02)
                    print(f"\n[{c}] chinh lech -> {body.trim_text()}")

            now = time.time()
            if now - last_print > 0.25:  # 1 dong trang thai, ghi de len chinh no
                last_print = now
                line = body.status_text() + (f" | reset {body.resets} lan" if body.resets else "")
                print("\r" + line[:118].ljust(118), end="", flush=True)
            time.sleep(0.02)  # ~50 lan/giay: tha phim la phanh gan nhu ngay
    except KeyboardInterrupt:
        pass
    finally:
        shared.stop = True
        body.close()
        print("\nDa dung xe. Tam biet!")


if __name__ == "__main__":
    main()
