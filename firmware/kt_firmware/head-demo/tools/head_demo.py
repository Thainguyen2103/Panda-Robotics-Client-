"""head-demo: camera + man + loa cua dau robot, chay AI cua Thai va Ngoc Anh tren laptop.

Man hinh robot: giong cam-emotion (AI cam xuc cua Thai doi mat robot theo nguoi dung).
Loa robot:      bam SPACE -> noi vao MIC LAPTOP -> STT (Gemini Transcribe, giong dashboard
                cua nhom) -> LLM gia su (Ngoc Anh) -> TTS (Fish Audio / giong Gemini) -> am thanh gui qua day
                USB -> loa robot.
                Trong luc do mat robot chuyen: dang nghe -> dang nghi -> dang noi.

Khong sua 1 dong code nao cua nhom: chi import va goi ham co san.
"""
import array
import logging
import os
import queue
import re
import struct
import sys
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    import msvcrt  # doc phim go o cua so den (chi co tren Windows)
except ImportError:
    msvcrt = None
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # thu muc head-demo


def find_team_repo():
    """Tim repo nhom (thu muc co server/vision): nam ke ben (MOON/) hoac bao ngoai."""
    for parent in HERE.parents:
        for candidate in (parent, parent / "Panda-Robotics-Client-"):
            if (candidate / "server" / "vision").is_dir():
                return candidate
    sys.exit("Khong tim thay repo Panda-Robotics-Client- (thu muc server/vision)")


TEAM_REPO = find_team_repo()

# --- Phai dat TRUOC khi import code cua nhom: config/settings.py doc luc import ---
os.environ.setdefault("MOON_VISION_MODEL_DIR", str(HERE / "models"))
os.environ.setdefault("MOON_VISION_DATA_DIR", str(HERE / "models" / "private"))
# Key doc tu file canh ben (khong dua len git) hoac bien moi truong.
#   gemini-key.txt: BAT BUOC cho phan nghe (Gemini Transcribe), dung luon cho LLM neu can
#   groq-key.txt:   tuy chon, LLM cua Groq tra loi nhanh hon
def read_key(path):
    """Nhan ca key tran ("AQ.xxx" / "AIza...") lan dong chep tu secrets.py/.env
    ("GEMINI_API_KEY = 'xxx'") -> chi lay phan gia tri."""
    text = path.read_text(encoding="utf-8-sig").strip()
    for sep in ("=", ":"):
        if sep in text and text.split(sep, 1)[0].strip().replace("_", "").isalpha():
            text = text.split(sep, 1)[1]
            break
    return text.strip().strip(",").strip().strip("'\"")


for _name, _file in (("GEMINI_API_KEY", "gemini-key.txt"), ("GROQ_API_KEY", "groq-key.txt")):
    if not os.environ.get(_name) and (HERE / _file).is_file():
        os.environ[_name] = read_key(HERE / _file)

# fish-key.txt (tuy chon, giong Fish Audio s2.1-pro-free): moi dong 1 gia tri
#   dong 1: API key (sk-fish-...)
#   dong "ID_Model = ..." (hoac Voice/Reference ID): ID giong trong tai khoan Fish
if (HERE / "fish-key.txt").is_file():
    for _line in (HERE / "fish-key.txt").read_text(encoding="utf-8-sig").splitlines():
        _label, _sep, _value = _line.partition("=")
        _value = (_value if _sep else _label).strip().strip(",").strip().strip("'\"")
        if not _value:
            continue
        if _sep and any(w in _label.upper() for w in ("ID", "MODEL", "VOICE", "REFERENCE")):
            os.environ.setdefault("FISH_VOICE_ID", _value)
        else:
            os.environ.setdefault("FISH_AUDIO_API_KEY", _value)

# Mot so mang (vd WiFi truong/nha) co IPv6 bi hong: Python thu IPv6 truoc, cho het gio
# (moi dia chi ~15-20 giay) roi moi sang IPv4 -> Gemini bao "timed out during opening
# handshake". Trinh duyet/curl tu ne duoc nen khong thay loi. Sap xep IPv4 len truoc.
import socket  # noqa: E402

_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_getaddrinfo(*a, **k), key=lambda r: r[0] != socket.AF_INET)
sys.path.insert(0, str(TEAM_REPO))
# tts.py cua nhom import "llm.language" (duong dan tinh tu thu muc server/, giong khi chay
# brain.py) -> them server/ vao duong tim module de chon dung giong Viet/Anh/Nhat.
sys.path.insert(1, str(TEAM_REPO / "server"))
sys.path.append(str(Path(__file__).resolve().parent))  # gemini_stt.py nam canh file nay

import select  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import serial  # noqa: E402
from serial.tools import list_ports  # noqa: E402

import mic_clean  # noqa: E402  (lam sach tieng mic robot truoc khi gui Gemini)
from config import settings  # noqa: E402

settings.VISION_POSE_ENABLED = False
settings.VISION_HANDS_ENABLED = False
settings.VISION_OBJECTS_ENABLED = False

from server.vision.pipeline.engine import EMOTIONS, VisionEngine  # noqa: E402

logging.getLogger("moon.vision").setLevel(logging.ERROR)

BAUD = 4_000_000
# Camera lap nam ngang trong dau robot -> anh bi xoay 90 do (dinh dau nguoi nam ben TRAI).
# Cam bien chi tu lat duoc 180 do (vflip/hmirror trong firmware), xoay 90 phai lam o laptop.
# Anh van nghieng sai chieu thi doi thanh cv2.ROTATE_90_COUNTERCLOCKWISE; lap thang lai
# camera thi dat None.
CAM_ROTATE = cv2.ROTATE_90_CLOCKWISE
REMOTE_URL = ""  # dia chi trang tay cam dien thoai (main() dien vao), hien o goc cua so
MAGIC = b"PNDA"      # 1 khung anh JPEG
MIC_MAGIC = b"PNDM"  # 1 khung tieng mic robot (PCM 16-bit mono, xem main.cpp micTask)
WINDOW = "PANDA head-demo (SPACE: noi | T: thu loa | +/-: am luong | Q: thoat)"
PANEL_W = 330
VOICE_H = 120
SAMPLE_RATE = 16000

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


