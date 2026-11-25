"""Dieu khien phan THAN robot tu laptop: qua day USB, hoac qua WiFi khi than cam SAC DU PHONG.

Board than chay firmware body-test (MOON/body-test), cung giao thuc voi tools/lai_xe.py:
  laptop -> board : "m <trai> <phai>\\n"   toc do -255..255 (am = lui), gui lien tuc ~20 lan/giay
                    (board tu dung neu ~0,5 giay khong nhan lenh — an toan khi mat ket noi)
  board -> laptop : "S <cm> <trai> <phai> <bi_chan>\\n"

  Day USB : Serial 115200.
  WiFi    : UDP. Board phat trang thai cho ca mang (cong 4210) -> laptop nghe thay thi biet
            dia chi IP cua board, roi gui lenh toi cong 4211 cua board. Khong can go IP.

Luat:
  run()/back()/turn_left()/turn_right() -> chay cho den khi stop(), gap vat can, hoac het
  MAX_RUN_SEC. drive(mode, hold=True): kieu TAY CAM — chi chay khi con duoc goi lai lien tuc
  (nut dang duoc giu); ngung goi ~0,5 giay (tha nut, mat mang) -> tu dung.
  Gap vat can (< 12cm) -> board tu dung NGAY khi dang di TOI (luat tren board); laptop cung
  tat che do "run" de xe KHONG tu chay lai khi vat can di mat (phai ra lenh lai).
  Lui va re VAN DUOC khi dang bi chan -> xe thoat khoi vat can.

  Re = XOAY TAI CHO: 2 banh quay nguoc chieu (re trai = banh trai lui, banh phai tien).
  Can firmware body-test co so lui (toc do am). Firmware cu (0..255) se coi so am la 0
  -> re chi con 1 banh quay, lui thi dung yen: nap lai body-test.
"""
import socket
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

BAUD = 115200
STATUS_PORT = 4210  # laptop nghe
CMD_PORT = 4211     # board nghe


def find_body_port(exclude=None):
    """DevKit C dung chip USB-Serial CP2102 (VID 10C4) hoac CH340 (VID 1A86).
    Board dau ESP32-S3 (VID 303A) va cong dang dung cho dau (exclude) bi bo qua."""
    for p in list_ports.comports():
        # PID 55D3 = chip CH343 cua board DAU (co the dang cam chi de lay dien) -> bo qua.
        if p.device != exclude and p.vid in (0x10C4, 0x1A86) and p.pid != 0x55D3:
            return p.device
    return None


class SerialLink:
    def __init__(self, port):
        self.name = port
        self.ser = serial.Serial(port, BAUD, timeout=0)
        self.buf = b""

    def send(self, line):
        self.ser.write(line.encode())

    def lines(self):
        self.buf += self.ser.read(512)
        while b"\n" in self.buf:
            raw, self.buf = self.buf.split(b"\n", 1)
            yield raw

    def close(self):
        self.ser.close()


class WifiLink:
    def __init__(self):
        self.name = "WiFi"
        self.peer = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", STATUS_PORT))
        self.sock.setblocking(False)

    def send(self, line):
        if self.peer:
            self.sock.sendto(line.encode(), (self.peer, CMD_PORT))

    def lines(self):
        while True:
            try:
                data, (ip, _) = self.sock.recvfrom(256)
            except (BlockingIOError, ConnectionResetError):
                return
            if data.startswith(b"S "):
                if self.peer != ip:
                    print(f"[THAN] tim thay board than qua WiFi: {ip}")
                self.peer = ip
            for raw in data.split(b"\n"):
                if raw:
                    yield raw

    def close(self):
        self.sock.close()


TRIM_FILE = Path(__file__).resolve().parent.parent / "body-trim.txt"  # luu do chinh lech banh
SPEED_MIN, SPEED_MAX, SPEED_STEP = 80, 255, 25  # duoi ~80 motor TT yeu qua, khong nhuc nhich
RAMP_START, RAMP_STEP = 90, 15  # tang toc dan: bat dau 90, moi 50ms +15 -> toi toc do dat trong ~0,5s
TURN_RATIO = 0.75               # xoay tai cho cham hon chay thang 1 chut, de lai cho trung huong


def wheel_speeds(mode, cur, trim):
    """Toc do (trai, phai) gui cho board. cur = toc do hien tai (dang tang dan),
    trim > 0 = giam banh TRAI (xe dang lech sang phai), trim < 0 = giam banh PHAI.
    Hai motor TT re tien khong bao gio quay deu nhau; chinh lech bu lai de di thang."""
    t = int(cur * TURN_RATIO)
    left, right = {
        "run": (cur, cur),
        "back": (-cur, -cur),
        "left": (-t, t),   # xoay tai cho: 2 banh nguoc chieu
        "right": (t, -t),
    }.get(mode, (0, 0))
    left = int(left * (1 - max(0.0, trim)))
    right = int(right * (1 + min(0.0, trim)))
    return left, right


