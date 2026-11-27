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
# Toc do PWM 0..255. Mac dinh 170 (~67%). Da thu 220: motor hut dong qua manh, nguon 5V chung voi
# ESP32 than bi sut -> board tu khoi dong lai, mat WiFi vai giay moi lan bam phim (25/11). Khi da
# tach nguon motor rieng (README 4c "Nguon") thi co the bam E de chay nhanh hon.
SPEED_DEFAULT, SPEED_MIN, SPEED_MAX, SPEED_STEP = 170, 110, 255, 25  # duoi ~110 xe hay dung khuc
# Tang toc: bat dau 100, moi vong lap (~40ms) +25 -> toi 170 trong ~0,12 giay. Nhanh hon ban cu
# (90, +15/50ms, ~0,5s, xe "i ach") nhung KHONG giat thang len cao: motor dung yen ma bi dong
# manh ngay = hut dong rat lon -> nguon 5V chung voi ESP32 bi sut -> board than tu khoi dong lai,
# mat WiFi vai giay (do that 25/11 khi thu "moi" 255 / bat dau 170 / mac dinh 220).
# (25/11 lan 2: van BROWNOUT o 170 khi loa + camera cung dang chay -> mem them: 80, +20 ->
#  toi 170 trong ~0,2 giay, van nhanh hon nhieu so voi 0,5 giay luc dau.)
RAMP_START, RAMP_STEP = 80, 20
BOOT_REASON = {  # firmware gui kem trang thai (esp_reset_reason)
    "POWERON": "vua cam nguon",
    "BROWNOUT": "SUT AP - motor hut dong lam tut nguon 5V, xem README muc 4c 'Nguon'",
    "SW": "phan mem tu reset (vd vua nap code qua WiFi)",
    "PANIC": "firmware bi loi (crash)",
    "WDT": "firmware bi treo",
    "EXT": "bam nut EN/RESET",
}
# Xoay tai cho: 2 banh chay nguoc chieu, lop truot ngang tren san -> can luc lon hon chay thang.
# 0.85 toc do thang nhung KHONG duoi 140 (thap hon xe xoay rat cham / khung lai). Khong de cao
# hon: xoay = 2 motor cung gang suc -> de sut ap nhat.
TURN_RATIO, TURN_MIN = 0.85, 140
# Ma ly do chip WiFi cua than bao khi bi rot mang (firmware moi gui kem trang thai).
WIFI_DROP_REASON = {
    200: "MAT SONG hotspot (beacon timeout) - hay gap khi nguon 5V tut luc motor/loa keo manh, hoac song yeu",
    201: "khong thay hotspot",
    2: "hotspot ngat (auth expire) - than im lang qua lau, thuong do sut ap",
    4: "hotspot ngat (assoc expire) - than im lang qua lau, thuong do sut ap",
    3: "hotspot chu dong duoi than ra",
    8: "than tu ngat",
    15: "bat tay WiFi qua lau (4-way handshake timeout)",
    204: "bat tay WiFi qua lau",
}


# Vua chay vua re (giu W + A...) nhu xe dieu khien: banh phia trong cham lai con 40%, xe cua
# vong cung ma KHONG dung lai. (Truoc: dang tien bam A = xoay tai cho -> banh trai phai dao chieu
# -> xe khung lai roi moi re.) 40% chu khong 0: ca 2 banh van quay toi -> firmware van coi la
# "dang tien" va van chan vat can phia truoc.
ARC_INNER = 0.4
FORWARD_MODES = ("run", "fl", "fr")   # fl = tien + re trai, fr = tien + re phai
BACK_MODES = ("back", "bl", "br")
MODES = FORWARD_MODES + BACK_MODES + ("left", "right")


try:
    import ctypes
    _user32 = ctypes.windll.user32
except (ImportError, AttributeError):  # khong phai Windows
    _user32 = None


def keyboard_mode(window_titles):
    """Lai kieu xe dieu khien: doc 4 phim W/A/S/D DANG GIU (khong phai "vua bam"), ket hop:
        W = tien, W+A / W+D = tien + re (cua vong), S = lui, S+A / S+D = lui + re,
        A / D (mot minh) = xoay tai cho.   Khong giu gi -> None (xe phanh).
    Phim go thuong (cv2.waitKey / msvcrt) chi bao 1 phim moi lan + lap phim kieu go chu -> khong
    biet dang giu 2 phim. GetAsyncKeyState cua Windows hoi thang ban phim: phim nay dang nhan khong.
    Chi nhan khi cua so dang chon co ten chua 1 trong window_titles (go chu o trinh duyet khong
    lai xe). Khong phai Windows -> luon None."""
    if _user32 is None:
        return None
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(_user32.GetForegroundWindow(), buf, 256)
    if not any(t in buf.value for t in window_titles):
        return None
    held = {k: bool(_user32.GetAsyncKeyState(ord(k)) & 0x8000) for k in "WASD"}
    w, s, a, d = held["W"], held["S"], held["A"], held["D"]
    turn = "l" if a and not d else "r" if d and not a else ""
    if w and not s:
        return {"l": "fl", "r": "fr"}.get(turn, "run")
    if s and not w:
        return {"l": "bl", "r": "br"}.get(turn, "back")
    return {"l": "left", "r": "right"}.get(turn)


