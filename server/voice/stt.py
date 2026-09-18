"""
stt.py — Speech-to-Text via Groq Whisper
==========================================
Gửi audio bytes lên Groq Whisper → nhận transcript text.

Tính năng:
  - Chống hallucination (blacklist + regex + ký tự lạ)
  - Nhận diện wake-word "Panda" (phonetic, không phụ thuộc dấu)
  - Dual-pass (vi + en song song) để tối đa khả năng bắt wake word
  - temperature=0.0 — không dùng fallback ladder (gây hallucination)
"""

import os
import re
import sys
import time
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings
from server.voice.vad import wrap_wav

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
GROQ_API_KEY      = getattr(settings, "GROQ_API_KEY",      None)
STT_MODEL         = getattr(settings, "STT_MODEL",         "whisper-large-v3-turbo")
STT_MODEL_QUESTION= getattr(settings, "STT_MODEL_QUESTION","whisper-large-v3")
STT_LANGUAGE      = getattr(settings, "STT_LANGUAGE",      "vi")   # Tránh auto-detect để giảm hallucination
WAKE_STT_PROMPT   = getattr(settings, "WAKE_STT_PROMPT",   "Đây là hội thoại có các từ: Panda, SQL, Java, Swing, AI, RAG, Python, API, Thắng, Ánh, Nanh.")

WAKE_WORDS = sorted(
    getattr(settings, "PANDA_WAKE_WORDS", ["panda"]),
    key=len, reverse=True,
)

# ─── Groq client ──────────────────────────────────────────────────────────────
groq_client = None
try:
    from groq import Groq
    if GROQ_API_KEY:
        groq_client = Groq(api_key=GROQ_API_KEY)
        print(f"✅ [STT] Groq sẵn sàng. STT model: {STT_MODEL}")
    else:
        print("⚠️  [STT] Chưa có GROQ_API_KEY trong settings.py.")
except ImportError:
    print("⚠️  [STT] groq chưa cài. pip install groq")
except Exception as e:
    print(f"❌ [STT] Lỗi khởi tạo Groq: {e}")

_wake_exec = ThreadPoolExecutor(max_workers=2)


# ══════════════════════════════════════════════════════════════════════════════
#  CHUẨN HÓA VĂN BẢN
# ══════════════════════════════════════════════════════════════════════════════

