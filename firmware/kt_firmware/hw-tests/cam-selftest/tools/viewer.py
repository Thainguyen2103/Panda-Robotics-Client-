"""Xem video camera PANDA truyen qua day USB.

Doc dong du lieu Serial tu ESP32: moi khung = b"PNDA" + do dai (4 byte) + JPEG.
Phan nam ngoai cac khung la chu log "[cam] ..." -> in ra cua so den.
"""
import struct
import sys
import time

import cv2
import numpy as np
import serial
from serial.tools import list_ports

# Thu lan luot cac toc do nay cho toi khi nhan duoc anh hop le — phai co SERIAL_BAUD trong
# src/main.cpp. Tu do nen doi toc do ben board thi khong can sua file nay.
# (5_000_000 da thu: chip CH343 tren board truyen sai bit o toc do do -> khong dung.)
BAUDS = [4_000_000, 3_000_000, 2_000_000]
MAGIC = b"PNDA"
MAX_FRAME = 400_000
WINDOW = "PANDA CAM - Esc/Q de thoat"
KNOWN_VIDS = {0x1A86, 0x303A}  # WCH (CH343/CH340) va Espressif USB


def pick_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    ports = list(list_ports.comports())
    for p in ports:
        if p.vid in KNOWN_VIDS:
            return p.device
    if len(ports) == 1:
        return ports[0].device
    print("Khong tu tim thay cong ESP32. Cac cong dang co:")
    for p in ports:
        print("  ", p.device, "-", p.description)
    return input("Go ten cong (vd COM3): ").strip()


def detect_baud(ser):
    """Nghe 1.5 giay o tung toc do; toc do nao doc ra dung dau khung PNDA + anh JPEG la dung."""
    for baud in BAUDS:
        ser.baudrate = baud
        ser.reset_input_buffer()
        data = bytearray()
        t0 = time.time()
        while time.time() - t0 < 1.5:
            data += ser.read(max(1, ser.in_waiting))
            i = data.find(MAGIC)
            if i >= 0 and len(data) >= i + 10 and data[i + 8 : i + 10] == b"\xff\xd8":
                return baud
    return None


def open_port(name):
    ser = serial.Serial()
    ser.port = name
    ser.baudrate = BAUDS[0]
    ser.timeout = 0.05
    # Giu DTR/RTS o muc nghi: mo cong ma dao 2 chan nay thi mach tu-reset tren board se khoi
    # dong lai ESP32 (hoac dua no vao che do nap code) — dung thu minh khong muon.
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def print_text(chunk):
    text = chunk.decode("ascii", errors="ignore")
    for line in text.splitlines():
        if line.startswith("[cam]"):
            print(line)


def main():
    port = pick_port()
    print(f"Mo cong {port}...")
    try:
        ser = open_port(port)
    except serial.SerialException as e:
        print("KHONG MO DUOC CONG:", e)
        print("-> Dong Serial Monitor cua PlatformIO (hoac chuong trinh khac dang giu cong) roi chay lai.")
        return
    baud = detect_baud(ser)
    if baud is None:
        print("Khong nhan duoc anh o toc do nao. Board da nap cam-selftest chua? Thu bam nut RST tren board.")
        ser.close()
        return
    print(f"Nhan anh o toc do {baud} baud.")

    print("Phim tat trong cua so video:")
    print("  1/2/3/4 = 320x240 / 640x480 / 800x600 / 1280x720")
    print("  + / -   = net hon / nhe hon (nen JPEG)")
    print("  m / f   = lat ngang / lat doc     Esc hoac Q = thoat")

    print("  s       = bat/tat lam net tren laptop")

    # Cua so dung kich thuoc anh that: phong to anh 640x480 len 960x720 nhu ban truoc la
    # noi suy them diem anh -> mem, nhoe di. Can to hon thi bam 3/4 de camera chup to that.
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    sharpen = True
    buf = bytearray()
    frames, t0, fps, last_kb = 0, time.time(), 0.0, 0
    while True:
        buf += ser.read(max(1, ser.in_waiting))

        while True:
            i = buf.find(MAGIC)
            if i < 0:
                # giu lai 3 byte cuoi phong truong hop "PNDA" bi cat doi giua 2 lan doc
                if len(buf) > 3:
                    print_text(bytes(buf[:-3]))
                    del buf[:-3]
                break
            if i > 0:
                print_text(bytes(buf[:i]))
                del buf[:i]
            if len(buf) < 8:
                break
            (length,) = struct.unpack("<I", buf[4:8])
            if length == 0 or length > MAX_FRAME:
                del buf[:4]  # dau goi gia (trung hop trong du lieu anh) -> bo qua, do tiep
                continue
            if len(buf) < 8 + length:
                break
            jpg = bytes(buf[8 : 8 + length])
            del buf[: 8 + length]

            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue  # khung hong do nhieu duong truyen -> bo, khung sau se toi ngay
            frames += 1
            last_kb = length // 1024
            now = time.time()
            if now - t0 >= 1:
                fps = frames / (now - t0)
                frames, t0 = 0, now
            if sharpen:
                # Unsharp mask (xu ly anh so): lay anh lam mo tru nguoc vao anh goc -> phan con
                # lai chinh la cac canh/chi tiet, cong them 60% phan do de canh sac hon.
                # Lam tren laptop nen khong ton them bang thong USB.
                blur = cv2.GaussianBlur(img, (0, 0), 1.2)
                img = cv2.addWeighted(img, 1.6, blur, -0.6, 0)
            h, w = img.shape[:2]
            label = f"{w}x{h}  {fps:.1f} khung/giay  {last_kb}KB" + ("  [net]" if sharpen else "")
            cv2.putText(img, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
            cv2.putText(img, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
            cv2.imshow(WINDOW, img)

        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        if key == ord("s"):
            sharpen = not sharpen
        if key != 255 and chr(key) in "1234+-mf":
            ser.write(bytes([key]))
        if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break

    ser.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
