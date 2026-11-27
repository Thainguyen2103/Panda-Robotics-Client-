"""Brain cua Moon: noi "tai - mat - mieng - banh xe" lai voi nhau va quyet dinh lam gi.

1. HANH DONG THEO CAU TRA LOI: LLM duoc phep them "the lenh" cuoi cau, vd
       "Moon nhay cho be xem nhe! [move:dance] [face:happy]"
   brain cat the lenh ra (loa khong doc), roi lam: doi mat robot, hien tu len man, lai banh xe.
   Khong ton them luot goi API: the lenh di chung cau tra loi.

2. TU CHU DONG (khong can bam SPACE), dua tren camera (model local, khong ton quota):
   - Thay nguoi xuat hien sau mot luc vang -> chao.
   - Co nguoi dung truoc robot ma lau khong ai noi gi -> do 1 tu vung trong kho bai hoc cua
     Ngoc Anh. Lan noi tiep theo cua be, LLM biet minh vua do gi de khen / sua.

An toan: lenh di chuyen chi la cu dong ngan (toi da ~2 giay), chi khi phan than dang noi; firmware
than van tu phanh truoc vat can 12cm, phim / tay cam cua nguoi dieu khien luon duoc uu tien.
Tat: chay "--brain off" hoac bam phim B luc dang chay.
"""
import json
import random
import re
import threading
import time
import unicodedata

# Bieu cam ma firmware head-demo ve duoc (src/face.cpp)
FACES = ("neutral", "happy", "sad", "angry", "surprised", "sleepy", "wink", "love", "cool", "cute",
         "dizzy", "questioning")
# Cu dong: chuoi (che do banh, so giay). Ngan + tu dung -> robot khong chay mat khoi ban.
MOVES = {
    "dance": [("left", 0.4), ("right", 0.4), ("left", 0.4), ("right", 0.4)],
    "spin": [("right", 1.6)],
    "nod": [("run", 0.25), ("back", 0.25), ("run", 0.25), ("back", 0.25)],
    "forward": [("run", 0.8)],
    "back": [("back", 0.8)],
    "left": [("left", 0.5)],
    "right": [("right", 0.5)],
}
TAG_RE = re.compile(r"\[\s*(face|move|word)\s*:\s*([^\]\n]{1,40})\]", re.I)

ACTION_PROMPT = """You have a body. At the very END of your reply you may add up to 2 action tags (they are not spoken):
[face:NAME] change your face. NAME: happy, sad, surprised, love, cool, cute, wink, questioning, dizzy, sleepy, angry, neutral.
[move:NAME] move your wheels briefly. NAME: dance, spin, nod, forward, back, left, right.
[move:explore] wander around the room by yourself for 10 minutes, avoiding obstacles — ONLY when the child asks you
to go explore / wander / drive around by yourself.
[word:ENGLISH|ROMAJI] show a vocabulary word on your screen, e.g. [word:CAT|NEKO].
Faces: use whenever they fit the feeling, e.g. [face:love] when the child says they love you.
Moves: ONLY when the child explicitly asks you to move (dance, spin, come, go, turn...). Your moves are short and safe,
so just do it happily. Never move when not asked.
Words: [word:...] when you teach a word. Never describe the tags in words."""

GREETINGS = [
    "Xin chào bạn nhỏ! Mình là Moon. Hôm nay mình cùng học từ mới nhé!",
    "A, có bạn đến chơi với Moon rồi! Chào bạn nha!",
    "Chào bạn! Moon đang chờ bạn nãy giờ đó. Mình cùng chơi đố chữ nhé!",
]

GREET_AFTER_ABSENT = 60.0  # vang mat >= 60 giay roi quay lai -> chao lai
GREET_COOLDOWN = 120.0
FACE_STABLE = 1.5          # mat phai xuat hien lien tuc 1,5 giay moi tinh (tranh nhan nham)
QUIZ_IDLE = 45.0           # co nguoi ma 45 giay khong ai noi gi -> do 1 cau
QUIZ_EXPIRE = 90.0         # sau 90 giay ma be chua tra loi thi bo cau do


def _ascii(text):
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn" and ord(c) < 128)


def load_quiz_words(path):
    """Lay cac tu don gian trong kho bai hoc (llm/data.json cua Ngoc Anh) de do be."""
    try:
        lessons = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    words = []
    for x in lessons:
        en, vi, ja = str(x.get("en") or ""), str(x.get("vi") or ""), str(x.get("ja") or "")
        romaji = re.search(r"\(([A-Za-z\- ]+)\)", ja)
        if vi and en and len(en.split()) <= 2 and en.replace(" ", "").isalpha():
            words.append({"vi": vi, "en": en, "kana": x.get("ja_kana") or "",
                          "romaji": romaji.group(1) if romaji else ""})
    return words


