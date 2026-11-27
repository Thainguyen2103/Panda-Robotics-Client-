"""Computer vision qua API (Gemini), TAM THOI cho toi khi Thai/Anh xong model rieng.

2 cach dung (cung tra ve dict giong VisionEngine.process() cua Thai, nen phan con lai cua
head_demo khong can biet anh duoc phan tich o dau):

  look(frame)     -> "hieu" ca canh: may nguoi, cam xuc, do vat, be dang cam/gio gi len,
                     mo ta ngan. Goi KHI CAN (be hoi "day la con gi?", brain can biet xung quanh).
  process(frame)  -> cung ten ham voi VisionEngine cua Thai: dung thay the hoan toan model local
                     (che do --vision api). Ben trong goi look() nhung toi da 1 lan / INTERVAL giay.

Vi sao KHONG goi API cho tung khung hinh: camera 13 hinh/giay, ban mien phi chi ~15 lan/phut va
~500 lan/ngay moi model -> goi lien tuc thi het quota trong vai phut. Nhan dien mat + cam xuc
theo thoi gian thuc nen de model local (nhanh, mien phi, anh khong ra khoi laptop).

Luu y rieng tu: ban mien phi, Google DUOC dung du lieu gui len de cai thien san pham. Anh
camera co mat tre em -> chay "--vision-cloud off" de khong bao gio gui anh len mang.

Thay bang model cua Thai/Anh sau nay: chi can 1 class co process(frame) tra ve dict co cac
khoa face_detected / emotion / emotion_scores / face_box (+ objects, holding, scene neu co).
"""
import base64
import json
import re
import threading
import time

import cv2
import requests

# Model nao nhin anh: thu tu uu tien, het quota/qua tai thi sang cai sau (nhu llm_online.py).
# Thu 2026-11: 3.5 Flash-Lite ~1,5-2,3 giay/anh; 3.1 dung duoc nhung co luc cham 10-25 giay.
VISION_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
EMOTIONS = ("neutral", "happy", "surprised", "sad", "angry", "disgust", "fear", "contempt")
INTERVAL = 15.0      # che do --vision api: toi da 1 lan goi / 15 giay (~240 lan / 1 tieng chay)
MAX_SIDE = 640       # thu nho anh truoc khi gui: Gemini tinh phi anh theo o 768px, to hon vo ich
COOLDOWN_BUSY, COOLDOWN_ERROR = 60, 15

PROMPT = """You are the eyes of Moon, a small robot that teaches English and Japanese words to young children.
Look at this camera image and answer ONLY with JSON:
{
 "people": number of people visible,
 "face_box": [ymin, xmin, ymax, xmax] of the largest / closest human face, values 0-1000, or null if no face,
 "emotion": emotion of that face, exactly one of: neutral, happy, surprised, sad, angry, disgust, fear, contempt, unknown,
 "emotion_confidence": 0.0-1.0,
 "holding": the main thing a person is holding up or showing to the camera (a toy, a fruit, a picture, a card...), or null,
 "objects": up to 5 clearly visible things (not people), most noticeable first,
 "scene": one short Vietnamese sentence describing what Moon sees, for a child
}
Every thing (holding and each object) is {"en": English word, "vi": Vietnamese word, "ja": Japanese word in kana}.
If the thing is a picture or drawing of something, name what it shows (a picture of a cat -> cat).
Use simple everyday words a child learns. If unsure, leave it out instead of guessing."""

# JSON schema: bat Gemini tra dung khuon (khong lan chu thua ngoai JSON)
_THING = {"type": "OBJECT", "properties": {"en": {"type": "STRING"}, "vi": {"type": "STRING"},
                                          "ja": {"type": "STRING"}}, "required": ["en", "vi"]}
SCHEMA = {"type": "OBJECT", "properties": {
    "people": {"type": "INTEGER"},
    "face_box": {"type": "ARRAY", "items": {"type": "NUMBER"}, "nullable": True},
    "emotion": {"type": "STRING", "enum": list(EMOTIONS) + ["unknown"]},
    "emotion_confidence": {"type": "NUMBER"},
    "holding": dict(_THING, nullable=True),
    "objects": {"type": "ARRAY", "items": _THING},
    "scene": {"type": "STRING"},
}, "required": ["people", "emotion", "objects", "scene"]}


def _jpeg(frame):
    h, w = frame.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("khong nen duoc anh JPEG")
    return base64.b64encode(buf.tobytes()).decode()