def ascii_vi(text):
    """Bo dau tieng Viet: man TFT va cua so OpenCV chi ve duoc chu ASCII."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn" and ord(c) < 128)


# Lenh di chuyen bang giong noi. Chi xet cau NGAN (<= 4 tu) de cau hoi binh thuong co chu
# "chay"/"dung" (vd "con meo chay tieng Anh la gi") khong bi hieu nham thanh lenh.
# So khop GIU DAU: bo dau thi "dùng" (dung) bi nham thanh "dừng".
STOP_WORDS = {"stop", "dừng", "thôi"}
RUN_WORDS = {"run", "chạy", "go", "tiến", "thẳng"}  # + "thẳng": bắt câu "đi thẳng"
LEFT_WORDS = {"left", "trái"}
RIGHT_WORDS = {"right", "phải"}
BACK_WORDS = {"back", "lùi"}


def body_command(text):
    words = re.findall(r"\w+", unicodedata.normalize("NFC", text or "").lower())
    if not words or len(words) > 4:
        return None
    wset = set(words)
    if STOP_WORDS & wset:  # xet DUNG truoc: an toan hon
        return "stop"
    if BACK_WORDS & wset:  # truoc "run": "chạy lùi" co ca "chạy" lan "lùi"
        return "back"
    if LEFT_WORDS & wset:  # xet trai/phai TRUOC run: "rẽ trái" co ca tu "rẽ" lan "trái"
        return "left"
    if RIGHT_WORDS & wset:
        return "right"
    if RUN_WORDS & wset:
        return "run"
    return None


def robot_command(result):
    if not result.get("face_detected"):
        return "sleepy", "KHONG THAY AI"
    emotion = result.get("emotion", "unknown")
    if emotion in ROBOT_FACE:
        return ROBOT_FACE[emotion]
    return "thinking", "CHUA RO"


def pick_port():
    """Cong USB cua board DAU, hoac None neu khong cam day -> dung WiFi."""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        return sys.argv[1]
    if "--wifi" in sys.argv:
        return None
    # Board dau: ESP32-S3 cong USB tich hop (VID 303A) hoac cong COM qua chip CH343
    # (VID 1A86, PID 55D3). Board than DevKit C dung CP2102 (10C4) / CH340 (1A86 nhung PID
    # 7523) -> loc ca PID de khong chon nham board than khi chi cam day board than.
    for p in list_ports.comports():
        if p.vid == 0x303A or (p.vid == 0x1A86 and p.pid == 0x55D3):
            return p.device
    return None


class Link:
    """Day USB toi board. Nhieu luong cung GHI (lenh mat, am thanh) -> can khoa de 1 goi
    'pcm <n>' + n byte khong bi 1 dong 'face ...' chen vao giua."""

    def __init__(self, ser):
        self.ser = ser
        self.lock = threading.Lock()

    @property
    def name(self):
        return self.ser.port

    def read(self):
        return self.ser.read(max(1, self.ser.in_waiting))

    def close(self):
        self.ser.close()

    def send(self, data: bytes):
        with self.lock:
            try:
                self.ser.write(data)
            except (serial.SerialException, OSError):
                pass  # cong dang mat (board reset / tuot day): bo goi nay, reader() se tu noi lai

    def reopen(self):
        """Dong roi mo lai cong. Giu khoa de luong khac khong ghi vao giua luc dang mo."""
        with self.lock:
            try:
                self.ser.close()
            except (serial.SerialException, OSError):
                pass
            self.ser.open()


HEAD_BEACON_PORT = 4212  # board dau phat "PANDA-HEAD <cong>" o day khi chua co laptop noi
HEAD_TCP_PORT = 4300     # board dau nghe ket noi TCP o day


class WifiLink:
    """Noi toi board DAU qua WiFi (TCP) — cung giao thuc voi day USB: anh/mic di len,
    lenh face/cam/pcm/mic di xuong. Cung ham send/read/reopen/close/name voi Link
    nen reader() va Voice khong can biet dang dung duong nao.
    Khong can go IP: board phat "PANDA-HEAD" cho ca mang moi giay, nghe thay la biet dia chi
    (giong board than). Hoac chi dinh: head_demo.py --wifi 192.168.137.50"""

    def __init__(self, ip=None):
        self.fixed_ip = ip
        self.ip = ip
        self.sock = None
        self.lock = threading.Lock()
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp.bind(("", HEAD_BEACON_PORT))
        self.udp.settimeout(1.5)

    @property
    def name(self):
        return f"WiFi {self.ip or '(dang tim board dau)'}"

    def _discover(self):
        try:
            while True:
                data, (ip, _) = self.udp.recvfrom(64)
                if data.startswith(b"PANDA-HEAD"):
                    break
        except socket.timeout:
            raise ConnectionError("chua thay board dau phat tin hieu WiFi (board bat chua? cung hotspot chua?)")
        if ip != self.ip:
            print(f"[WIFI] tim thay board dau: {ip}")
        self.ip = ip

    def reopen(self):
        with self.lock:
            self._drop()
        if not self.fixed_ip:
            self._discover()
        s = socket.create_connection((self.ip, HEAD_TCP_PORT), timeout=3)
        # Gui ngay tung goi (lenh mat / am thanh khong bi gom lai cho); bo dem nhan lon de
        # luong doc lo cham vai chuc ms (GIL, AI) cung khong mat byte anh.
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        s.settimeout(3)  # gui bi ket qua 3 giay = coi nhu mat ket noi
        with self.lock:
            self.sock = s

    def read(self):
        s = self.sock
        if s is None:
            raise ConnectionError("chua ket noi")
        # Cho toi da 50ms co du lieu (giong timeout cua cong Serial), khong dung recv cho mai.
        if not select.select([s], [], [], 0.05)[0]:
            return b""
        data = s.recv(65536)
        if not data:
            raise ConnectionError("board dau dong ket noi (mat WiFi / board reset)")
        return data

    def send(self, data: bytes):
        with self.lock:
            if self.sock is None:
                return
            try:
                self.sock.sendall(data)
            except OSError:
                # Gui hong giua chung -> goi "pcm" bi cat doi, khong noi tiep duoc nua: dong
                # ket noi de reader() thay loi va noi lai tu dau.
                self._drop()

    def _drop(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def close(self):
        with self.lock:
            self._drop()
        self.udp.close()


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame, self.frame_id = None, 0
        self.result = None
        self.cam_fps = 0.0
        self.port_ok = True  # False = cong USB toi board dau dang mat, reader() dang noi lai
        self.stop = False
        # Tieng mic robot: Voice._listen_robot_mic() rut tung khung ra khi dang ghi am.
        # Gioi han kich thuoc de neu khong ai dang nghe (board lo gui du "mic off") thi
        # khong tran bo nho, chi mat vai khung tieng thua chu khong treo chuong trinh.
        self.mic_queue = queue.Queue(maxsize=400)


def reconnect(link, shared, err):
    """Mat duong toi board dau. Qua day USB: cong COM bien mat (board reset — vd vua nap code
    xong — hay tuot day la Windows go cong ra roi gan lai sau ~1-2 giay). Qua WiFi: board ra
    khoi vung song / mat dien / reset. Truoc day luong reader() chet luon o day
    ("GetOverlappedResult failed") -> khong bao gio co anh nua. Gio: cho noi lai roi doc tiep."""
    print(f"[LINK] chua/mat ket noi board dau ({err}). Dang thu noi {link.name}...")
    with shared.lock:
        shared.port_ok, shared.frame, shared.cam_fps = False, None, 0.0
    while not shared.stop:
        try:
            link.reopen()
        except (serial.SerialException, OSError):
            time.sleep(1)
            continue
        print(f"[LINK] da noi {link.name}.")
        link.send(b"cam natural\n")  # board vua reset -> quen che do camera, gui lai
        with shared.lock:
            shared.port_ok = True
        return


def reader(link, shared):
    buf = bytearray()
    frames, t0 = 0, time.time()
    while not shared.stop:
        try:
            buf += link.read()
        except (serial.SerialException, OSError) as e:
            reconnect(link, shared, e)
            buf.clear()  # du lieu cu bi cat ngang giua khung, bo di
            continue
        while True:
            i_cam, i_mic = buf.find(MAGIC), buf.find(MIC_MAGIC)
            candidates = [x for x in (i_cam, i_mic) if x >= 0]
            if not candidates:
                del buf[:-3]
                break
            i = min(candidates)
            is_mic = i == i_mic
            if i > 0:
                for line in bytes(buf[:i]).decode("ascii", "ignore").splitlines():
                    if line.startswith("[cam]"):
                        print(line)
                del buf[:i]
            if len(buf) < 8:
                break
            (n,) = struct.unpack("<I", buf[4:8])
            if n == 0 or n > (64_000 if is_mic else 400_000):
                del buf[:4]
                continue
            if len(buf) < 8 + n:
                break
            payload = bytes(buf[8 : 8 + n])
            del buf[: 8 + n]
            if is_mic:
                try:
                    shared.mic_queue.put_nowait(payload)
                except queue.Full:
                    pass
                continue
            img = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            if CAM_ROTATE is not None:
                img = cv2.rotate(img, CAM_ROTATE)  # xoay TRUOC khi dua AI: AI chi bat mat dung chieu
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
    print("Mo hinh cam xuc da nap:", ", ".join(m for m in ("face", "emotion", "face_details") if m in engine.models))
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
            shared.result = result
        time.sleep(max(0.0, 1 / settings.VISION_AI_FPS - (time.monotonic() - began)))
    engine.close()


# ============================== GIONG NOI ==============================

def ollama_running():
    host = getattr(settings, "OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    try:
        urllib.request.urlopen(host + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


class Voice:
    """Tro chuyen: nghe (mic robot, hoac mic laptop neu --laptop-mic) -> hieu (Gemini STT)
    -> tra loi (LLM) -> noi (loa robot)."""

    FACE = {"listening": ("hearing", "DANG NGHE..."),
            "thinking": ("thinking", "DANG NGHI..."),
            "speaking": ("speaking", "MOON DANG NOI")}

    # Ghi am tu mic ROBOT (khong phai mic laptop nua, tu khi gan INMP441 that len head-demo).
    # Nguong "the nao la co tieng noi" nam trong mic_clean.py (MIN_VOICE_LEVEL...).
    WAIT_SEC = 4.0     # bam SPACE xong co toi da 4 giay de bat dau noi (mic laptop cua nhom: 6)
    SILENCE_SEC = 1.5  # noi xong, im 1,5 giay la chot cau ("stop" phai nhanh)
    MAX_SEC = 10.0     # dai nhat 1 lan ghi, phong khi cho on qua AI tuong la noi mai

    def __init__(self, link, mic_queue):
        self.link = link
        self.mic_queue = mic_queue
        self.state = "loading"
        self.info = "Dang nap AI giong noi..."
        self.caption = ""
        self.question = self.answer = ""
        # 0.5: giong TTS da to sat muc toi da; phat 100% qua MAX98357 khi nguon USB con
        # nuoi ca camera + man hinh thi ap bi tut -> tieng re. Can to hon thi bam '+'.
        self.volume = 0.5
        # Mac dinh dung mic ROBOT (INMP441 qua day USB). "--laptop-mic" de quay lai mic laptop
        # (vd robot chua gan mic, hoac dang nghi ngo mic robot co van de) ma khong phai sua code.
        self.use_robot_mic = "--laptop-mic" not in sys.argv
        # Giong robot: Fish Audio neu co fish-key.txt, khong thi giong Gemini. Ep chon bang
        # --tts fish / --tts gemini, hoac bam V trong luc chay de doi qua lai.
        self.tts_mode = "fish" if os.environ.get("FISH_AUDIO_API_KEY") else "gemini"
        if "--tts" in sys.argv:
            self.tts_mode = sys.argv[sys.argv.index("--tts") + 1].lower()
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "")
        self.body = None             # phan than (body_link.Body), None neu chua cam
        self.flash = None            # (mat, chu, het_han): mat tam thoi, vd gap vat can
        self.local = self.engine = None
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not self.gemini_key:
            self.state = "error"
            self.info = "THIEU GEMINI KEY: tao file head-demo/gemini-key.txt (xem README)"
            print(self.info)
            return
        # LLM = LLM LOCAL cua Ngoc Anh: settings.py dat LLM_PROVIDER="ollama", model
        # OLLAMA_LLM_MODEL (qwen3.5:2b) chay tren card do hoa laptop, khong len mang.
        # Chi khi chay voi --llm-online moi cho phep doi sang Groq/Gemini (du phong).
        settings.GEMINI_API_KEY = self.gemini_key
        if not ollama_running():
            if "--llm-online" in sys.argv:
                settings.LLM_PROVIDER = "groq" if os.environ.get("GROQ_API_KEY") else "gemini"
            else:
                self.state = "error"
                self.info = (f"CHUA BAT OLLAMA (LLM local cua Ngoc Anh, model {settings.OLLAMA_LLM_MODEL}): "
                             "mo app Ollama roi chay lai (xem README muc 3)")
                print(self.info)
                return
        try:
            from server.voice.runtime import local
            from server.llm import engine
            import gemini_stt
        except Exception as e:  # thieu thu vien...
            self.state, self.info = "error", f"Loi nap AI giong noi: {e}"
            print(self.info)
            return
        self.local, self.engine, self.stt = local, engine, gemini_stt
        self.state = "ready"
        self.info = (f"San sang. Nghe: Gemini Transcribe | LLM: "
                     f"{getattr(engine, '_provider_name', None) or settings.LLM_PROVIDER} | "
                     f"Giong: {self.tts_name()}. Bam SPACE de noi.")
        print(self.info)

    def _listen(self):
        """Ghi am (mic robot, hoac mic laptop neu chay --laptop-mic / chua gan mic that),
        roi gui Gemini chep thanh chu."""
        audio = self._listen_robot_mic() if self.use_robot_mic else self._listen_laptop_mic()
        if not audio:
            print("[nghe] khong co tieng noi nao de gui Gemini.")
            return ""
        self.info = "Gemini dang chep loi noi..."
        text = self.stt.transcribe(audio, self.gemini_key)
        print(f"[nghe] gui Gemini {len(audio) / 32000:.1f}s am thanh -> Gemini tra ve: {text!r}")
        return text

    def _listen_laptop_mic(self):
        """Duong cu: ghi am bang ham cua nhom (mic LAPTOP), dung khi chay --laptop-mic."""
        self.local._abort_event.clear()
        return self.local._record_until_silence(
            # 1,5 giay im lang la chot cau (mac dinh cua nhom 3 giay): lenh "stop" phai nhanh.
            silence_sec=min(1.5, self.local.QUESTION_SILENCE_SEC),
            max_sec=self.local.QUESTION_MAX_SEC,
            wait_timeout=6.0,
            yield_on_pause=False,
        )

    def _listen_robot_mic(self):
        """Duong moi: ghi am bang MIC ROBOT (INMP441 tren head-demo, gui PCM qua day USB).
        Tu doc buffer trong luc "mic on", tu nhan ra luc bat dau / ngung noi NGAY TRONG HAM NAY
        (firmware chi lo gui tho), roi lam sach (mic_clean.py) truoc khi tra ve de gui Gemini."""
        # Bo khung cu con sot tu lan ghi truoc (vd mic "on" tre, hoac "off" truoc chua kip
        # don het) de khong lay nham tieng cua lan hoi truoc vao dau lan nay.
        while not self.mic_queue.empty():
            try:
                self.mic_queue.get_nowait()
            except queue.Empty:
                break
        self.link.send(b"mic on\n")
        chunks, levels = [], []
        skip = mic_clean.SKIP_START_SEC
        # Thoi gian dem theo SO MAU nhan duoc, khong theo dong ho: khung qua day USB co luc den
        # don cuc, dem theo dong ho se tuong im lang trong khi tieng noi van dang nam tren day.
        pos = 0.0
        voice_start = voice_end = None
        deadline = time.time() + self.MAX_SEC + 2  # phong khi board ngung gui han
        try:
            while pos < self.MAX_SEC and time.time() < deadline:
                if voice_end is None and pos > self.WAIT_SEC:
                    break  # bam SPACE roi ma khong ai noi
                if voice_end is not None and pos - voice_end > self.SILENCE_SEC:
                    break  # noi xong roi
                try:
                    data = self.mic_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                samples = np.frombuffer(data, dtype=np.int16)
                if skip > 0:
                    skip -= len(samples) / SAMPLE_RATE
                    continue
                chunks.append(data)
                pos += len(samples) / SAMPLE_RATE
                levels.append(mic_clean.voice_level(samples))
                if mic_clean.is_voice(levels):
                    voice_start = pos if voice_start is None else voice_start
                    voice_end = pos
        finally:
            self.link.send(b"mic off\n")
        audio = b"".join(chunks)
        if not audio:
            print("[mic] KHONG nhan duoc khung mic nao: firmware chua co mic, hoac log khoi dong bao mic LOI.")
            return b""
        mic_clean.save_wav(HERE / "debug_mic_last.wav", audio)
        print(f"[mic] ghi {pos:.1f}s | on nen ~{np.percentile(levels, 15):.0f}, nguong "
              f"{mic_clean.voice_threshold(levels):.0f}, to nhat {max(levels):.0f} -> "
              + (f"CO tieng noi {voice_start:.1f}s-{voice_end:.1f}s" if voice_end else "KHONG thay tieng noi"))
        wraps = mic_clean.count_wraps(audio)
        if wraps:
            print(f"[mic] CANH BAO: {wraps} lan so bi tran (tieng lop bop) -> board van chay firmware CU,"
                  " nap lai head-demo (pio run -t upload)!")
        if voice_end is None:
            return b""
        audio, gain = mic_clean.clean(audio, voice_start, voice_end)
        mic_clean.save_wav(HERE / "debug_mic_last_clean.wav", audio)
        print(f"[mic] lam sach: giu {len(audio) / 32000:.1f}s quanh tieng noi, to len x{gain:.1f}. Nghe thu:"
              " debug_mic_last.wav (tho) / debug_mic_last_clean.wav (ban gui Gemini)")
        return audio

    @property
    def busy(self):
        return self.state in self.FACE

    def face_override(self):
        if self.flash and time.time() < self.flash[2]:
            return self.flash[0], self.flash[1]
        if self.state not in self.FACE:
            if self.body and self.body.running:
                caption = {"run": "MOON DANG CHAY", "left": "MOON RE TRAI", "right": "MOON RE PHAI"}
                return "happy", caption.get(self.body.mode, "MOON DANG CHAY")
            return None
        face, text = self.FACE[self.state]
        if self.state == "speaking" and self.caption:
            text = self.caption
        return face, text

    def _not_ready(self, what):
        """Phim bam luc AI chua san sang: bao ro ly do thay vi im lang."""
        reason = {"loading": "AI giong noi dang nap, doi vai giay",
                  "error": self.info}.get(self.state, f"robot dang ban ({self.state})")
        print(f"[{what}] chua chay duoc: {reason}")
        if self.state not in ("error",):
            self.info = f"{what}: {reason}"

    def talk(self):
        if self.state != "ready":
            return self._not_ready("SPACE")
        print("[SPACE] Bat dau nghe...")
        threading.Thread(target=self._conversation, daemon=True).start()

    def say(self, text):
        if self.state != "ready":
            return self._not_ready("T")
        print("[T] Thu loa robot...")
        threading.Thread(target=self._speak_only, args=(text,), daemon=True).start()

    def _speak_only(self, text):
        self._speak(text)
        self.state = "ready"

    def _conversation(self):
        self.caption = ""
        where = "mic robot (dinh dau)" if self.use_robot_mic else "mic laptop"
        self.state, self.info = "listening", f"Dang nghe... noi vao {where}"
        try:
            text = self._listen()
        except Exception as e:
            print("Loi thu am/Gemini:", repr(e))
            self.state = "ready"
            self.info = f"Loi Gemini ({type(e).__name__}): kiem tra key + internet. Bam SPACE thu lai."
            return
        if not text:
            self.state, self.info = "ready", "Khong nghe ro. Bam SPACE noi lai."
            return
        self.question = text
        print(f"\nBan noi: {text}")

        cmd = body_command(text)
        if cmd:
            return self._body_command(cmd)

        self.state, self.info = "thinking", "Dang nghi..."
        try:
            reply = self.engine.chat(text)
        except Exception as e:
            reply = ""
            print("Loi LLM:", e)
        if not reply:
            self.state, self.info = "ready", "LLM khong tra loi (xem cua so den)."
            return
        self.answer = reply
        print(f"Moon:    {reply}")

        # Cau hoi tu vung (vd "con meo tieng Nhat la gi") -> hien tu len man robot
        info = None
        try:
            info = self.engine.learning_display_info(text)
        except Exception:
            pass
        if info:
            en = ascii_vi(str(info.get("en") or "")).upper()
            romaji = ascii_vi(str(info.get("ja_romaji") or info.get("romaji") or "")).upper()
            self.caption = " / ".join(x for x in (en, romaji) if x)[:22]
        self._speak(reply)
        self.state = "ready"
        self.info = "Xong. Bam SPACE de noi tiep."

    BODY_REPLY = {"run": "Moon chạy đây!", "back": "Moon lùi lại đây!",
                  "left": "Moon rẽ trái đây!", "right": "Moon rẽ phải đây!"}
    BODY_ACTION = {"run": "run", "back": "back", "left": "turn_left", "right": "turn_right"}

    def _body_command(self, cmd):
        """Lenh "run"/"left"/"right"/"stop": khong hoi LLM, ra lenh cho phan than roi noi
        xac nhan ngan."""
        if not (self.body and self.body.online):
            reply = "Mình chưa nối được phần thân, bạn cắm cáp và nạp body-test giúp mình nhé."
        elif cmd == "stop":
            self.body.stop()
            reply = "Moon dừng lại rồi."
        elif getattr(self.body, self.BODY_ACTION[cmd])():
            reply = self.BODY_REPLY[cmd]
        else:
            reply = "Phía trước có vật cản, Moon không chạy được."
        print(f"[THAN] lenh {cmd.upper()} -> {reply}")
        self.answer = reply
        self._speak(reply)
        self.state = "ready"
        self.info = "Xong. Bam SPACE de noi tiep (\"stop\" de dung)."

    def body_key(self, cmd):
        """Phim W / S / A / D / L: tien / lui / re trai / re phai / dung, khong can noi
        (du phong khi lop on). Bam 1 lan la chay tiep cho toi khi bam phim khac hoac L."""
        if not self.body:
            print("[THAN] chua cam board than (body-test).")
            return
        if cmd == "stop":
            self.body.stop()
        elif not getattr(self.body, self.BODY_ACTION[cmd])():
            print("[THAN] dang co vat can, khong chay.")
        print(f"[THAN] phim -> {self.body.status_text()}")

    def on_obstacle(self):
        """Goi tu body_link khi dang chay ma gap vat can (board da tu dung banh)."""
        print("[THAN] VAT CAN -> dung")
        self.flash = ("surprised", "VAT CAN!", time.time() + 2.5)
        if self.state == "ready":
            self.state = "speaking"
            self._speak("Có vật cản phía trước, Moon dừng lại nhé!")
            self.state = "ready"

    def _synth(self, sentence):
        """Tao giong 1 cau bang TTS dang chon (self.tts_mode = 'fish' hoac 'gemini').
        Dich vu online thinh thoang loi/qua tai -> thu lai toi da 3 lan roi moi bo cau."""
        import moon_tts
        for attempt in range(3):
            try:
                if self.tts_mode == "fish":
                    return moon_tts.fish_synth(sentence, os.environ["FISH_AUDIO_API_KEY"], settings)
                return moon_tts.gemini_synth(sentence, self.gemini_key)
            except Exception as e:
                print(f"Loi TTS {self.tts_mode} (lan {attempt + 1}):", e)
            time.sleep(0.4 * (attempt + 1))
        return None

    def toggle_tts(self):
        if not os.environ.get("FISH_AUDIO_API_KEY"):
            print("[V] Chua co fish-key.txt -> chi dung duoc giong Gemini.")
            return
        self.tts_mode = "gemini" if self.tts_mode == "fish" else "fish"
        self.info = f"Doi giong robot: {self.tts_name()}"
        print(self.info)

    def tts_name(self):
        return ("Fish Audio " + getattr(settings, "FISH_TTS_MODEL", "")) if self.tts_mode == "fish" \
            else "Gemini (" + __import__("moon_tts").GEMINI_VOICE + ")"

    def _speak(self, text):
        """Cat cau tra loi thanh tung cau ngan, tao giong va phat lan luot: cau dai de bi dich vu TTS
        tu choi hon, va robot bat dau noi som hon (khong doi tao giong ca doan)."""
        self.state, self.info = "speaking", f"Dang tao giong noi ({self.tts_name()})..."
        # LLM hay chen emoji (🐼✨) -> bo di, khong thi TTS doc ten emoji hoac im lang la.
        text = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️‍*#_`]", "", text)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if s.strip()]
        # Tao giong TAT CA cac cau cung luc (song song) ngay tu dau: trong luc cau 1 dang phat,
        # cau 2, 3... da san sang -> het cau la noi tiep ngay, khong im 1-2 giay cho TTS.
        pool = ThreadPoolExecutor(max_workers=3)
        jobs = [pool.submit(self._synth, s) for s in sentences]
        spoken = 0
        for job in jobs:
            samples = job.result()
            if samples is None or not len(samples):
                print(f"Bo qua 1 cau vi {self.tts_name()} khong tra am thanh.")
                continue
            # Dich vu TTS hay chen khoang lang o dau/cuoi moi doan -> cat bo, chi chua
            # 0,15 giay nghi giua 2 cau cho tu nhien.
            loud = np.nonzero(np.abs(samples) > 500)[0]
            if len(loud):
                samples = samples[max(0, loud[0] - 800) : loud[-1] + 800]
            samples = np.concatenate([samples, np.zeros(SAMPLE_RATE * 15 // 100, np.int16)])
            if self.volume != 1.0:
                samples = np.clip(samples * self.volume, -32767, 32767).astype(np.int16)
            self.info = "Robot dang noi..."
            # Chi cho loa phat het o cau CUOI; cac cau giua gui noi duoi lien mach.
            self._stream(samples.tobytes(), wait=(job is jobs[-1]))
            spoken += 1
        pool.shutdown(wait=False)
        if not spoken:
            self.info = f"TTS loi - {self.tts_name()} khong tra am thanh (kiem tra internet/key, thu lai)."

    def _stream(self, data: bytes, wait=True):
        """Gui am thanh vua bang toc do loa phat (32KB/giay), chi di truoc ~0,35 giay.
        Gui 1 lan het thi be chua 32KB tren board tran, mat tieng.
        self._play_end = luc loa phat xong phan da gui -> cau sau noi tiep dung nhip, khong chong."""
        chunk = 2048
        bytes_per_sec = SAMPLE_RATE * 2
        t0 = max(time.monotonic(), getattr(self, "_play_end", 0.0))
        self._play_end = t0 + len(data) / bytes_per_sec
        sent = 0
        while sent < len(data):
            ahead = sent / bytes_per_sec - (time.monotonic() - t0)
            if ahead > 0.35:
                time.sleep(ahead - 0.35)
                continue
            part = data[sent : sent + chunk]
            self.link.send(b"pcm %d\n" % len(part) + part)
            sent += len(part)
        if wait:
            # cho loa phat not phan con lai truoc khi doi mat
            time.sleep(max(0.0, self._play_end - time.monotonic()) + 0.15)


# ============================== VE CUA SO ==============================

def bar(panel, y, label, value, color):
    cv2.putText(panel, label, (10, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
    x0, w = 130, PANEL_W - 190
    cv2.rectangle(panel, (x0, y), (x0 + w, y + 14), (60, 60, 60), -1)
    cv2.rectangle(panel, (x0, y), (x0 + int(w * max(0.0, min(1.0, value))), y + 14), color, -1)
    cv2.putText(panel, f"{value * 100:4.0f}%", (x0 + w + 6, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)


def wrap(text, width):
    words, lines, cur = ascii_vi(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def draw(frame, result, cam_fps, sent, voice):
    view = frame.copy()
    panel = np.full((view.shape[0], PANEL_W, 3), 30, np.uint8)
    if result and result.get("face_box"):
        x, y, w, h = map(int, result["face_box"])
        cv2.rectangle(view, (x, y), (x + w, y + h), (0, 255, 0), 2)
        label = NAME_VI.get(result["emotion"], "Chua ro")
        cv2.putText(view, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
        cv2.putText(view, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    y = 24
    cv2.putText(panel, f"Camera {cam_fps:4.1f} khung/s", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 200, 150), 1)
    y += 24
    cv2.putText(panel, f"-> Man hinh: {sent[0]}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1)
    if REMOTE_URL:
        cv2.putText(panel, f"Tay cam: {REMOTE_URL}", (10, view.shape[0] - 22 * 6), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (200, 160, 255), 1)
    if result and result.get("face_detected"):
        y += 30
        cv2.putText(panel, f"CAM XUC: {NAME_VI.get(result['emotion'], 'Chua ro')}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        scores = result.get("emotion_scores") or {}
        y += 8
        for name in EMOTIONS:
            y += 20
            bar(panel, y, NAME_VI[name], scores.get(name, 0.0), (80, 200, 80))
    else:
        cv2.putText(panel, "Khong thay mat nao", (10, y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    if voice.body:
        body = voice.body
        col = (60, 60, 255) if body.blocked or not body.online else ((0, 255, 255) if body.running else (180, 180, 180))
        parts = body.status_text().split(" | ")
        for i, part in enumerate(parts):
            cv2.putText(panel, part, (10, view.shape[0] - 22 * len(parts) + 14 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)

    top = np.hstack([view, panel])
    strip = np.full((VOICE_H, top.shape[1], 3), 18, np.uint8)
    color = {"ready": (120, 220, 120), "error": (60, 60, 255)}.get(voice.state, (0, 200, 255))
    cv2.putText(strip, f"GIONG NOI [{voice.state}]  am luong x{voice.volume:.2f}:  {ascii_vi(voice.info)}",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    lines = [("Ban:  ", voice.question), ("Moon: ", voice.answer)]
    yy = 46
    for prefix, text in lines:
        for i, ln in enumerate(wrap(text, 130)[:2]):
            cv2.putText(strip, (prefix if i == 0 else "      ") + ln, (10, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1)
            yy += 18
    return np.vstack([top, strip])


def main():
    port = pick_port()
    shared = Shared()
    if port:
        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = port, BAUD, 0.05
        ser.dtr = ser.rts = False  # khong lam board tu reset khi mo cong
        try:
            ser.open()
        except serial.SerialException as e:
            print("KHONG MO DUOC CONG", port, "-", e)
            print("-> Dong Serial Monitor / chuong trinh khac dang giu cong roi chay lai.")
            return
        ser.set_buffer_size(rx_size=4 * 1024 * 1024)  # luong doc lo cham vai chuc ms cung khong mat byte
        link = Link(ser)
        print(f"Dang doc camera qua day USB o {port}. Dang nap AI (lan dau mat vai chuc giay)...")
    else:
        # Khong cam day board dau -> qua WiFi. Board dau + laptop phai cung mang (hotspot).
        i = sys.argv.index("--wifi") if "--wifi" in sys.argv else -1
        ip = sys.argv[i + 1] if 0 <= i < len(sys.argv) - 1 and not sys.argv[i + 1].startswith("--") else None
        link = WifiLink(ip)
        shared.port_ok = False  # chua noi: reader() se tu tim board roi noi
        print("Khong thay day USB toi board dau -> dung WiFi (board dau phai bat + vao cung hotspot).")
        print("Dang nap AI (lan dau mat vai chuc giay)...")
    ser = link  # cac cho cu goi ser.close() luc thoat
    for target, args in ((reader, (link, shared)), (ai_worker, (shared,))):
        threading.Thread(target=target, args=args, daemon=True).start()
    voice = Voice(link, shared.mic_queue)

    # Phan THAN (tuy chon): board DevKit C chay body-test.
    #   - cam day USB vao laptop  -> dieu khien qua day
    #   - cam sac du phong        -> dieu khien qua WiFi (board phai vao cung mang voi laptop)
    from body_link import SPEED_STEP, Body, find_body_port
    if "--no-body" not in sys.argv:
        body_port = find_body_port(exclude=port)  # (find_body_port bo qua board dau CH343 nho exclude)
        try:
            voice.body = Body(body_port, on_obstacle=voice.on_obstacle)
            where = body_port or "WiFi (cho board than phat tin hieu...)"
            print(f"Phan than: {where}. Noi \"run\" de chay, \"stop\" de dung (phim W / L).")
        except (serial.SerialException, OSError) as e:
            print(f"Khong mo duoc ket noi phan than: {e} (dong Serial Monitor / chay-test.bat).")

    # Tay cam dien thoai: trang web do laptop phat (xem tools/remote.py).
    global REMOTE_URL
    if "--no-remote" not in sys.argv:
        import remote
        try:
            urls = remote.start(shared, voice)
            REMOTE_URL = urls[0] if urls else f"http://<IP laptop>:{remote.PORT}"
            print(f"TAY CAM DIEN THOAI: dien thoai vao cung hotspot, mo {REMOTE_URL}"
                  + (f"  (hoac {', '.join(urls[1:])})" if len(urls) > 1 else ""))
            print("  Lan dau Windows hoi tuong lua cho python -> tick CA Private lan Public roi Allow.")
        except OSError as e:
            print(f"Khong mo duoc tay cam dien thoai (cong {remote.PORT} dang ban?): {e}")

    if "--tone" in sys.argv:
        # Chan doan tieng re: phat tieng "tut" 440Hz sach 100% qua DUNG duong USB cua giong noi,
        # o 3 muc to 20% / 50% / 90%. Tut sach -> duong truyen OK; tut cung re -> dây/nguon.
        t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
        for level in (0.2, 0.5, 0.9):
            print(f"Tut 440Hz, muc {int(level * 100)}%...")
            voice._stream((np.sin(2 * np.pi * 440 * t) * 32767 * level).astype(np.int16).tobytes())
            time.sleep(0.5)
        shared.stop = True
        ser.close()
        return

    if "--say" in sys.argv:  # chay thu loa khong can camera: head_demo.py --say "cau noi"
        text = sys.argv[sys.argv.index("--say") + 1]
        while voice.state == "loading":
            time.sleep(0.2)
        voice._speak(text)
        shared.stop = True
        ser.close()
        return

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    link.send(b"cam natural\n")
    sent, last_send, last_shown = ("", ""), 0.0, -1
    started, last_placeholder, warned = time.time(), 0.0, False
    print("\nPHIM (bam o cua so camera HOAC o cua so den nay): SPACE noi | T thu loa | V doi giong Fish/Gemini"
          " | +/- am luong | Q thoat")
    print("LAI THAN: W tien / S lui / A xoay trai / D xoay phai / L phanh | E tang toc / R giam toc"
          " | , . chinh lech khi di thang bi lech (, = keo sang trai, . = keo sang phai)")
    print("Lenh noi (bam SPACE roi noi): \"run\"/\"chay\" -> tien | \"back\"/\"lùi\" -> lui |"
          " \"left\"/\"trái\" -> re trai | \"right\"/\"phải\" -> re phai | \"stop\"/\"dừng\" -> dung\n")
    while True:
        with shared.lock:
            frame, fid, result, fps = shared.frame, shared.frame_id, shared.result, shared.cam_fps
        now = time.time()
        if frame is not None and fid != last_shown:
            last_shown = fid
            cmd = voice.face_override() or (robot_command(result) if result else ("sleepy", "DANG NAP AI"))
            if cmd != sent or now - last_send > 2:
                link.send(f"face {cmd[0]} {cmd[1]}\n".encode("ascii"))
                sent, last_send = cmd, now
            cv2.imshow(WINDOW, draw(frame, result, fps, sent, voice))
        elif frame is None and now - last_placeholder > 0.3:
            # Chua co anh nao tu board: van hien cua so (de bam phim + doc trang thai) kem loi nhan.
            last_placeholder = now
            blank = np.zeros((480, 640, 3), np.uint8)
            if not shared.port_ok and isinstance(link, WifiLink):
                msg = ["CHUA NOI DUOC BOARD DAU QUA WIFI", "Dang tu tim + noi lai...",
                       "-> Board dau da bat nguon chua? Hotspot laptop bat chua?",
                       "   KHONG can tat chuong trinh nay."]
            elif not shared.port_ok:
                msg = ["MAT KET NOI USB VOI BOARD DAU", "Dang tu noi lai...",
                       "-> Kiem tra day USB. Board vua nap code thi doi vai giay.",
                       "   KHONG can tat chuong trinh nay."]
            else:
                msg = ["CHUA NHAN DUOC ANH TU BOARD", "Board dang chay firmware khac?",
                       "-> Dong cua so nay, mo thu muc head-demo trong VS Code,",
                       "   bam Upload, roi chay lai chay-demo.bat"]
            for i, line in enumerate(msg):
                cv2.putText(blank, line, (20, 200 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1)
            cv2.imshow(WINDOW, draw(blank, None, 0.0, sent, voice))
            if not warned and shared.port_ok and now - started > 5:
                warned = True
                print("!! 5 giay chua nhan duoc anh camera: board chua nap firmware head-demo "
                      "(hoac camera loi). Loa cung se KHONG phat vi firmware cu khong nhan am thanh.")
        key = cv2.waitKey(1) & 0xFF
        # chr(...).lower(): bat Caps Lock / giu Shift van nhan phim (T hoa = t thuong)
        ch = chr(key).lower() if key != 255 else ""
        # Phim go o cua so den (cmd) cung duoc nhan, khong bat buoc chon cua so camera.
        while msvcrt and msvcrt.kbhit():
            c = msvcrt.getwch()
            if c == "\x1b":
                key = 27
            elif c not in ("\x00", "\xe0"):
                ch = c.lower()
        if key == 27 or ch == "q" or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
            break
        if ch == " ":
            voice.talk()
        elif ch == "t":
            voice.say("Xin chào, mình là Moon. Loa của mình đã hoạt động rồi nhé!")
        elif ch == "v":
            voice.toggle_tts()
        # Lai than kieu game: W tien, S LUI, A/D xoay trai/phai, L dung.
        # "ư": bo go tieng Viet (Telex) dang bat thi phim W ra chu "ư".
        elif ch in ("w", "ư"):
            voice.body_key("run")
        elif ch == "s":
            voice.body_key("back")
        elif ch == "a":
            voice.body_key("left")
        elif ch == "d":
            voice.body_key("right")
        elif ch == "l":
            voice.body_key("stop")  # phanh: firmware noi tat motor -> banh dung ngay
        elif ch in ("e", "r", ",", ".") and voice.body:
            # E/R: tang/giam toc do (+-25). ","/".": xe di thang ma lech -> keo sang trai/phai
            # (moi lan 2%, tu luu vao body-trim.txt).
            b = voice.body
            if ch == "e":
                print(f"[THAN] tang toc -> {b.faster()}")
            elif ch == "r":
                print(f"[THAN] giam toc -> {b.faster(-SPEED_STEP)}")
            else:
                b.nudge(0.02 if ch == "," else -0.02)
                print(f"[THAN] chinh lech -> {b.trim_text()}")
        elif ch in ("+", "="):
            voice.volume = min(3.0, voice.volume + 0.25)
        elif ch == "-":
            voice.volume = max(0.25, voice.volume - 0.25)
    shared.stop = True
    if voice.body:
        voice.body.close()  # gui "m 0 0": banh dung truoc khi thoat
    time.sleep(0.2)
    ser.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