class Brain:
    def __init__(self, voice, shared, quiz_words=(), proactive=True):
        self.voice, self.shared = voice, shared
        self.quiz_words = list(quiz_words)
        self.proactive = proactive
        self.quiz = None             # {"word":..., "lang": "en"/"ja", "asked": t}
        self.face_since = None       # luc mat bat dau xuat hien lien tuc
        self.face_gone_since = time.time() - GREET_AFTER_ABSENT  # luc khoi dong: coi nhu vang lau
        self.last_greet = 0.0
        self.last_activity = time.time()  # lan cuoi co ai noi / robot noi
        self.greeted = False         # da chao nguoi dang dung truoc robot chua
        self._move_token = 0

    # ---------- 1. ngu canh them cho LLM ----------
    def context(self):
        parts = [ACTION_PROMPT]
        q = self.quiz
        if q and time.time() - q["asked"] < QUIZ_EXPIRE:
            w = q["word"]
            answer = w["en"] if q["lang"] == "en" else f"{w['kana']} ({w['romaji']})"
            parts.append(f"Moon vừa đố bé: \"{q['text']}\" Đáp án đúng: {answer}. Nếu bé đang trả lời câu đố, "
                         "hãy khen nếu đúng (gần đúng do nhận dạng giọng nói cũng tính là đúng), nếu sai thì "
                         "nhẹ nhàng nói đáp án và cho bé đọc theo.")
        return "\n".join(parts)

    def on_heard(self, text):
        """Goi moi khi be noi (sau khi nghe xong): cau do coi nhu da duoc tra loi."""
        self.last_activity = time.time()

    def after_reply(self):
        self.quiz = None  # LLM da xu ly cau tra loi do -> khong nhac lai nua
        self.last_activity = time.time()

    # ---------- 2. thuc hien the lenh trong cau tra loi ----------
    def apply(self, reply):
        """Cat the lenh khoi cau tra loi, thuc hien, tra ve phan chu de loa doc."""
        face = word = move = None
        for kind, value in TAG_RE.findall(reply or ""):
            kind, value = kind.lower(), value.strip()
            if kind == "face" and value.lower() in FACES:
                face = value.lower()
            elif kind == "move" and (value.lower() in MOVES or value.lower() == "explore"):
                move = value.lower()
            elif kind == "word":
                word = " / ".join(_ascii(p).strip().upper() for p in value.split("|") if _ascii(p).strip())[:22]
        clean = TAG_RE.sub("", reply or "")
        clean = re.sub(r"\[[^\]]{0,40}\]", "", clean)  # the la/viet sai -> bo luon, khong doc
        clean = re.sub(r"\s{2,}", " ", clean).strip()
        if word:
            self.voice.caption = word
        if face:
            # Mat tam thoi trong luc robot noi cau nay (uoc ~14 ky tu / giay, toi thieu 3 giay)
            caption = self.voice.caption or "MOON DANG NOI"
            self.voice.flash = (face, caption, time.time() + max(3.0, len(clean) / 14))
        if move:
            self.move(move)
        if face or word or move:
            print(f"[BRAIN] the lenh: face={face} word={word} move={move}")
        return clean

    def move(self, name):
        body = self.voice.body
        if not (body and body.online):
            print(f"[BRAIN] muon {name} nhung chua noi phan than -> bo qua")
            return
        auto = getattr(self.voice, "auto", None)
        if name == "explore":  # di dao 10 phut, tu ne vat can (tools/auto_drive.py)
            if auto:
                why = auto.start()
                if why:
                    print(f"[BRAIN] muon di dao nhung: {why}")
            return
        if auto:
            auto.stop("be nho lam dong tac " + name)  # be nho nhay / quay... -> thoi di dao
        self._move_token += 1
        token = self._move_token
        threading.Thread(target=self._run_move, args=(body, MOVES[name], token), daemon=True).start()

    def _run_move(self, body, steps, token):
        try:
            for mode, sec in steps:
                if token != self._move_token or not body.drive(mode):
                    return
                end = time.time() + sec
                while time.time() < end:
                    # Nguoi dieu khien bam phim / tay cam (doi che do) -> nhuong ngay, khong lai tiep
                    if body.mode != mode or token != self._move_token:
                        return
                    time.sleep(0.03)
        finally:
            if token == self._move_token and body.mode in {m for m, _ in steps}:
                body.stop()

    # ---------- 3. tu chu dong ----------
    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _loop(self):
        while not self.shared.stop:
            time.sleep(0.5)
            try:
                self.tick(time.time())
            except Exception as e:  # brain loi khong duoc lam sap ca chuong trinh
                print("[BRAIN] loi:", repr(e))

    def tick(self, now):
        with self.shared.lock:
            result = self.shared.result
        face = bool(result and result.get("face_detected"))
        if face:
            self.face_since = self.face_since or now
        else:
            if self.face_since is not None:
                self.face_gone_since = now
            self.face_since = None
            if self.face_gone_since and now - self.face_gone_since > GREET_AFTER_ABSENT:
                self.greeted = False
        if not self.proactive or self.voice.state != "ready":
            if self.voice.state != "ready":
                self.last_activity = now
            return
        present = face and now - self.face_since >= FACE_STABLE
        if present and not self.greeted and now - self.last_greet > GREET_COOLDOWN:
            self.greeted, self.last_greet = True, now
            self._say(random.choice(GREETINGS), "happy", "XIN CHAO!")
        elif present and self.quiz_words and now - self.last_activity > QUIZ_IDLE:
            self._ask_quiz(now)

    def _ask_quiz(self, now):
        w = random.choice(self.quiz_words)
        lang = "ja" if w["kana"] and w["romaji"] and random.random() < 0.5 else "en"
        hands_free = getattr(self.voice, "auto_listening", lambda: False)()
        text = (f"Đố bé nè: {w['vi']} tiếng {'Nhật' if lang == 'ja' else 'Anh'} là gì? "
                + ("Bé trả lời Moon đi nào!" if hands_free else "Bé bấm nút rồi trả lời Moon nhé!"))
        self.quiz = {"word": w, "lang": lang, "asked": now, "text": text}
        self._say(text, "questioning", "DO BE?")

    def _say(self, text, face, caption):
        if not self.voice.speak_proactive(text, face, caption):
            return
        print(f"[BRAIN] tu noi: {text}")
        self.last_activity = time.time()