def _parse_json(text):
    """Gemini (co schema) tra JSON sach; Gemma khong ho tro schema -> boc phan {...} ra."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError(f"khong co JSON trong: {text[:80]!r}")
        return json.loads(m.group(0))


class ApiVision:
    def __init__(self, api_key, models=None, interval=INTERVAL, session=None):
        self.key = api_key
        self.models = list(models or VISION_MODELS)
        self.interval = interval
        self.session = session or requests.Session()
        self.resting = {}
        self.last_model = None
        self.models_ready = {"face": True, "emotion": True}  # cho dong "Mo hinh ... da nap"
        self._last = None               # ket qua look() gan nhat
        self._last_time = 0.0
        self._lock = threading.Lock()

    # ---------- goi API ----------
    def _call(self, model, image_b64):
        body = {"contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
            {"text": PROMPT}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}}
        if model.startswith("gemini"):  # Gemma chua ho tro JSON schema
            body["generationConfig"].update(responseMimeType="application/json", responseSchema=SCHEMA)
        r = self.session.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            # cho toi da 12 giay: be dang doi cau tra loi, model cham thi bo sang model khac
            headers={"x-goog-api-key": self.key}, json=body, timeout=(6, 12))
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {r.text[:150]}")
        parts = r.json()["candidates"][0]["content"]["parts"]
        return _parse_json("".join(p.get("text", "") for p in parts if not p.get("thought")))

    def look(self, frame):
        """Phan tich 1 anh. Tra ve dict (xem _to_result) hoac None neu moi model deu loi."""
        image = _jpeg(frame)
        h, w = frame.shape[:2]
        for model in self.models:
            if time.time() < self.resting.get(model, 0):
                continue
            t0 = time.time()
            try:
                raw = self._call(model, image)
            except Exception as e:
                msg = str(e)
                busy = any(c in msg for c in ("429", "503", "RESOURCE_EXHAUSTED", "quota", "Unavailable"))
                self.resting[model] = time.time() + (COOLDOWN_BUSY if busy else COOLDOWN_ERROR)
                print(f"[MAT] {model} loi ({'het quota/qua tai' if busy else msg[:90]}) -> thu cai tiep theo")
                continue
            self.last_model = model
            result = _to_result(raw, w, h)
            result["inference_ms"] = round((time.time() - t0) * 1000)
            result["vision_model"] = model
            with self._lock:
                self._last, self._last_time = result, time.time()
            return result
        return None

    def latest(self, max_age=None):
        """Ket qua look() gan nhat (None neu cu hon max_age giay)."""
        with self._lock:
            if self._last is None or (max_age is not None and time.time() - self._last_time > max_age):
                return None
            return self._last

    # ---------- thay the VisionEngine cua Thai ----------
    def process(self, frame):
        """Cung giao dien VisionEngine.process(): goi API toi da 1 lan / interval giay,
        giua cac lan tra lai ket qua cu (mat robot doi cham hon model local, nhung khong ton quota)."""
        if time.time() - self._last_time >= self.interval:
            self._last_time = time.time()  # dat truoc: loi thi cung cho het interval moi thu lai
            self.look(frame)
        return self.latest() or {"face_detected": False, "emotion": "unknown", "emotion_scores": {},
                                 "face_box": None, "people": 0, "objects": [], "holding": None, "scene": ""}

    def close(self):
        self.session.close()


def _thing(x):
    if not isinstance(x, dict) or not str(x.get("en") or "").strip():
        return None
    return {k: str(x.get(k) or "").strip() for k in ("en", "vi", "ja")}


def _to_result(raw, w, h):
    """JSON cua Gemini -> dict cung khoa voi VisionEngine cua Thai (+ vai khoa moi)."""
    box = raw.get("face_box")
    face_box = None
    if isinstance(box, list) and len(box) == 4:
        ymin, xmin, ymax, xmax = (max(0.0, min(1000.0, float(v))) for v in box)
        if ymax > ymin and xmax > xmin:  # Gemini dung toa do 0-1000 -> doi ra pixel [x, y, rong, cao]
            face_box = [xmin * w / 1000, ymin * h / 1000, (xmax - xmin) * w / 1000, (ymax - ymin) * h / 1000]
    emotion = raw.get("emotion") if raw.get("emotion") in EMOTIONS else "unknown"
    conf = float(raw.get("emotion_confidence") or 0.0)
    objects = [t for t in (_thing(o) for o in raw.get("objects") or []) if t][:5]
    return {
        "face_detected": face_box is not None,
        "face_box": face_box,
        "emotion": emotion if face_box else "unknown",
        "emotion_confidence": conf,
        "emotion_scores": {emotion: conf} if face_box and emotion != "unknown" else {},
        "people": int(raw.get("people") or 0),
        "holding": _thing(raw.get("holding")),
        "objects": objects,
        "scene": str(raw.get("scene") or "").strip(),
    }


def describe(result):
    """Doi ket qua look() thanh 1 doan chu cho LLM doc (bom vao prompt khi be hoi ve thu nhin thay)."""
    if not result:
        return ""
    parts = [f"Camera của Moon đang thấy: {result['scene']}" if result.get("scene") else "Camera của Moon:"]
    if result.get("people"):
        parts.append(f"Có {result['people']} người.")
    if result.get("holding"):
        t = result["holding"]
        parts.append(f"Bé đang cầm/giơ lên: {t['vi']} (tiếng Anh: {t['en']}, tiếng Nhật: {t.get('ja') or '?'}).")
    if result.get("objects"):
        parts.append("Đồ vật xung quanh: " + ", ".join(f"{t['vi']} ({t['en']})" for t in result["objects"]) + ".")
    if result.get("face_detected") and result.get("emotion") != "unknown":
        parts.append(f"Nét mặt bé: {result['emotion']}.")
    return " ".join(parts)