def strip_diacritics(s: str) -> str:
    """lower + bỏ dấu thanh + đ→d + nén khoảng trắng."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ══════════════════════════════════════════════════════════════════════════════
#  WAKE-WORD DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# Biến thể Whisper hay sinh ra cho "Panda" (đo thực tế)
_EXTRA_WAKE_VARIANTS = [
    "bạn nàng", "ban nang", "bạn nàng ơi",
    "pang da", "pang đa",
]

WAKE_WORDS_NORM = sorted(
    {strip_diacritics(w) for w in WAKE_WORDS}
    | {strip_diacritics(w) for w in _EXTRA_WAKE_VARIANTS},
    key=len, reverse=True,
)


def _levenshtein(a: str, b: str) -> int:
    """Khoảng cách Levenshtein giữa 2 chuỗi ngắn."""
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def contains_wake_word(text: str) -> bool:
    """
    True nếu transcript chứa wake-word "Panda" hoặc biến thể phonetic.
    Không phụ thuộc dấu thanh hay hoa/thường.
    """
    if not text:
        return False
    norm = strip_diacritics(text)
    if any(wake in norm for wake in WAKE_WORDS_NORM):
        return True
    # Fuzzy: "Anna", "Amanda", "panna"... → cách "panda" ≤ 2 phép sửa
    return any(len(tok) >= 4 and _levenshtein(tok, "panda") <= 2
               for tok in norm.split())


# ══════════════════════════════════════════════════════════════════════════════
#  CHỐNG HALLUCINATION
# ══════════════════════════════════════════════════════════════════════════════

_HALLUCINATION_BLACKLIST = {
    "hello", "hello.", "hi", "hey", "you", "you.", "thank you", "thanks",
    "thank you for watching", "thanks for watching", "subscribe",
    "like and subscribe", "please subscribe", "see you next time",
    "bye", "goodbye", "vâng", "dạ", "ừ", "oh", "uh", "hmm", "the", "a",
    "subtitles by", "amara.org",
    "okay", "ok", "okay.", "i know", "okay, i know", "you know", "i see",
    "oh well", "right", "yes", "no", "good", "really", "really?",
}

_HALLUCINATION_TOKENS = (
    "subscribe", "subtitles by", "amara.org", "thank you for watching",
    "thanks for watching", "like and subscribe", "see you next time",
    "đăng ký kênh", "cho kênh", "kênh ghiền",
    "theo dõi", "hẹn gặp lại", "ủng hộ kênh", "cảm ơn các bạn",
)

# Chữ Nhật/Trung/Cyrillic/Ả Rập/Hàn — chắc chắn là hallucination
_NON_LATIN_RE = re.compile(
    r"[\u3040-\u30ff\u4e00-\u9fff\u0400-\u04ff\u0600-\u06ff\uac00-\ud7af]"
)


def is_hallucination(text: str) -> bool:
    """True nếu transcript có dấu hiệu bịa đặt của Whisper."""
    if not text:
        return True
    t = text.strip()
    if len(t) <= 2:
        return True
    low = t.lower()
    if low.strip(".!? ") in _HALLUCINATION_BLACKLIST:
        return True
    if any(tok in low for tok in _HALLUCINATION_TOKENS):
        return True
    if _NON_LATIN_RE.search(t):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  TRANSCRIBE
# ══════════════════════════════════════════════════════════════════════════════

_UNSET = object()


def transcribe_bytes(
    data: bytes,
    filename: str = "clip.wav",
    language=_UNSET,
    prompt: str = None,
    model: str = None,
) -> str:
    """
    Gửi audio bytes (WAV / WebM / MP3) lên Groq Whisper.
    temperature=0.0 — không hallucinate.
    """
    if not groq_client or not data:
        return ""

    t0 = time.time()
    tmp_path = None
    try:
        suffix = os.path.splitext(filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        kwargs = {
            "model": model or STT_MODEL,
            "file": (filename, open(tmp_path, "rb")),
            "temperature": 0.0,
            "response_format": "text",
        }
        lang = STT_LANGUAGE if language is _UNSET else language
        if lang:
            kwargs["language"] = lang
        if prompt:
            kwargs["prompt"] = prompt

        text = groq_client.audio.transcriptions.create(**kwargs)
        if hasattr(text, "text"):
            text = text.text
        text = (text or "").strip()

        if text:
            print(f"📝 [STT] ({time.time()-t0:.2f}s): \"{text}\"")
        return text

    except Exception as e:
        print(f"❌ [STT] Lỗi Groq: {e}")
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def transcribe_pcm(pcm: bytes, model: str = None) -> str:
    """PCM int16 16kHz mono → WAV → Groq (1 pass, theo STT_LANGUAGE)."""
    if not pcm:
        return ""
    return transcribe_bytes(wrap_wav(pcm), "clip.wav", model=model)


def transcribe_dual(pcm: bytes) -> str:
    """
    2 pass song song (vi + en) để tối đa khả năng bắt wake-word.
    Lazy: pass vi trước, bắt được wake → trả ngay (1 call).
    Chỉ khi hụt mới chạy en + vi+prompt song song.
    """
    wav = wrap_wav(pcm)
    t_vi = transcribe_bytes(wav, "clip_vi.wav", "vi")
    if contains_wake_word(t_vi):
        return t_vi

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_en = ex.submit(transcribe_bytes, wav, "clip_en.wav", "en")
        f_vp = ex.submit(transcribe_bytes, wav, "clip_vp.wav", "vi", WAKE_STT_PROMPT)
        t_en = f_en.result()
        t_vp = f_vp.result()

    for t in (t_vp, t_en):
        if contains_wake_word(t):
            print(f"🌐 [STT] Wake từ pass dự phòng: \"{t}\"")
            return t
    return t_vi or t_vp or t_en
