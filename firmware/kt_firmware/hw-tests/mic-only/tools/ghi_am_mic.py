"""Ghi am tu mic INMP441 cua robot qua day USB, phat lai bang loa laptop, va ket luan mic co hu khong.

Buoc 1: im lang 3 giay  -> do do on nen cua mic
Buoc 2: noi 5 giay      -> do do to, do meo
Buoc 3: phat lai ban ghi bang loa laptop -> ban tu nghe co re khong
File .wav luu o thu muc ket-qua/ de nghe lai / gui cho nhom.
"""
import array
import math
import sys
import time
import wave
from pathlib import Path

import serial
from serial.tools import list_ports

BAUD = 921600
RATE = 16000
OUT_DIR = Path(__file__).resolve().parent.parent / "ket-qua"


def find_port():
    ports = list(list_ports.comports())
    for p in ports:
        if p.vid == 0x1A86:  # chip USB CH343 tren board ESP32-S3
            return p.device
    if len(ports) == 1:
        return ports[0].device
    sys.exit("Khong tim thay board. Cam day USB vao cong COM cua board roi chay lai.\n"
             f"Cac cong dang co: {[p.device for p in ports]}")


def record(ser, seconds):
    ser.reset_input_buffer()
    ser.write(f"rec {seconds}\n".encode())
    deadline = time.time() + 5
    while True:
        line = ser.readline().decode(errors="ignore").strip()
        if line.startswith("PCM "):
            nbytes = int(line.split()[1])
            break
        if time.time() > deadline:
            sys.exit("Board khong tra loi lenh ghi am. Da nap firmware mic-only chua?")
    data = bytearray()
    ser.timeout = seconds + 5
    while len(data) < nbytes:
        chunk = ser.read(nbytes - len(data))
        if not chunk:
            sys.exit("Mat ket noi giua chung khi dang ghi am.")
        data += chunk
    ser.timeout = 1
    return array.array("h", bytes(data))


def stats(samples):
    n = len(samples)
    dc = sum(samples) / n
    rms = math.sqrt(sum((s - dc) ** 2 for s in samples) / n)
    peak = max(abs(s) for s in samples)
    clip = sum(1 for s in samples if abs(s) >= 32700) / n * 100
    stuck = sum(1 for a, b in zip(samples, samples[1:]) if a == b) / max(1, n - 1) * 100
    return dict(dc=dc, rms=rms, peak=peak, clip=clip, stuck=stuck)


def save_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())


def normalized(samples, dc):
    """Ban de NGHE: bo lech DC va khuech dai len gan muc to nhat, de mic nho van nghe ro.
    Chi phong to deu ca bai -> khong them meo. Ban tho (chua chinh) van luu rieng."""
    centered = [s - dc for s in samples]
    peak = max(1.0, max(abs(s) for s in centered))
    gain = min(30000 / peak, 64.0)
    return array.array("h", (int(max(-32767, min(32767, s * gain))) for s in centered)), gain


def play(path):
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    except Exception as e:  # khong phai Windows -> tu mo file bang trinh nghe nhac
        print(f"  (Khong tu phat duoc: {e}. Mo file {path} de nghe.)")


def fmt(s):
    return f"lech DC={s['dc']:.0f}  on TB(rms)={s['rms']:.0f}  dinh={s['peak']}  meo(clip)={s['clip']:.1f}%  dung im={s['stuck']:.0f}%"


def main():
    OUT_DIR.mkdir(exist_ok=True)
    port = find_port()
    print(f"Ket noi {port} @ {BAUD} baud...")
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
    except serial.SerialException as e:
        sys.exit(f"Khong mo duoc {port}: {e}\n-> Tat Serial Monitor / cua so khac dang giu cong roi chay lai.")
    time.sleep(1.5)  # mo cong co the lam board reset -> doi board khoi dong xong

    print("\n=== BUOC 1/3: IM LANG ===")
    input("Giu phong yen tinh, KHONG noi. Bam Enter de ghi 3 giay...")
    quiet = record(ser, 3)
    q = stats(quiet)
    save_wav(OUT_DIR / "1-im-lang-tho.wav", quiet)
    print("  " + fmt(q))

    print("\n=== BUOC 2/3: NOI ===")
    input("Noi binh thuong, cach mic 20-30cm (vd dem 'mot hai ba bon nam'). Bam Enter roi noi ngay (5 giay)...")
    speech = record(ser, 5)
    v = stats(speech)
    save_wav(OUT_DIR / "2-giong-noi-tho.wav", speech)
    loud, gain = normalized(speech, v["dc"])
    listen_path = OUT_DIR / "3-giong-noi-de-nghe.wav"
    save_wav(listen_path, loud)
    print("  " + fmt(v))

    print("\n=== BUOC 3/3: NGHE LAI BANG LOA LAPTOP ===")
    print(f"  Dang phat (da khuech dai x{gain:.1f} de de nghe)...")
    play(listen_path)

    # ---- Ket luan tu so do ----
    print("\n=== KET LUAN TU SO DO ===")
    problems = []
    snr = 20 * math.log10(max(1.0, v["rms"]) / max(1.0, q["rms"]))
    if q["stuck"] > 90 and v["stuck"] > 90:
        problems.append("Mic KHONG co tin hieu (mau dung yen). Kiem tra day SD(42), SCK(40), WS(41), "
                        "VDD 3V3, GND, chan L/R noi GND. Day dung ma van vay -> mic chet.")
    elif v["peak"] < 100:
        problems.append("Noi ma tin hieu gan bang 0 -> mic 'diec' hoac lo thu am bi bit. Kiem tra lo nho tren mic.")
    if v["clip"] > 1:
        problems.append(f"{v['clip']:.1f}% mau cham tran -> meo vi qua to. Noi xa mic hon roi thu lai.")
    if snr < 10 and v["peak"] >= 100:
        problems.append(f"Giong noi chi to hon on nen {snr:.0f} dB (tot: >20 dB) -> mic rat nhieu/yeu, nghi mic loi "
                        "hoac nhieu nguon (thu cap USB khac, tranh xa day loa/motor).")
    if not problems:
        print(f"  So do BINH THUONG (giong noi to hon on nen {snr:.0f} dB, khong meo, co tin hieu).")
    for p in problems:
        print("  ! " + p)

    print("\n=== BAN TU NGHE ===")
    ans = input("Ban ghi vua phat co RE / xe / meo khong? (c = co re, k = khong, Enter = nghe lai): ").strip().lower()
    while ans == "":
        play(listen_path)
        ans = input("Co re khong? (c/k): ").strip().lower()
    print()
    if ans.startswith("c"):
        print(">> MIC CO VAN DE: tieng re co san ngay trong ban ghi, ma ban ghi khong di qua loa robot.")
        print("   Thu: cam lai day mic chac chan / day ngan hon -> ghi lai. Van re -> MUA MIC INMP441 MOI.")
    else:
        print(">> MIC TOT. Neu truoc day nghe re khi noi vao mic -> loi nam o duong LOA")
        print("   (chay bai speaker-only) hoac do mic dat sat loa gay hu/vong phan hoi.")
    print(f"\nCac file ghi am: {OUT_DIR}")
    ser.close()


if __name__ == "__main__":
    main()