def mode_group(mode):
    """Nhom huong: doi mode trong cung nhom (vd run -> fl) thi xe chay tiep khong tang toc lai."""
    if mode in FORWARD_MODES:
        return "fwd"
    if mode in BACK_MODES:
        return "back"
    return mode  # "left" / "right" (xoay tai cho) / "stop"


def wheel_speeds(mode, cur, trim):
    """Toc do (trai, phai) gui cho board. cur = toc do hien tai (dang tang dan),
    trim > 0 = giam banh TRAI (xe dang lech sang phai), trim < 0 = giam banh PHAI.
    Hai motor TT re tien khong bao gio quay deu nhau; chinh lech bu lai de di thang."""
    t = min(255, max(int(cur * TURN_RATIO), TURN_MIN)) if cur else 0
    i = int(cur * ARC_INNER)
    left, right = {
        "run": (cur, cur),
        "back": (-cur, -cur),
        "left": (-t, t),   # xoay tai cho: 2 banh nguoc chieu
        "right": (t, -t),
        "fl": (i, cur),    # tien + re trai: banh trai (phia trong) cham
        "fr": (cur, i),
        "bl": (-i, -cur),  # lui + re trai
        "br": (-cur, -i),
    }.get(mode, (0, 0))
    left = int(left * (1 - max(0.0, trim)))
    right = int(right * (1 + min(0.0, trim)))
    return left, right