class Body:
    def __init__(self, port=None, speed=150, max_run_sec=10.0, on_obstacle=None):
        """port = cong COM (day USB), hoac None -> tim board than qua WiFi."""
        self.link = SerialLink(port) if port else WifiLink()
        self.port = self.link.name
        self.speed = speed
        self._cur = 0          # toc do dang chay that (tang dan toi self.speed)
        self._cur_mode = "stop"
        try:
            self.trim = max(-0.3, min(0.3, float(TRIM_FILE.read_text().strip())))
        except (OSError, ValueError):
            self.trim = 0.0
        self.max_run_sec = max_run_sec
        self.on_obstacle = on_obstacle
        self.mode = "stop"  # "stop" | "run" | "back" | "left" | "right"
        self.run_since = 0.0
        self.hold_until = None  # kieu tay cam: qua moc nay ma khong duoc goi lai -> dung
        self.dist = None        # cm, None = chua co so lieu, -1 = khong co vat trong tam
        self.blocked = False
        self.wheels = (0, 0)
        self.last_status = 0.0
        self.stop_flag = False
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def online(self):
        return time.time() - self.last_status < 1.5

    @property
    def running(self):
        """Tuong thich code cu: True neu dang chay o BAT KY che do nao (thang/trai/phai)."""
        return self.mode != "stop"

    def _start(self, mode, hold=False):
        # Dang co vat can: cam di toi, nhung cho lui/re de thoat (board cung lam y nhu vay).
        if self.blocked and mode == "run":
            return False
        if mode != self.mode:
            self.run_since = time.time()
        self.mode = mode
        self.hold_until = time.time() + 0.5 if hold else None
        return True

    def drive(self, mode, hold=False):
        """mode: "run" | "back" | "left" | "right" | "stop". Tra False neu bi vat can chan."""
        if mode == "stop":
            self.stop()
            return True
        return self._start(mode, hold)

    def run(self):
        return self._start("run")

    def back(self):
        return self._start("back")

    def turn_left(self):
        return self._start("left")

    def turn_right(self):
        return self._start("right")

    def stop(self):
        """Phanh: firmware body-test nhan toc do 0 -> phanh that (noi tat motor), banh dung ngay."""
        self.mode = "stop"
        self.hold_until = None

    def faster(self, step=SPEED_STEP):
        """Tang (step > 0) / giam (step < 0) toc do. Dang chay thi ap dung ngay."""
        self.speed = max(SPEED_MIN, min(SPEED_MAX, self.speed + step))
        return self.speed

    def nudge(self, delta):
        """Chinh lech banh: delta > 0 = keo xe sang TRAI (giam banh trai), < 0 = sang PHAI.
        Luu ra file de lan sau khoi chinh lai."""
        self.trim = round(max(-0.3, min(0.3, self.trim + delta)), 2)
        try:
            TRIM_FILE.write_text(f"{self.trim}\n")
        except OSError:
            pass
        return self.trim

    def trim_text(self):
        if abs(self.trim) < 0.005:
            return "can bang"
        return f"giam banh {'trai' if self.trim > 0 else 'phai'} {abs(self.trim) * 100:.0f}%"

    def status_text(self):
        if not self.online:
            if isinstance(self.link, WifiLink):
                return "THAN (WiFi): dang tim... | than da bat + vao WiFi chua?"
            return f"THAN ({self.port}): mat ket noi | board da nap body-test chua?"
        d = "khong co vat" if self.dist is None or self.dist < 0 else f"{self.dist:.0f}cm"
        state = {
            "stop": "dung yen", "run": "DANG CHAY", "back": "DANG LUI", "left": "RE TRAI", "right": "RE PHAI",
        }[self.mode]
        if self.blocked:
            state = "VAT CAN" if self.mode in ("stop", "run") else f"VAT CAN, {state}"
        return (f"THAN ({self.port}): {state} | HC-SR04 {d} | banh {self.wheels[0]}/{self.wheels[1]}"
                f" | toc do {self.speed} | lech: {self.trim_text()}")

    def _loop(self):
        while not self.stop_flag:
            now = time.time()
            if self.mode != "stop" and now - self.run_since > self.max_run_sec:
                self.stop()  # chay qua lau -> tu dung (tranh xe lao khoi ban)
            if self.hold_until is not None and now > self.hold_until:
                self.stop()  # tay cam: nut da tha / dien thoai mat mang -> dung
            # Tang toc dan nhu xe that: doi huong (hoac vua xuat phat) thi bat dau cham, roi
            # nhanh dan toi toc do dat. Bot giat, banh khong truot, 2 banh deu nhau hon.
            # Giam toc do (phim R) thi ap dung ngay.
            mode = self.mode
            if mode == "stop":
                self._cur = 0
            elif mode != self._cur_mode:
                self._cur = min(self.speed, RAMP_START)
            else:
                self._cur = min(self.speed, self._cur + RAMP_STEP)
            self._cur_mode = mode
            left, right = wheel_speeds(mode, self._cur, self.trim)
            try:
                self.link.send(f"m {left} {right}\n")
                lines = list(self.link.lines())
            except (serial.SerialException, OSError):
                time.sleep(0.5)
                continue
            for raw in lines:
                parts = raw.decode(errors="replace").split()
                if len(parts) != 5 or parts[0] != "S":
                    continue
                was_blocked = self.blocked
                self.dist = float(parts[1])
                self.wheels = (int(parts[2]), int(parts[3]))
                self.blocked = parts[4] == "1"
                self.last_status = time.time()
                # Chi dung khi dang di THANG; dang re thi de xe re tiep cho thoat vat can.
                if self.blocked and not was_blocked and self.mode == "run":
                    # In ra khoang cach luc bi chan: so lon (vd 300cm) ma van chan = nhieu motor,
                    # khong phai vat that.
                    print(f"[THAN] board bao VAT CAN, HC-SR04 dang do {self.dist:.0f}cm, banh {self.wheels}")
                    self.mode = "stop"
                    if self.on_obstacle:
                        threading.Thread(target=self.on_obstacle, daemon=True).start()
            time.sleep(0.05)

    def close(self):
        # (truoc day co "self.running = False" o day: running la @property chi doc -> nem
        #  AttributeError, nen lenh dung "m 0 0" luc thoat khong bao gio duoc gui)
        self.mode = "stop"
        self.stop_flag = True
        time.sleep(0.1)
        try:
            self.link.send("m 0 0\n")
            self.link.close()
        except (serial.SerialException, OSError):
            pass
