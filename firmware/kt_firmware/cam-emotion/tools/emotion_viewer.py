"""Camera ESP32 -> AI cam xuc cua Thai -> mat robot tren man TFT.

3 luong chay song song (giong cach Thai tach trong server/vision/runtime/camera.py):
  - reader: doc anh JPEG tu day USB, giu lai DUY NHAT anh moi nhat
  - ai:     chay VisionEngine cua Thai tren anh moi nhat (~10 lan/giay)
  - main:   ve cua so (anh + khung mat + % cam xuc), gui lenh "face ..." xuong board
Tach ra de AI cham (~80ms/lan) khong lam video tren man hinh bi giat.
"""
import logging
import os
import struct
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # thu muc cam-emotion


def find_team_repo():
    """Tim thu muc chua server/vision cua Thai. cam-emotion co the nam o 2 noi:
    MOON/cam-emotion (repo rieng, repo nhom nam ke ben) hoac
    Panda-Robotics-Client-/firmware/kt_firmware/cam-emotion (ben trong repo nhom)."""
    for parent in HERE.parents:
        for candidate in (parent, parent / "Panda-Robotics-Client-"):
            if (candidate / "server" / "vision").is_dir():
                return candidate
    sys.exit("Khong tim thay repo Panda-Robotics-Client- (thu muc server/vision)")


TEAM_REPO = find_team_repo()