class Body:
    def __init__(self, port=None, speed=SPEED_DEFAULT, max_run_sec=10.0, on_obstacle=None,
                 ramp=(RAMP_START, RAMP_STEP), safety=True):
        """port = cong COM (day USB), hoac None -> tim board than qua WiFi.
        ramp = (toc do luc xuat phat, tang moi vong ~40ms). safety=False: tat luat dung truoc vat
        can (che do dua xe - xe ban phia truoc cung bi tinh la vat can)."""
        self.link = SerialLink(port) if port else WifiLink()
        self.port = self.link.name
        self.speed = speed
        self.ramp_start, self.ramp_step = ramp
        self.safety = safety
        self._last_safe_sent = 0.0
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
        self.uptime = None       # so giay tu luc board than khoi dong (firmware moi gui kem)
        self.boot_reason = None
        self.resets = 0          # so lan board than tu khoi dong lai trong luc chay
        self._was_online = False
        self._lost_at = None
        self.rssi = None         # do manh song WiFi cua than (dBm), firmware moi gui kem
        self.wifi_drops = None   # so lan WiFi cua than bi rot ke tu luc bat
        self.drop_reason = 0
        self._at_loss = None     # (so lan rot, so lan reset) luc mat lien lac -> so khi co lai
        self.activity = None     # ham tra ve robot dang lam gi (head_demo gan: "speaking"...)
        self.stop_flag = False
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def online(self):
        # 2,5 giay: WiFi hotspot thinh thoang tre / rot goi 1-2 giay (camera dau dang chiem song)
        # ma than van chay binh thuong -> 1,5 giay hay bao "mat lien lac" nham.
        return time.time() - self.last_status < 2.5

    @property
    def running(self):
        """Tuong thich code cu: True neu dang chay o BAT KY che do nao (thang/trai/phai)."""
        return self.mode != "stop"

    def _start(self, mode, hold=False):
        # Dang co vat can: cam di toi, nhung cho lui/re de thoat (board cung lam y nhu vay).
        if mode not in MODES:
            return False
        if self.safety and self.blocked and mode in FORWARD_MODES:
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
            "stop": "dung yen", "run": "DANG CHAY", "back": "DANG LUI", "left": "XOAY TRAI", "right": "XOAY PHAI",
            "fl": "TIEN + RE TRAI", "fr": "TIEN + RE PHAI", "bl": "LUI + RE TRAI", "br": "LUI + RE PHAI",
        }[self.mode]
        if self.blocked:
            state = "VAT CAN" if self.mode in ("stop",) + FORWARD_MODES else f"VAT CAN, {state}"
        return (f"THAN ({self.port}): {state} | HC-SR04 {d} | banh {self.wheels[0]}/{self.wheels[1]}"
                f" | toc do {self.speed} | lech: {self.trim_text()}"
                + (f" | song {self.rssi}dBm" if self.rssi is not None and isinstance(self.link, WifiLink) else ""))

    def _loop(self):
        while not self.stop_flag:
            now = time.time()
            # (gui lenh 25 lan/giay thay vi 20: WiFi rot 1-2 goi lien tiep van con du lenh trong
            #  0,5 giay ma board cho, xe khong khung giua duong)
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
            elif mode_group(mode) != mode_group(self._cur_mode):
                # vua xuat phat / doi huong chay (tien <-> lui <-> xoay) -> tang toc lai tu dau.
                # Doi trong cung nhom (dang tien them re trai) thi giu nguyen toc do, xe khong khung.
                self._cur = min(self.speed, self.ramp_start)
            else:
                self._cur = min(self.speed, self._cur + self.ramp_step)
            self._cur_mode = mode
            left, right = wheel_speeds(mode, self._cur, self.trim)
            try:
                self.link.send(f"m {left} {right}\n")
                # Bat/tat luat vat can: gui lai moi giay (UDP co the rot goi; board khoi dong lai
                # thi tu ve BAT). Firmware cu khong hieu lenh nay -> bo qua, khong sao.
                if now - self._last_safe_sent > 1.0:
                    self._last_safe_sent = now
                    self.link.send(f"safe {1 if self.safety else 0}\n")
                lines = list(self.link.lines())
            except (serial.SerialException, OSError):
                time.sleep(0.5)
                continue
            for raw in lines:
                parts = raw.decode(errors="replace").split()
                if len(parts) < 5 or parts[0] != "S":
                    continue
                was_blocked = self.blocked
                self.dist = float(parts[1])
                self.wheels = (int(parts[2]), int(parts[3]))
                self.blocked = parts[4] == "1"
                self.last_status = time.time()
                if len(parts) >= 7:  # firmware moi: "S cm L R chan giay_tu_luc_bat ly_do"
                    self._check_reboot(int(parts[5]), parts[6])
                if len(parts) >= 10:  # ... + "song_dBm so_lan_rot_wifi ma_ly_do"
                    self.rssi, self.wifi_drops, self.drop_reason = int(parts[7]), int(parts[8]), int(parts[9])
                # Chi dung khi dang di TOI; dang lui/xoay thi de xe chay tiep cho thoat vat can.
                if self.safety and self.blocked and not was_blocked and self.mode in FORWARD_MODES:
                    # In ra khoang cach luc bi chan: so lon (vd 300cm) ma van chan = nhieu motor,
                    # khong phai vat that.
                    print(f"[THAN] board bao VAT CAN, HC-SR04 dang do {self.dist:.0f}cm, banh {self.wheels}")
                    self.mode = "stop"
                    if self.on_obstacle:
                        threading.Thread(target=self.on_obstacle, daemon=True).start()
            self._check_link()
            time.sleep(0.04)

    def _check_reboot(self, uptime, reason):
        """So giay tu luc bat bi TUT xuong = board than vua tu khoi dong lai -> bao ly do 1 lan."""
        first = self.uptime is None
        if first or uptime + 2 < self.uptime:
            self.boot_reason = reason
            why = BOOT_REASON.get(reason, reason)
            if first:
                print(f"[THAN] board than chay duoc {uptime}s, lan khoi dong gan nhat: {reason} ({why})")
            else:
                self.resets += 1
                print(f"[THAN] !!! board than vua TU KHOI DONG LAI (lan {self.resets}): {reason} - {why}")
        self.uptime = uptime

    def _check_link(self):
        """In 1 dong khi mat / co lai lien lac voi than (thay vi in lap lai moi lan bam phim)."""
        online = self.online
        if self._was_online and not online:
            self._lost_at = time.time()
            self._at_loss = (self.wifi_drops, self.resets)
            doing = []
            if self.mode != "stop":
                doing.append(f"xe dang chay ({self.mode}, banh {self.wheels[0]}/{self.wheels[1]})")
            act = self.activity() if self.activity else None
            if act in ("speaking", "listening", "thinking"):
                doing.append({"speaking": "MOON dang NOI (loa)", "listening": "MOON dang nghe",
                              "thinking": "MOON dang nghi"}[act])
            sig = f" | song luc truoc {self.rssi}dBm" if self.rssi is not None else ""
            print("[THAN] MAT LIEN LAC voi than (2,5 giay khong nhan trang thai)"
                  + (f" | luc do: {', '.join(doing)}" if doing else " | luc do: xe dung yen") + sig)
        elif online and not self._was_online and self._lost_at:
            print(f"[THAN] co lai lien lac sau {time.time() - self._lost_at:.1f}s -> {self._diagnose()}")
        self._was_online = online

    def _diagnose(self):
        """Mat lien lac vi dau: board reset / WiFi cua than rot that / chi rot goi tin tren song."""
        drops0, resets0 = self._at_loss or (None, self.resets)
        if self.resets > resets0:
            return "board than KHOI DONG LAI (xem dong '!!!' o tren de biet ly do)"
        if self.wifi_drops is None or drops0 is None:
            return "(nap firmware body-test moi de biet ly do)"
        if self.wifi_drops > drops0:
            why = WIFI_DROP_REASON.get(self.drop_reason, f"ma {self.drop_reason}")
            return f"WiFi cua than bi ROT that: {why}"
        weak = self.rssi is not None and self.rssi < -75
        return ("WiFi cua than VAN NOI, chi goi tin bi lac tren song"
                + (f" - song YEU ({self.rssi}dBm), dat robot gan laptop hon" if weak
                   else " - song bi nghen (camera dau dang gui anh) hoac laptop bi kham"))

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
