"""Lai thu phan THAN robot bang ban phim laptop.

  Giu L      -> banh TRAI quay        Giu R  -> banh PHAI quay     (giu ca 2 -> xe di thang)
  + / -      -> nhanh / cham hon      Q / Esc -> thoat

Vat can truoc HC-SR04 gan hon 12cm -> board cam di thang (giu L+R cung khong quay),
nhung giu 1 phim L hoac R van quay duoc 1 banh -> xe xoay mat khoi vat can.
Luat an toan nam tren board, chuong trinh nay chi doc phim va hien trang thai.

Chay: chay-test.bat  (hoac: python tools/lai_xe.py [COMx])
"""
import ctypes
import sys
import time

import serial
from serial.tools import list_ports

BAUD = 115200
user32 = ctypes.windll.user32


def held(vk):
    """Phim dang duoc GIU khong (Windows GetAsyncKeyState, bit cao = dang nhan)."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def find_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    ports = list(list_ports.comports())
    # DevKit C dung chip USB-Serial CP2102 (VID 10C4) hoac CH340 (VID 1A86).
    # Bo qua board dau ESP32-S3 (VID 303A) neu dang cam cung luc.
    for p in ports:
        if p.vid in (0x10C4, 0x1A86):
            return p.device
    others = [p.device for p in ports if p.vid != 0x303A]
    if len(others) == 1:
        return others[0]
    print("Khong tim thay board than. Cong dang co:", [p.device for p in ports])
    print("Chay lai kem ten cong, vd: python tools\\lai_xe.py COM5")
    sys.exit(1)


def main():
    port = find_port()
    try:
        ser = serial.Serial(port, BAUD, timeout=0)
    except serial.SerialException as e:
        print(f"KHONG MO DUOC {port}: {e}\n-> Dong Serial Monitor / chuong trinh khac dang dung cong.")
        sys.exit(1)
    print(f"Da noi board than o {port}.")
    print("KE BANH LEN KHOI BAN truoc khi thu!  Giu L / R de quay, +/- doi toc do, Q thoat.\n")

    speed = 150  # ~60%: du quay ro, khong keo qua nhieu dong tu cong USB
    status = "cho board..."
    buf = b""
    prev = {"+": False, "-": False}
    try:
        while True:
            if held(ord("Q")) or held(0x1B):
                break
            for key, vk, step in (("+", 0xBB, 25), ("+", 0x6B, 25), ("-", 0xBD, -25), ("-", 0x6D, -25)):
                now = held(vk)
                if now and not prev.get((key, vk)):
                    speed = max(50, min(255, speed + step))
                prev[(key, vk)] = now

            left = speed if held(ord("L")) else 0
            right = speed if held(ord("R")) else 0
            ser.write(f"m {left} {right}\n".encode())

            buf += ser.read(512)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                parts = raw.decode(errors="replace").split()
                if len(parts) == 5 and parts[0] == "S":
                    cm, run_l, run_r, blocked = float(parts[1]), parts[2], parts[3], parts[4] == "1"
                    dist = "khong co vat" if cm < 0 else f"{cm:5.1f} cm"
                    want = f"giu: {'L' if left else '-'}{'R' if right else '-'}"
                    state = "VAT CAN -> DUNG" if blocked else "chay duoc"
                    status = (f"{want} | toc do {speed:3d} | banh trai {int(run_l):3d} phai {int(run_r):3d}"
                              f" | HC-SR04: {dist:>12} | {state}")
                elif raw.startswith(b"#"):
                    print(raw.decode(errors="replace"))
            print("\r" + status.ljust(110), end="", flush=True)
            time.sleep(0.05)
    finally:
        ser.write(b"m 0 0\n")
        ser.close()
        print("\nDa dung banh, thoat.")


if __name__ == "__main__":
    main()
