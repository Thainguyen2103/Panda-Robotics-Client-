"""CHE DO TU DI DAO: Moon tu chay lien tuc (mac dinh 10 phut) va tu ne vat can.

Cach ne (HC-SR04 chi nhin THANG phia truoc, khong quay duoc -> muon "nhin" trai/phai thi xoay
CA XE sang do roi do):
    di thang ... thay vat cach < AVOID_CM
      -> phanh, xoay TRAI ~60 do, do  -> xoay PHAI ~120 do (qua ben phai ~60 do), do
      -> ben nao thoang (> OPEN_CM) thi di huong do (uu tien ben xa hon)
      -> ca 2 ben deu bi chan -> LUI 1 doan roi quay dau, thu lai
      -> bi chan lien tiep TRAPPED_LIMIT lan -> dung han, bao "Moon bi ket".
    Dang chay ma khoang cach phia truoc dung yen ~2 giay (xe sượt hong vao goc / vat thap ma
    HC-SR04 khong thay, banh quay ma xe khong nhuc nhich) -> coi nhu bi ket: lui + quay.

Khong co encoder (cam bien dem vong banh) nen goc xoay tinh bang THOI GIAN: SCAN_TURN_SEC giay
~ 60 do. Xoay it/nhieu qua (san tron / tham, pin yeu) thi chinh bang "--auto-turn 0.6".

An toan:
  - Moi lenh di deu "hold": luong nay chet / laptop treo -> than tu phanh sau 0,5 giay.
  - Firmware than VAN tu phanh khi vat < ~12cm (lop bao ve thu 2 neu laptop phan ung cham).
  - HC-SR04 KHONG thay mep ban / cau thang -> chi chay TU DI DUOI SAN.
  - Nguoi lai bang phim / tay cam / noi "dung" -> tat che do tu di ngay.
"""
import random
import statistics
import threading
import time

AUTO_MINUTES = 10
AUTO_SPEED = 160      # cham hon toc do lai tay: con kip phanh + bot sut ap (xem README "Nguon")
AVOID_CM = 30         # vat gan hon -> bat dau tim duong (firmware chan cung o ~12cm)
OPEN_CM = 45          # huong co khoang trong xa hon muc nay = di duoc
SCAN_TURN_SEC = 0.45  # xoay bao lau ~ 60 do (doi bang --auto-turn)
SETTLE_SEC = 0.3      # dung lai cho xe het rung + HC-SR04 bo ket qua cu (trung vi 3 lan x 60ms)
SAMPLE_SEC = 0.35     # roi lay trung vi cac lan do trong khoang nay
BACK_SEC = 0.6
FAR_CM = 400.0        # HC-SR04 bao -1 = khong co vat trong tam ~4m
# Ket: dang tien ma khoang cach phia truoc doi < 3cm trong 2 giay. Hay gap khi xe sượt HONG vao
# goc tu / chan ghe: HC-SR04 chi nhin 1 hinh non hep phia truoc nen khong thay -> xe day mai vao
# goc (motor ghi = hut dong rat lon). 2 giay chu khong lau hon de bot ghi motor.
STUCK_SEC, STUCK_CM = 2.0, 3.0
TRAPPED_LIMIT = 3     # bi chan 3 lan lien (lui ma van ket) -> dung han
TICK = 0.04
# Song WiFi yeu (xa laptop, phong nhieu mang): goi trang thai cua than lac tung chap. Qua 0,5 giay
# khong co so do MOI = robot dang "mu" (so khoang cach con giu la so cu) -> DUNG cho, khong duoc
# coi so cu la "khoang cach dung yen = bi ket" hay "khong do duoc = vat can 0cm" (loi 27/11 o ITF).
FRESH_SEC = 0.5
MEASURE_WAIT = 2.0    # luc nhin trai/phai: cho toi da 2 giay de co so do moi
UNKNOWN = -1.0        # _measure: khong nhan duoc so do nao (mat goi tin)