# Phai dat TRUOC khi import code cua Thai: config/settings.py doc bien moi truong luc import.
os.environ.setdefault("MOON_VISION_MODEL_DIR", str(HERE / "models"))
os.environ.setdefault("MOON_VISION_DATA_DIR", str(HERE / "models" / "private"))
sys.path.insert(0, str(TEAM_REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import serial  # noqa: E402
from serial.tools import list_ports  # noqa: E402

from config import settings  # noqa: E402

# Chi giu phan KHUON MAT. Tu the nguoi / ban tay / do vat can torch + YOLO (vai GB) va
# khong lien quan cam xuc -> tat bang chinh cac cong tac Thai de san trong settings.py.
settings.VISION_POSE_ENABLED = False
settings.VISION_HANDS_ENABLED = False
settings.VISION_OBJECTS_ENABLED = False

from server.vision.pipeline.engine import EMOTIONS, VisionEngine  # noqa: E402

# Engine cua Thai canh bao thieu mo hinh nhan chu nhan (SFace) — phan do khong dung o day.
logging.getLogger("moon.vision").setLevel(logging.ERROR)

BAUD = 4_000_000
MAGIC = b"PNDA"
WINDOW = "PANDA - AI cam xuc (Q de thoat)"
PANEL_W = 330

# Nhan cua Thai (8 nhan FER+) -> 1 trong 15 mat robot (bo ten chung trong ai.md) + chu tren TFT.
# Robot khong co mat "ghe tom/so hai/khinh", nen muon mat gan nghia nhat.
ROBOT_FACE = {
    "neutral": ("neutral", "BINH THUONG"),
    "happy": ("happy", "VUI"),
    "surprised": ("surprised", "NGAC NHIEN"),
    "sad": ("sad", "BUON"),
    "angry": ("angry", "GIAN"),
    "disgust": ("dizzy", "GHE"),
    "fear": ("questioning", "SO"),
    "contempt": ("cool", "KHINH"),
}
NAME_VI = {
    "neutral": "Binh thuong", "happy": "Vui", "surprised": "Ngac nhien", "sad": "Buon",
    "angry": "Gian", "disgust": "Ghe tom", "fear": "So hai", "contempt": "Khinh",
}


def robot_command(result):
    if not result.get("face_detected"):
        return "sleepy", "KHONG THAY AI"
    emotion = result.get("emotion", "unknown")
    if emotion in ROBOT_FACE:
        return ROBOT_FACE[emotion]
    return "thinking", "CHUA RO"  # co mat nhung AI cua Thai chua du chac -> "unknown"


def pick_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for p in list_ports.comports():
        if p.vid in (0x1A86, 0x303A):
            return p.device
    ports = list(list_ports.comports())
    return ports[0].device if len(ports) == 1 else input("Go ten cong (vd COM3): ").strip()


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame, self.frame_id = None, 0
        self.result, self.result_id = None, -1
        self.cam_fps = 0.0
        self.stop = False


def reader(ser, shared):
    buf = bytearray()
    frames, t0 = 0, time.time()
    while not shared.stop:
        buf += ser.read(max(1, ser.in_waiting))
        while True:
            i = buf.find(MAGIC)
            if i < 0:
                del buf[:-3]
                break
            if i > 0:
                for line in bytes(buf[:i]).decode("ascii", "ignore").splitlines():
                    if line.startswith("[cam]"):
                        print(line)
                del buf[:i]
            if len(buf) < 8:
                break
            (n,) = struct.unpack("<I", buf[4:8])
            if n == 0 or n > 400_000:
                del buf[:4]
                continue
            if len(buf) < 8 + n:
                break
            jpg = bytes(buf[8 : 8 + n])
            del buf[: 8 + n]
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            frames += 1
            now = time.time()
            with shared.lock:
                shared.frame = img
                shared.frame_id += 1
                if now - t0 >= 1:
                    shared.cam_fps = frames / (now - t0)
                    frames, t0 = 0, now


def ai_worker(shared):
    engine = VisionEngine()
    ok = [m for m in ("face", "emotion", "face_details") if m in engine.models]
    print("Mo hinh AI da nap:", ", ".join(ok))
    missing = {k: v for k, v in engine.errors.items() if k != "identity"}
    if missing:
        print("THIEU mo hinh:", missing)
    last_id = -1
    while not shared.stop:
        with shared.lock:
            frame, fid = shared.frame, shared.frame_id
        if frame is None or fid == last_id:
            time.sleep(0.005)
            continue
        last_id = fid
        began = time.monotonic()
        result = engine.process(frame)
        with shared.lock:
            shared.result, shared.result_id = result, fid
        # Giu nhip toi da VISION_AI_FPS (10/giay) nhu cau hinh cua Thai
        time.sleep(max(0.0, 1 / settings.VISION_AI_FPS - (time.monotonic() - began)))
    engine.close()


def bar(panel, y, label, value, color):
    cv2.putText(panel, label, (10, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
    x0, w = 130, PANEL_W - 190
    cv2.rectangle(panel, (x0, y), (x0 + w, y + 14), (60, 60, 60), -1)
    cv2.rectangle(panel, (x0, y), (x0 + int(w * max(0.0, min(1.0, value))), y + 14), color, -1)
    cv2.putText(panel, f"{value * 100:4.0f}%", (x0 + w + 6, y + 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)


def diagnostics(view, result, enhanced):
    """Dai chu o day video: cac co ma luat "gian" cua Thai can + goc camera nhin mat."""
    lines = [f"Anh: {'LAM NET (cho nguoi xem)' if enhanced else 'TU NHIEN (cho AI)'}  - phim E de doi"]
    cues = (result or {}).get("expression_cues") or {}
    if cues:
        brow = cues.get("brow_down", 0.0)
        squeeze = max(cues.get("eye_squint", 0.0), cues.get("mouth_press", 0.0))
        lines.append(f"GIAN can: cau may {brow:.2f}/0.42 {'OK' if brow >= 0.42 else 'THIEU'}"
                     f"  |  nheo mat/mim moi {squeeze:.2f}/0.12 {'OK' if squeeze >= 0.12 else 'THIEU'}")
    pose = (result or {}).get("head_pose") or {}
    if pose:
        pitch = pose.get("pitch", 0.0)
        hint = "  -> camera lech doc, nen dat ngang tam mat" if abs(pitch) > 15 else ""
        lines.append(f"Goc nhin doc (pitch): {pitch:+.0f} do{hint}")
    y = view.shape[0] - 10 - 22 * (len(lines) - 1)
    cv2.rectangle(view, (0, y - 20), (view.shape[1], view.shape[0]), (0, 0, 0), -1)
    for text in lines:
        cv2.putText(view, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
        y += 22


def draw(frame, result, cam_fps, sent, enhanced=False):
    view = frame.copy()
    diagnostics(view, result, enhanced)
    panel = np.full((view.shape[0], PANEL_W, 3), 30, np.uint8)
    if result and result.get("face_box"):
        x, y, w, h = map(int, result["face_box"])
        cv2.rectangle(view, (x, y), (x + w, y + h), (0, 255, 0), 2)
        label = NAME_VI.get(result["emotion"], "Chua ro")
        cv2.putText(view, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
        cv2.putText(view, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    y = 24
    cv2.putText(panel, f"Camera {cam_fps:4.1f} khung/s", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 200, 150), 1)
    if result:
        y += 20
        cv2.putText(panel, f"AI {result.get('inference_ms', 0):.0f} ms/lan", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 200, 150), 1)
    y += 26
    cv2.putText(panel, f"-> Man hinh: {sent[0]}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1)
    if not result or not result.get("face_detected"):
        cv2.putText(panel, "Khong thay mat nao", (10, y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return np.hstack([view, panel])

    y += 30
    source = result.get("emotion_source", "")
    cv2.putText(panel, f"KET LUAN: {NAME_VI.get(result['emotion'], 'Chua ro')}", (10, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    y += 18
    cv2.putText(panel, f"(nguon: {source})", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)

    # 1) Diem hop nhat = 75% FER+ + 25% dau hieu co mat (combined_emotion_scores cua Thai)
    y += 22
    cv2.putText(panel, "Diem hop nhat (FER+ & co mat):", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    scores = result.get("emotion_scores") or {}
    for name in EMOTIONS:
        y += 18
        bar(panel, y, NAME_VI[name], scores.get(name, 0.0), (80, 200, 80))

    # 2) Muc kich hoat co mat tu MediaPipe (expression_intensities cua Thai)
    y += 30
    cv2.putText(panel, "Dau hieu co mat (MediaPipe):", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    inten = result.get("expression_intensities") or {}
    for name in ("happy", "surprised", "sad", "angry", "disgust", "fear", "contempt"):
        y += 18
        bar(panel, y, NAME_VI[name], inten.get(name, 0.0), (200, 150, 60))
    return np.hstack([view, panel])


def main():
    port = pick_port()
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, BAUD, 0.05
    ser.dtr = ser.rts = False  # khong lam board tu reset khi mo cong
    try:
        ser.open()
    except serial.SerialException as e:
        print("KHONG MO DUOC CONG", port, "-", e)
        print("-> Dong Serial Monitor / xem-camera.bat dang giu cong roi chay lai.")
        return
    print(f"Dang doc camera o {port}. Dang nap AI cua Thai (lan dau mat vai giay)...")

    shared = Shared()
    threads = [threading.Thread(target=reader, args=(ser, shared), daemon=True),
               threading.Thread(target=ai_worker, args=(shared,), daemon=True)]
    for t in threads:
        t.start()

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    enhanced = False
    ser.write(b"cam natural\n")
    sent, last_send = ("", ""), 0.0
    last_shown = -1
    while True:
        with shared.lock:
            frame, fid, result, fps = shared.frame, shared.frame_id, shared.result, shared.cam_fps
        if frame is not None and fid != last_shown:
            last_shown = fid
            cmd = robot_command(result) if result else ("sleepy", "DANG NAP AI")
            now = time.time()
            # Gui khi cam xuc doi, va nhac lai moi 2s de board bat kip neu vua bi reset
            if cmd != sent or now - last_send > 2:
                ser.write(f"face {cmd[0]} {cmd[1]}\n".encode("ascii"))
                if cmd != sent:
                    print(f"-> man hinh: {cmd[0]:12s} ({cmd[1]})")
                sent, last_send = cmd, now
            cv2.imshow(WINDOW, draw(frame, result, fps, sent, enhanced))
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key == ord("e"):
            enhanced = not enhanced
            ser.write(b"cam enhanced\n" if enhanced else b"cam natural\n")
            print("Kieu anh:", "lam net" if enhanced else "tu nhien")
    shared.stop = True
    time.sleep(0.2)
    ser.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