class AutoDrive:
    def __init__(self, body, minutes=AUTO_MINUTES, turn_sec=SCAN_TURN_SEC, speed=AUTO_SPEED, on_event=None):
        """on_event(kind, info): bao ra ngoai de doi mat / noi. kind: start, scan, go, back,
        stuck, trapped, lost, end, stop."""
        self.body = body
        self.duration = minutes * 60
        self.turn_sec = turn_sec
        self.speed = speed
        self.on_event = on_event or (lambda kind, info: None)
        self.running = False
        self.state = ""
        self.started_at = 0.0
        self.avoid_count = 0
        self._token = 0
        self._lock = threading.Lock()  # stop() va lenh di cua luong tu di khong chen nhau

    # ---------- dieu khien tu ngoai ----------
    def start(self):
        """Tra ve "" neu bat duoc, hoac ly do khong bat duoc."""
        if self.running:
            return "dang tu di roi"
        if not (self.body and self.body.online):
            return "chua noi duoc phan than"
        with self._lock:
            self._token += 1
            token = self._token
            self.running = True
        self.started_at = time.time()
        self.avoid_count = 0
        self.state = "bat dau"
        print(f"[TU DI] BAT {self.duration / 60:.0f} phut, toc do {self.speed}, ne vat < {AVOID_CM}cm"
              f" (xoay {self.turn_sec}s ~ 60 do)")
        threading.Thread(target=self._run, args=(token,), daemon=True).start()
        self.on_event("start", "")
        return ""

    def stop(self, reason="tat"):
        """Dung ngay (an toan goi tu bat ky luong nao). Tra True neu luc do dang tu di."""
        with self._lock:
            if not self.running:
                return False
            self._token += 1  # moi buoc dang chay cua luong cu deu thay token doi -> thoat
            self.running = False
            self.body.stop()
        self.state = ""
        print(f"[TU DI] TAT ({reason})")
        self.on_event("stop", reason)
        return True

    def remaining(self):
        return max(0.0, self.duration - (time.time() - self.started_at)) if self.running else 0.0

    def status_text(self):
        r = int(self.remaining())
        return f"TU DI con {r // 60}:{r % 60:02d} (ne {self.avoid_count}): {self.state}"

    # ---------- cac buoc nho ----------
    def _alive(self, token):
        return token == self._token

    def _cmd(self, mode, token):
        """Ra lenh cho banh, chi khi luot tu di nay con hieu luc (khong de lenh muon chen sau stop())."""
        with self._lock:
            if not self._alive(token):
                return False
            if mode == "stop":
                self.body.stop()
                return True
            return self.body.drive(mode, hold=True)

    def _hold(self, mode, sec, token):
        """Giu 1 che do trong sec giay (goi lai lien tuc de "gia han" hold). False = bi tat giua chung."""
        end = time.time() + sec
        while time.time() < end:
            if not self._alive(token):
                return False
            if mode != "stop":
                self._cmd(mode, token)
            time.sleep(TICK)
        return self._alive(token)

    def _measure(self, token):
        """Dung han, cho on dinh, roi lay trung vi khoang cach phia truoc (cm).
        None = bi tat giua chung; UNKNOWN = song yeu, khong nhan duoc so do moi nao."""
        self._cmd("stop", token)
        if not self._hold("stop", SETTLE_SEC, token):
            return None
        vals, seen = [], self.body.last_status
        start = time.time()
        # Lay trong SAMPLE_SEC; goi tin bi lac thi cho them (toi MEASURE_WAIT) cho du 2 so do
        while self._alive(token):
            waited = time.time() - start
            if (waited >= SAMPLE_SEC and len(vals) >= 2) or waited >= MEASURE_WAIT:
                break
            if self.body.last_status != seen:  # chi lay goi trang thai MOI
                seen = self.body.last_status
                d = self.body.dist
                if d is not None:
                    vals.append(FAR_CM if d < 0 else d)
            time.sleep(0.02)
        if not self._alive(token):
            return None
        return statistics.median(vals) if vals else UNKNOWN

    def _turn(self, direction, sec, token):
        ok = self._hold(direction, sec, token)
        self._cmd("stop", token)
        return ok

    def _front_near(self):
        b = self.body
        return b.blocked or (b.dist is not None and 0 < b.dist < AVOID_CM)

    # ---------- vong chinh ----------
    def _run(self, token):
        b = self.body
        saved = (b.speed, b.max_run_sec, b.safety)
        b.speed, b.max_run_sec, b.safety = self.speed, self.duration + 60, True
        trapped, near_since, offline_since, forward_since, last_seen = 0, None, None, None, 0.0
        track = []  # (thoi diem, khoang cach) luc dang di thang -> phat hien ket
        reason = "het gio"
        try:
            while self._alive(token):
                now = time.time()
                if now - self.started_at >= self.duration:
                    break
                if not b.online:
                    offline_since, forward_since, track = offline_since or now, None, []
                    self.state = "mat lien lac than, cho..."
                    self._cmd("stop", token)
                    if now - offline_since > 20:
                        reason = "mat lien lac than"
                        self.on_event("lost", "")
                        break
                    time.sleep(0.2)
                    continue
                offline_since = None
                if now - b.last_status > FRESH_SEC:
                    # Chua mat han (2,5 giay) nhung so do da cu: dung cho, dung dung so cu.
                    if self.state != "song yeu, cho tin hieu...":
                        print("[TU DI] tin hieu than tre/lac -> dung cho (song WiFi yeu?)")
                    self.state = "song yeu, cho tin hieu..."
                    self._cmd("stop", token)
                    near_since, track, forward_since = None, [], None
                    time.sleep(TICK)
                    continue

                if self._front_near():
                    near_since = near_since or now
                    # 1 lan do gan le loi (nhieu) thi bo qua; gan lien tuc ~0,1 giay moi tinh
                    if b.blocked or now - near_since >= 0.1:
                        near_since, track, forward_since = None, [], None
                        result = self._avoid(token)
                        if result is None:
                            break
                        if result == "retry":  # mat song giua chung: khong tinh la bi chan
                            continue
                        trapped = trapped + 1 if result == "back" else 0
                        if trapped >= TRAPPED_LIMIT:
                            reason = "bi ket"
                            self.on_event("trapped", "")
                            break
                        continue
                else:
                    near_since = None

                if self._stuck(track, now):
                    print("[TU DI] khoang cach dung yen trong luc chay -> chac bi ket vat thap, lui + quay")
                    self.on_event("stuck", "")
                    track, forward_since = [], None
                    self.avoid_count += 1
                    if not (self._hold("back", BACK_SEC, token)
                            and self._turn(random.choice(("left", "right")), self.turn_sec * 2, token)):
                        break
                    continue

                self.state = "di thang"
                forward_since = forward_since or now
                moving = self._cmd("run", token)
                # Chi ghi so do MOI (goi trang thai moi ve), khong ghi lai so cu khi goi tin lac
                if moving and b.last_status != last_seen and b.dist is not None and b.dist > 0:
                    track.append((b.last_status, b.dist))
                last_seen = b.last_status
                if now - forward_since > 2.0:
                    trapped = 0  # di thang duoc 2 giay -> da thoat khoi cho ket
                time.sleep(TICK)
        finally:
            b.speed = saved[0] if b.speed == self.speed else b.speed  # nguoi da bam E/R thi giu
            b.max_run_sec, b.safety = saved[1], saved[2]
            with self._lock:
                natural = self._alive(token)
                if natural:  # het gio / bi ket: tu tat (stop() tu ngoai thi da tat roi)
                    self._token += 1
                    self.running = False
                    b.stop()
            if natural:
                self.state = ""
                print(f"[TU DI] TAT ({reason}), da ne {self.avoid_count} lan")
                self.on_event("end" if reason == "het gio" else "stop", reason)

    def _stuck(self, track, now):
        while track and now - track[0][0] > STUCK_SEC:
            track.pop(0)
        if not track or now - track[0][0] < STUCK_SEC * 0.9:
            return False
        ds = [d for _, d in track]
        return max(ds) - min(ds) < STUCK_CM and max(ds) < 200

    def _blind(self):
        """Dang nhin trai/phai thi mat song -> khong doan bua. Vong chinh se dung cho song ve
        roi tu kiem tra lai phia truoc."""
        print("[TU DI] dang tim duong thi mat tin hieu than (song yeu) -> dung cho, khong doan")
        self.state = "song yeu, cho tin hieu..."
        return "retry"

    def _avoid(self, token):
        """Tim duong. Tra ve "left"/"right"/"back"/"retry" (mat song), hoac None neu bi tat."""
        self.avoid_count += 1
        self.state = "vat can! nhin trai..."
        self.on_event("scan", "")
        self._cmd("stop", token)
        if not self._turn("left", self.turn_sec, token):
            return None
        left = self._measure(token)
        if left is None:
            return None
        if left == UNKNOWN:
            return self._blind()
        self.state = f"trai {left:.0f}cm, nhin phai..."
        if not self._turn("right", self.turn_sec * 2, token):
            return None
        right = self._measure(token)
        if right is None:
            return None
        if right == UNKNOWN:
            return self._blind()
        print(f"[TU DI] vat can -> trai {left:.0f}cm, phai {right:.0f}cm", end=" ")
        if right >= OPEN_CM and right >= left:
            print("-> di ben PHAI")
            self.state = f"di ben phai ({right:.0f}cm)"
            self.on_event("go", "right")
            return "right"  # dang huong ve ben phai roi, di tiep
        if left >= OPEN_CM:
            print("-> quay lai ben TRAI")
            self.state = f"di ben trai ({left:.0f}cm)"
            self.on_event("go", "left")
            return "left" if self._turn("left", self.turn_sec * 2, token) else None
        print("-> ca 2 ben bi chan, LUI + quay dau")
        self.state = "2 ben bi chan, lui lai"
        self.on_event("back", "")
        if not self._hold("back", BACK_SEC, token):
            return None
        self._cmd("stop", token)
        # dang huong phai ~60 do: xoay phai them ~120 do -> gan nhu quay nguoc huong cu
        return "back" if self._turn("right", self.turn_sec * 2, token) else None
