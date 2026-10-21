"""
LLM (Large Language Model) module
===================================
Mặc định dùng Qwen local qua Ollama; có thể bổ sung ngữ cảnh từ kho bài học RAG.

Setup:
    pip install openai groq

    Đặt vào config/settings.py:
        # Option A — DeepSeek API (recommend 🇨🇳)
        DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxx"
        GROQ_LLM_MODEL   = "deepseek-chat"          # hoặc "deepseek-reasoner"

        # Option B — Groq free (fallback)
        GROQ_API_KEY     = "gsk_xxxxxxxxxxxxxxxx"
        GROQ_LLM_MODEL   = "deepseek-r1-distill-llama-70b"  # hoặc "qwen-qwq-32b"

Lấy DeepSeek key tại: https://platform.deepseek.com/api_keys
Lấy Groq key tại:     https://console.groq.com/keys
"""

import os
import sys
import time
import threading
import uuid
import unicodedata
from datetime import datetime

from server.llm.language import (
    language_failure_message,
    normalize_user_question,
    response_language,
    response_language_instruction,
    response_language_matches,
    strict_retry_instruction,
)
from server.llm.brain_router import (
    Intent, IntentDecision, IntentRouter, PROMPT_OVERRIDES,
    is_study_help_query, STUDY_HELP_RESPONSE,
    set_study_help_state, get_study_help_state, clear_study_help_state,
    get_fast_chitchat,
)

# Fix Windows terminal encoding (giống brain.py) — tránh crash khi in emoji/Việt
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Cấu hình từ settings ─────────────────────────────────────────────────────
try:
    from config import settings
    DEEPSEEK_API_KEY = getattr(settings, "DEEPSEEK_API_KEY", None)
    GROQ_API_KEY     = getattr(settings, "GROQ_API_KEY", None)
    GEMINI_API_KEY   = getattr(settings, "GEMINI_API_KEY", None)
    GROQ_LLM_MODEL   = getattr(settings, "GROQ_LLM_MODEL", "deepseek-r1-distill-llama-70b")
    GEMINI_LLM_MODEL = getattr(settings, "GEMINI_LLM_MODEL", "gemini-3.5-flash-lite")
    OLLAMA_HOST       = getattr(settings, "OLLAMA_HOST", "http://127.0.0.1:11434")
    OLLAMA_LLM_MODEL  = getattr(settings, "OLLAMA_LLM_MODEL", "moon-tutor")
    OLLAMA_MAX_TOKENS = getattr(settings, "OLLAMA_MAX_TOKENS", 150)
    LLM_PROVIDER     = getattr(settings, "LLM_PROVIDER", "ollama")
    LEARNING_RAG_ENABLED = getattr(settings, "LEARNING_RAG_ENABLED", True)
    QUICK_MODEL      = getattr(settings, "QUICK_MODEL", GROQ_LLM_MODEL)
except Exception:
    DEEPSEEK_API_KEY = None
    GROQ_API_KEY     = None
    GEMINI_API_KEY   = None
    GROQ_LLM_MODEL   = "deepseek-r1-distill-llama-70b"
    GEMINI_LLM_MODEL = "gemini-3.5-flash-lite"
    OLLAMA_HOST = "http://127.0.0.1:11434"
    OLLAMA_LLM_MODEL = "moon-tutor"
    OLLAMA_MAX_TOKENS = 150
    LLM_PROVIDER     = "ollama"
    LEARNING_RAG_ENABLED = True
    QUICK_MODEL      = "openai/gpt-oss-120b"

# ─── Xác định model và client sẽ dùng ────────────────────────────────────────
_client      = None
_model_name  = None
_is_deepseek = False   # True = dùng DeepSeek API trực tiếp
_provider_name = None

def _init_client():
    """Khởi tạo LLM chính; provider ``ollama`` không dùng API LLM dự phòng."""
    global _client, _model_name, _is_deepseek, _provider_name

    _client = None
    _model_name = None
    _is_deepseek = False
    _provider_name = None

    requested = str(LLM_PROVIDER or "auto").strip().lower()
    allowed = {"auto", "ollama", "deepseek", "gemini", "groq"}
    if requested not in allowed:
        print(f"⚠️ [LLM] MOON_LLM_PROVIDER={requested!r} không hợp lệ; dùng auto.")
        requested = "auto"

    # ── Option A: Qwen local qua Ollama ───────────────────────────────────────
    if requested in {"auto", "ollama"}:
        try:
            from server.llm_providers.ollama import OllamaTextClient
            ollama_client = OllamaTextClient(OLLAMA_LLM_MODEL, OLLAMA_HOST)
            ollama_client.ensure_ready()
            _client = ollama_client
            _model_name = OLLAMA_LLM_MODEL
            _provider_name = "ollama"
            print(f"✅ [LLM] Ollama sẵn sàng. Model: {_model_name}")

            return
        except Exception as e:
            print(f"⚠️ [LLM] Ollama chưa sẵn sàng: {e}")

    # ── Option B: DeepSeek API (openai-compatible) ────────────────────────────
    if requested in {"auto", "deepseek"} and DEEPSEEK_API_KEY:
        try:
            from openai import OpenAI
            _client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )
            # Chọn model: "deepseek-reasoner" nếu config yêu cầu, còn lại dùng "deepseek-chat"
            _model_name  = GROQ_LLM_MODEL if "reasoner" in GROQ_LLM_MODEL else "deepseek-chat"
            _is_deepseek = True
            _provider_name = "deepseek"
            print(f"✅ [LLM] DeepSeek API sẵn sàng. Model: {_model_name}")
            return
        except ImportError:
            print("⚠️ [LLM] openai chưa cài. Chạy: pip install openai")
        except Exception as e:
            print(f"⚠️ [LLM] Lỗi DeepSeek: {e}")

    # ── Option C: Gemini text generation khi được chọn rõ ràng hoặc dùng auto ─
    # Provider mặc định là Ollama, nên Gemini API key vẫn chỉ phục vụ STT.
    if requested in {"auto", "gemini"} and GEMINI_API_KEY:
        try:
            from server.llm_providers.gemini import GeminiTextClient
            _client = GeminiTextClient(GEMINI_API_KEY, GEMINI_LLM_MODEL)
            _model_name = GEMINI_LLM_MODEL
            _is_deepseek = False
            _provider_name = "gemini"
            print(f"✅ [LLM] Gemini sẵn sàng. Model: {_model_name}")
            return
        except Exception as e:
            print(f"⚠️ [LLM] Lỗi Gemini: {e}")

    # ── Option D: Groq ────────────────────────────────────────────────────────
    if requested in {"auto", "groq"} and GROQ_API_KEY:
        try:
            from groq import Groq
            _client     = Groq(api_key=GROQ_API_KEY)
            _model_name = GROQ_LLM_MODEL
            _is_deepseek = False
            _provider_name = "groq"
            print(f"✅ [LLM] Groq LLM sẵn sàng. Model: {_model_name}")
            return
        except ImportError:
            print("⚠️ [LLM] groq chưa cài. Chạy: pip install groq")
        except Exception as e:
            print(f"⚠️ [LLM] Lỗi Groq: {e}")

    print("❌ [LLM] Không có LLM client khả dụng. Kiểm tra Ollama hoặc cấu hình provider.")

_init_client()

# ─── Kho bài học RAG của nhóm LLM ───────────────────────────────────────────
_retrieve_learning_context = None
_get_learning_display_info = None
_retrieve_learning_record = None
_format_learning_record = None
_is_out_of_scope_intent = lambda _question: False
if LEARNING_RAG_ENABLED:
    try:
        from server.llm.rag_engine import retrieve_context as _retrieve_learning_context
        from server.llm.rag_engine import get_display_info as _get_learning_display_info
        from server.llm.rag_engine import get_learning_record as _retrieve_learning_record
        from server.llm.rag_engine import is_out_of_scope_intent as _is_out_of_scope_intent
        from server.llm.rag_engine import _get_rag as _get_learning_rag
        _format_learning_record = _get_learning_rag().format_context_for_prompt
    except Exception as e:
        print(f"⚠️ [RAG] Không thể nạp kho bài học: {e}")


_LEARNING_INTENT_MARKERS = (
    "tiếng nhật", "tiếng anh", "học từ", "dạy", "chỉ cho", "từ gì",
    "đọc", "viết", "nghĩa", "phát âm", "chữ hán", "hiragana", "romaji",
    "đố", "con gì", "cái gì", "thứ gì", "loài nào",
    "japanese", "english word", "teach", "learn", "pronounce", "meaning",
    "how do you say", "how is", "quiz", "what animal", "which animal",
    "日本語", "英語", "漢字", "ひらがな", "ローマ字", "読み", "読ん", "書き",
    "意味", "教えて", "クイズ", "何の動物", "どの動物",
)


def has_learning_intent(question: str) -> bool:
    normalized = unicodedata.normalize("NFC", question or "").casefold()
    return any(marker in normalized for marker in _LEARNING_INTENT_MARKERS)


def learning_context(question: str, *, force: bool = False) -> str:
    """Return verified lesson context without making the whole LLM depend on RAG."""
    if not _retrieve_learning_context or not force:
        return ""
    try:
        # Một bài liên quan là đủ cho model local và giảm đáng kể thời gian
        # xử lý prompt so với việc bơm hai bài dài vào mỗi lượt.
        return _retrieve_learning_context(question, top_k=1)
    except Exception as e:
        print(f"⚠️ [RAG] Truy xuất bài học lỗi: {e}")
        return ""


def learning_display_info(question: str) -> dict | None:
    """Expose the best lesson fields for OLED/LED integrations."""
    if not _get_learning_display_info:
        return None
    try:
        return _get_learning_display_info(question)
    except Exception as e:
        print(f"⚠️ [RAG] Lấy dữ liệu màn hình lỗi: {e}")
        return None


def learning_record(question: str) -> dict | None:
    if not _retrieve_learning_record:
        return None
    try:
        return _retrieve_learning_record(question)
    except Exception as exc:
        print(f"⚠️ [RAG] Lấy bản ghi bài học lỗi: {exc}")
        return None


_VOCAB_LOOKUP_MARKERS = (
    "tiếng nhật", "tiếng anh", "tiếng việt", "đọc thế nào", "đọc là gì", "viết thế nào", "nghĩa là gì",
    "chữ hán", "hán tự", "kanji", "hiragana", "romaji",
    "how do you say", "in japanese", "in english", "in vietnamese", "how is", "pronounce", "written in",
    "日本語", "英語", "読み", "読ん", "書き", "漢字", "ひらがな", "ローマ字", "意味",
)

_TIME_QUERY_MARKERS = (
    "mấy giờ", "bao nhiêu giờ", "giờ hiện tại", "bây giờ là mấy giờ",
    "hôm nay ngày", "ngày bao nhiêu", "thứ mấy",
    "what time", "current time", "time is it", "what date", "what day is it",
    "today's date", "何時", "いま何時", "今何時", "今日は何日", "何曜日", "今日の日付",
)


def realtime_answer(question: str) -> str | None:
    """Return exact local time without spending an LLM inference round."""
    normalized = unicodedata.normalize("NFC", question or "").casefold()
    if not any(marker in normalized for marker in _TIME_QUERY_MARKERS):
        return None

    now = datetime.now()
    language = response_language(question)
    if language == "ja":
        weekdays = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
        return (
            f"現在は{now.hour:02d}時{now.minute:02d}分、{now.year}年{now.month}月{now.day}日"
            f"（{weekdays[now.weekday()]}）です。"
        )
    if language == "en":
        weekdays = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        ]
        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        return (
            f"It is {now:%H:%M} on {weekdays[now.weekday()]}, "
            f"{months[now.month - 1]} {now.day}, {now.year}."
        )
    return f"Bây giờ là {now:%H:%M}, {_WEEKDAYS[now.weekday()]} ngày {now:%d/%m/%Y}."


from server.llm.dictionary_router import get_entertainment, get_role_play
from server.llm.pedagogy import (
    fast_pedagogical_correction,
    detect_pedagogical_context,
    is_role_play_request,
    is_role_play_exit,
    format_role_play_system_instruction,
    format_pedagogical_error_instruction,
)
from functools import lru_cache

def grounded_learning_answer(question: str, lesson_info: dict | None = None) -> str | None:
    """Answer direct vocabulary lookups instantly via Hash Map / RAG display info.
    Bỏ qua LLM nặng nề, trả về đáp án ngay lập tức từ data.json.
    """
    normalized = unicodedata.normalize("NFC", question or "").casefold()
    if not any(marker in normalized for marker in _VOCAB_LOOKUP_MARKERS):
        return None

    info = lesson_info or learning_display_info(question)
    if not info:
        return None

    kanji = str(info.get("ja_kanji") or info.get("kanji") or "").strip()
    hiragana = str(info.get("ja_kana") or info.get("japanese_hiragana") or info.get("hiragana") or "").strip()
    ja = str(info.get("ja") or "").strip()
    english = str(info.get("en") or info.get("english") or "").strip()
    vietnamese = str(info.get("vi") or info.get("vietnamese") or "").strip()

    if not (vietnamese and english and (kanji or hiragana)):
        return None

    language = response_language(question)
    disp_kanji = kanji or hiragana
    disp_kana = hiragana or kanji
    if language == "ja":
        return (
            f"日本語では「{disp_kanji}（{disp_kana}）」と書きます。英語では「{english}」、"
            f"ベトナム語では「{vietnamese}」です。"
        )
    if language == "en":
        return f"In Japanese, {english} is written {disp_kanji}（{disp_kana}）; in Vietnamese, it means {vietnamese}."
    q_lower = unicodedata.normalize("NFC", question or "").casefold()
    if any(k in q_lower for k in ["tiếng anh", "english", "in english"]):
        return f"Từ {vietnamese} trong tiếng Anh là {english} bé nha!"
    # Mặc định: hỏi tiếng Nhật → tập trung vào Nhật
    if disp_kanji and disp_kanji != disp_kana:
        return f"Từ {vietnamese} trong tiếng Nhật viết là {disp_kanji}（{disp_kana}） bé nha!"
    return f"Từ {vietnamese} trong tiếng Nhật đọc là {disp_kana} bé nha!"


_learning_display_sequence = 0


def publish_learning_display(question: str, info: dict):
    """
    Trích xuất đúng trường dữ liệu theo ngôn ngữ bé hỏi:
    - Tiếng Nhật / Chữ Hán -> lấy ja_kanji (hoặc ja)
    - Tiếng Anh -> lấy en
    - Tiếng Việt -> lấy vi
    Bắn lệnh MQTT lên màn hình OLED/LED của robot.
    """
    if not info:
        return
    try:
        from server.llm.dictionary_router import extract_display_text
        from server.network.mqtt_bridge import publish
        from config import settings
        import json
        import hashlib

        field, display_text = extract_display_text(question, info)
        if not display_text:
            return

        kanji = str(info.get("ja_kanji") or info.get("kanji") or "")
        kana = str(info.get("ja_kana") or info.get("japanese_hiragana") or "")
        romaji = str(info.get("ja_romaji") or info.get("romaji") or info.get("phonetic") or "")
        meaning_vi = str(info.get("vi") or info.get("vietnamese") or "")
        item_id = str(info.get("item_id") or info.get("id") or hashlib.sha256(
            "|".join((kanji, kana, meaning_vi, display_text)).encode("utf-8")
        ).hexdigest()[:16])
        global _learning_display_sequence
        with _history_lock:
            _learning_display_sequence += 1
            display_sequence = _learning_display_sequence
        display = {
            "schema": "moon.learning-display.v1",
            "item_id": item_id,
            "turn_id": str(getattr(_conversation_turn, "turn_id", "") or ""),
            "display_sequence": display_sequence,
            "kanji": kanji,
            "kana": kana,
            "romaji": romaji,
            "meaning_vi": meaning_vi,
            "example": str(info.get("example") or info.get("example_ja") or ""),
            "audio_state": "idle",
            "text": display_text,
        }

        publish(getattr(settings, "TOPIC_LEARNING_DISPLAY", "moon/ai/learning_display"),
                json.dumps(display, ensure_ascii=False))
        # Legacy topic stays plain text for existing firmware and integrations.
        publish("moon/ai/led", display_text)

        # 2. Cập nhật nhãn OLED chủ đề/từ vựng (moon/ai/topic)
        topic_var = getattr(settings, "TOPIC_AI_TOPIC", "moon/ai/topic")
        topic_id = info.get("topic") or "study"
        publish(topic_var, json.dumps({
            "id": topic_id.lower() if isinstance(topic_id, str) else "study",
            "cap": display_text[:12]
        }))
        print(f"📟 [OLED-MQTT] Đã hiển thị [{field}]: \"{display_text}\" lên OLED")
    except Exception as e:
        print(f"⚠️ [MQTT] Không thể bắn display lên OLED: {e}")


# ─── System Prompt — Tính cách Moon (Tối ưu cho model nhỏ 2B-3B) ────────────
# Ràng buộc chặt chẽ: chỉ sử dụng các trường [vi], [ja], [en] trong [LESSON DATA]
SYSTEM_PROMPT = """You are Moon, a kind panda tutor for children.
Reply in the user's language, in at most 2 short spoken sentences.
For lesson questions, use only the single <lesson_data> record supplied by the app. Do not add facts or guess. Always copy ja_kana exactly; show kanji as 漢字（かな）.
If the app provides no lesson record, it handles the refusal; do not answer from memory.
For language practice, encourage gently, give one accurate correction, and briefly explain it.
For role-play, stay in character. Do not turn ordinary conversation into a lesson or invent Vietnamese pronunciations."""


def _unverified_knowledge_response(question: str) -> str:
    """Fail closed for factual questions with no matching lesson record."""
    language = response_language(question)
    if language == "en":
        return "I don't have verified information about that in this version. I'll add it in a future update."
    if language == "ja":
        return "現在のバージョンには確認済みの情報がありません。次のアップデートで追加します。"
    return HARDCODED_FALLBACK_MSG


HARDCODED_FALLBACK_MSG = (
    "Robot chưa có thông tin đã kiểm chứng về nội dung này trong phiên bản hiện tại. "
    "Robot sẽ cập nhật sau nhé!"
)


def _grounded_lesson_template(question: str, lesson: dict) -> str:
    """Deterministic verbalizer used when the small model omits lesson evidence."""
    vi = str(lesson.get("vi") or lesson.get("vietnamese") or lesson.get("meaning_vi") or "").strip()
    en = str(lesson.get("en") or lesson.get("english") or "").strip()
    kanji = str(lesson.get("ja_kanji") or lesson.get("kanji") or "").strip()
    kana = str(lesson.get("ja_kana") or lesson.get("japanese_hiragana") or "").strip()
    romaji = str(lesson.get("phonetic") or lesson.get("romaji") or "").strip()
    japanese = f"{kanji}（{kana}）" if kanji and kana and kanji != kana else (kana or kanji)
    lang = response_language(question)
    if lang == "en":
        response = f"In Japanese, {vi or en} is {japanese} ({romaji}). It means {en or vi}."
    elif lang == "ja":
        response = f"「{vi or en}」は日本語で「{japanese}」（{romaji}）です。英語では「{en}」です。"
    else:
        response = f"Từ “{vi or en}” trong tiếng Nhật là {japanese}"
        if romaji:
            response += f", đọc là {romaji}"
        if en:
            response += f"; tiếng Anh là “{en}”"
        response += "."
    related = lesson.get("related_terms") or []
    if related and lang == "vi":
        first = related[0]
        alt = str(first.get("ja") or "").strip()
        note = str(first.get("meaning_vi") or "").strip()
        if alt and note:
            response += f" Lưu ý: {alt} là từ liên quan, không phải cách đọc của {kanji or kana}."
    return response


def _guard_lesson_answer(answer: str, question: str, lesson: dict) -> str:
    """Replace an ungrounded/reading-omitting small-model answer with data template."""
    kana = str(lesson.get("ja_kana") or lesson.get("japanese_hiragana") or "").strip()
    if not answer.strip() or (kana and kana not in answer):
        return _grounded_lesson_template(question, lesson)
    return answer

# ─── Ngữ cảnh thời gian thực (để LLM biết "thế giới thật") ───────────────────
# Giống Anki Vector: LLM không tự biết giờ/thời tiết — phải CẤP cho nó.
_WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _current_context() -> str:
    """Bơm đồng hồ thật vào prompt mỗi lần hỏi."""
    now = datetime.now()
    return (f"[Thông tin thực tế] Bây giờ là {now:%H:%M}, "
            f"{_WEEKDAYS[now.weekday()]} {now:%d/%m/%Y}.")


_WX_CODES = {
    0: "trời quang", 1: "gần quang", 2: "có mây", 3: "nhiều mây",
    45: "sương mù", 48: "sương mù đóng băng",
    51: "mưa phùn nhẹ", 53: "mưa phùn", 55: "mưa phùn dày",
    61: "mưa nhỏ", 63: "mưa vừa", 65: "mưa to",
    80: "mưa rào nhẹ", 81: "mưa rào", 82: "mưa rào to",
    95: "dông", 96: "dông kèm mưa đá", 99: "dông kèm mưa đá mạnh",
}


def _maybe_weather(question: str) -> str | None:
    """Hỏi thời tiết → gọi open-meteo (miễn phí, không cần API key)."""
    low = question.lower()
    if not any(k in low for k in ["thời tiết", "trời mưa", "trời nắng", "bao nhiêu độ",
                                  "có mưa không", "weather", "temperature"]):
        return None
    try:
        import requests
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": 16.05, "longitude": 108.25,   # Đà Nẵng
                    "current_weather": "true"},
            timeout=6,
        )
        w = r.json()["current_weather"]
        desc = _WX_CODES.get(w.get("weathercode"), "không rõ")
        return (f"Thời tiết Đà Nẵng lúc này: {w['temperature']}°C, {desc}, "
                f"gió {w['windspeed']} km/h.")
    except Exception as e:
        print(f"⚠️ [LLM] Lấy thời tiết lỗi: {e}")
        return None


# ─── Conversation history ─────────────────────────────────────────────────────
_conversation_history: list[dict] = []
_history_lock = threading.Lock()
_conversation_histories: dict[str, list[dict]] = {}
_conversation_context = threading.local()
_conversation_turn = threading.local()
_conversation_store = None
try:
    from server.llm import conversation_store as _conversation_store
except Exception as exc:
    print(f"⚠️ [LLM] Conversation persistence unavailable ({type(exc).__name__}); using session memory only.")
# Bốn lượt gần nhất đủ giữ mạch hội thoại nhưng không làm prompt local tăng dần
# đến mức chậm rõ rệt sau một phút trò chuyện.
MAX_HISTORY = 3

# Trạng thái phiên nhập vai hiện tại (Role-play session)
_active_role_plays: dict[str, dict] = {}

def get_active_role_play() -> dict | None:
    with _history_lock:
        return _active_role_plays.get(getattr(_conversation_context, "conversation_id", "legacy-default"))

def set_active_role_play(scenario: dict | None):
    with _history_lock:
        conversation_id = getattr(_conversation_context, "conversation_id", "legacy-default")
        if scenario is None:
            _active_role_plays.pop(conversation_id, None)
        else:
            _active_role_plays[conversation_id] = scenario


def _get_messages(user_question: str, intent_decision=None, lesson_record: dict | None = None) -> list[dict]:
    conversation_id = getattr(_conversation_context, "conversation_id", "legacy-default")
    with _history_lock:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Câu hỏi giờ/ngày đã có nhánh deterministic. Chỉ bơm thời tiết khi
        # được hỏi để model nhỏ không lặp lại giờ hệ thống trong hội thoại thường.
        wx = _maybe_weather(user_question)
        if wx:
            messages.append({"role": "system", "content": wx})

        # 1. Bơm chỉ thị nhập vai nếu đang trong phiên đóng vai tương tác
        active_role_play = _active_role_plays.get(conversation_id)
        if active_role_play:
            messages.append({
                "role": "system",
                "content": format_role_play_system_instruction(active_role_play),
            })
        else:
            # 2. Bơm chỉ thị sư phạm sửa lỗi nếu phát hiện ngữ cảnh luyện nói ngoại ngữ
            is_ped, _ = detect_pedagogical_context(user_question)
            if is_ped:
                messages.append({
                    "role": "system",
                    "content": format_pedagogical_error_instruction(),
                })

        # 3. Bơm ngữ cảnh hỗ trợ học tập nếu bé vừa chia sẻ trình độ học ở lượt trước
        study_state = get_study_help_state(conversation_id)
        if study_state and study_state.get("waiting_for_level"):
            messages.append({
                "role": "system",
                "content": (
                    "[HỖ TRỢ HỌC TẬP - PHẢN HỒI TRÌNH ĐỘ]: Bé vừa chia sẻ trình độ học hoặc nội dung muốn học "
                    "(tiếng Anh hoặc tiếng Nhật). Hãy khen ngợi bé ấm áp trong 1 câu ngắn, rồi bắt đầu bằng "
                    "1 bài học, từ vựng hoặc câu đố nhỏ phù hợp nhất với trình độ bé vừa nói. Giữ câu trả lời vui tươi, trong 1-2 câu ngắn."
                ),
            })
            clear_study_help_state(conversation_id)

        route = intent_decision or IntentRouter().classify(user_question)
        prompt_override = PROMPT_OVERRIDES.get(route.intent)
        if prompt_override:
            messages.append({"role": "system", "content": prompt_override})

        lesson_context = ""
        if lesson_record is not None and _format_learning_record:
            lesson_context = _format_learning_record([lesson_record])
        elif route.use_rag and route.intent is not Intent.KNOWLEDGE_QNA:
            lesson_context = learning_context(user_question, force=True)
        if lesson_context:
            print("📚 [RAG] Đã thêm bài học xác thực vào prompt.")
            messages.append({
                "role": "system",
                "content": (
                    "[LESSON DATA — USE EXACTLY, DO NOT ALTER]\n"
                    + lesson_context
                ),
            })
        history = [] if lesson_record is not None else _conversation_histories.get(conversation_id, [])
        if _conversation_store:
            try:
                related = _conversation_store.search(conversation_id, user_question, limit=2)
                recent = _conversation_store.recent_turns(conversation_id, limit=MAX_HISTORY)
                selected = []
                seen = set()
                for item in related + recent:
                    marker = (item["role"], item["content"])
                    if marker not in seen:
                        selected.append(item)
                        seen.add(marker)
                history = selected[-MAX_HISTORY * 2:]
            except Exception as exc:
                print(f"⚠️ [LLM] Conversation lookup unavailable ({type(exc).__name__}).")
        messages.extend(history[-MAX_HISTORY * 2:])
        messages.append({"role": "system", "content": response_language_instruction(user_question)})
        messages.append({"role": "user", "content": user_question})
    return messages


def _add_to_history(user_msg: str, assistant_msg: str):
    cancelled = getattr(_conversation_turn, "should_cancel", None)
    if cancelled and cancelled():
        return
    conversation_id = getattr(_conversation_context, "conversation_id", "legacy-default")
    turn_id = getattr(_conversation_turn, "turn_id", None) or uuid.uuid4().hex
    with _history_lock:
        history = _conversation_histories.setdefault(conversation_id, [])
        history.extend([{"role": "user", "content": user_msg},
                        {"role": "assistant", "content": assistant_msg}])
        del history[:-MAX_HISTORY * 2]
        if conversation_id == "legacy-default":
            _conversation_history[:] = history
    if _conversation_store:
        try:
            from server.llm.language import response_language
            _conversation_store.save_turn(conversation_id, turn_id, user_msg, assistant_msg,
                                          response_language(user_msg))
        except Exception as exc:
            print(f"⚠️ [LLM] Conversation save unavailable ({type(exc).__name__}).")


def record_completed_turn(question: str, answer: str, conversation_id: str,
                          turn_id: str | None = None):
    """Persist a trusted deterministic/fast-path answer under the same schema."""
    conversation_id = str(conversation_id or "")[:128]
    if not conversation_id or not question or not answer:
        return
    turn_id = str(turn_id or uuid.uuid4().hex)[:128]
    with _history_lock:
        history = _conversation_histories.setdefault(conversation_id, [])
        history.extend([{"role": "user", "content": question},
                        {"role": "assistant", "content": answer}])
        del history[:-MAX_HISTORY * 2]
    if _conversation_store:
        try:
            from server.llm.language import response_language
            _conversation_store.save_turn(conversation_id, turn_id, question, answer,
                                          response_language(question))
        except Exception as exc:
            print(f"⚠️ [LLM] Conversation save unavailable ({type(exc).__name__}).")


def clear_history(conversation_id: str | None = None):
    with _history_lock:
        if conversation_id is None:
            _conversation_history.clear()
            _conversation_histories.clear()
            _active_role_plays.clear()
        else:
            _conversation_histories.pop(str(conversation_id), None)
            _active_role_plays.pop(str(conversation_id), None)
    if conversation_id is not None and _conversation_store:
        _conversation_store.delete_conversation(str(conversation_id))
    print("🧹 [LLM] Đã xóa lịch sử hội thoại và đặt lại kịch bản nhập vai.")


# ─── DeepSeek reasoning: strip <think>...</think> tags ───────────────────────
import re as _re

def _strip_thinking(text: str) -> str:
    """Bỏ phần <think>...</think> của DeepSeek-R1 trước khi gửi TTS."""
    return _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()


def _stream_provider(client, provider, model, messages, max_tokens, temperature):
    """Normalize native and OpenAI-compatible providers into text chunks."""
    if provider in {"gemini", "ollama"}:
        yield from client.stream_chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if hasattr(delta, "content") and delta.content:
            yield delta.content


def _generate_response(messages: list[dict], max_tokens: int, temperature: float) -> str:
    """Collect one provider response so its language can be checked before TTS."""
    text = "".join(
        _stream_provider(
            _client,
            _provider_name,
            _model_name,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    )
    return _strip_thinking(text)


# ─── Semantic Cache ────────────────────────────────────────────────────────────
_semantic_cache = {}

# ─── Chat function ─────────────────────────────────────────────────────────────
def chat(
    question: str,
    on_thinking: callable = None,
    on_chunk: callable = None,
    on_done: callable = None,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    should_cancel: callable = None,
) -> str:
    """
    Gửi câu hỏi lên LLM và stream response về.

    Args:
        question:     Câu hỏi của người dùng.
        on_thinking:  Callback(stage: str) — "thinking" | "answering"
        on_chunk:     Callback(chunk: str) — mỗi chunk text nhận được.
        on_done:      Callback(full_text: str) — khi hoàn thành.

    Returns:
        Câu trả lời đầy đủ (str).
    """
    _conversation_context.conversation_id = str(
        conversation_id or f"legacy-{os.getpid()}-{threading.get_ident()}"
    )[:128]
    _conversation_turn.turn_id = str(turn_id or uuid.uuid4().hex)[:128]
    _conversation_turn.should_cancel = should_cancel
    if on_thinking:
        on_thinking("thinking")

    model_question = normalize_user_question(question)
    if model_question != question:
        print(f'✍️ [LLM] Hiệu chỉnh chắc chắn: "{question}" → "{model_question}"')

    intent_decision = IntentRouter().classify(model_question)
    print(f"🧭 [BRAIN ROUTER] intent={intent_decision.intent.value} confidence={intent_decision.confidence:.2f}")

    # Reject known out-of-scope factual requests before study-help/chitchat
    # fast paths can turn them into a different answer (e.g. grammar-form C06).
    if _is_out_of_scope_intent(model_question):
        unavailable = HARDCODED_FALLBACK_MSG
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(unavailable)
        _add_to_history(question, unavailable)
        if on_done:
            on_done(unavailable)
        print("🛑 [RAG] Intent ngoài phạm vi; circuit breaker trả fallback cố định.")
        return unavailable

    # A learning/vocabulary question must not be classified as social chat
    # (the phrase "khen bạn" in B05 used to trigger that bypass).
    if (intent_decision.intent is Intent.CHITCHAT
            and has_learning_intent(model_question)):
        intent_decision = IntentDecision(
            Intent.KNOWLEDGE_QNA, 1.0, True, "learning_marker_overrides_chitchat"
        )
        print("🧭 [BRAIN ROUTER] Learning markers override chitchat; use RAG circuit breaker.")

    # 0. Thoát vai nếu bé yêu cầu dừng trò chơi nhập vai
    if get_active_role_play() and is_role_play_exit(model_question):
        with _history_lock:
            _active_role_plays.pop(_conversation_context.conversation_id, None)
        exit_msg = "Cảm ơn bé đã cùng chơi đóng vai với Moon nha! Trò chơi hôm nay vui quá, lần sau chúng mình lại chơi tiếp nhé!"
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(exit_msg)
        _add_to_history(question, exit_msg)
        if on_done:
            on_done(exit_msg)
        return exit_msg

    # 1. Cơ chế phản hồi lỗi sai sư phạm nhanh (Pedagogical Error Correction: Khích lệ -> Sửa chuẩn -> Giải thích)
    fast_ped_answer = fast_pedagogical_correction(model_question)
    if fast_ped_answer:
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(fast_ped_answer)
        _add_to_history(question, fast_ped_answer)
        if on_done:
            on_done(fast_ped_answer)
        print(f'✅ [PEDAGOGY] Sửa lỗi ngữ pháp 3 bước: "{fast_ped_answer[:80]}"')
        return fast_ped_answer

    # 2. Khởi động kịch bản nhập vai (Interactive Role-play Practice)
    if is_role_play_request(model_question):
        scenario = get_role_play(model_question)
        if scenario:
            with _history_lock:
                _active_role_plays[_conversation_context.conversation_id] = scenario
            intro = scenario.get("intro", "")
            first_turn = scenario.get("first_turn", "")
            role_msg = f"{intro} {first_turn}".strip()
            if on_thinking:
                on_thinking("answering")
            if on_chunk:
                on_chunk(role_msg)
            _add_to_history(question, role_msg)
            if on_done:
                on_done(role_msg)
            print(f'✅ [ROLE-PLAY] Bắt đầu kịch bản: "{scenario.get("title")}"')
            return role_msg

    # 1. BỘ NHỚ ĐỆM (SEMANTIC CACHE) - Tránh LLM chạy lại câu cũ
    if (model_question in _semantic_cache
            and intent_decision.intent is not Intent.KNOWLEDGE_QNA):
        cached_ans = _semantic_cache[model_question]
        print(f"⚡ [SEMANTIC CACHE] Lấy từ RAM (0 độ trễ): \"{cached_ans[:50]}...\"")
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(cached_ans)
        _add_to_history(question, cached_ans)
        if on_done:
            on_done(cached_ans)
        return cached_ans

    # 2. Fast Path: Ý định nhờ hỗ trợ học tập (Study Help) -> Phản hồi gợi mở (0ms)
    if is_study_help_query(model_question):
        study_answer = STUDY_HELP_RESPONSE
        set_study_help_state(_conversation_context.conversation_id, {
            "waiting_for_level": True,
            "timestamp": time.time(),
        })
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(study_answer)
        _add_to_history(question, study_answer)
        if on_done:
            on_done(study_answer)
        print(f'✅ [STUDY HELP] Phản hồi gợi mở định tuyến: "{study_answer[:80]}"')
        return study_answer

    # 3. Fast Path: Chào hỏi, cảm ơn, tạm biệt đơn giản (Chitchat) (0ms)
    fast_chat = get_fast_chitchat(model_question)
    if fast_chat:
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(fast_chat)
        _add_to_history(question, fast_chat)
        if on_done:
            on_done(fast_chat)
        print(f'✅ [CHITCHAT] Trả lời chào hỏi tức thì: "{fast_chat[:80]}"')
        return fast_chat


    exact_answer = realtime_answer(model_question)
    if exact_answer:
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(exact_answer)
        _add_to_history(question, exact_answer)
        if on_done:
            on_done(exact_answer)
        print(f'✅ [REALTIME] Trả lời tức thì: "{exact_answer}"')
        return exact_answer

    lesson_record = None
    if intent_decision.intent is Intent.KNOWLEDGE_QNA:
        lesson_record = learning_record(model_question)
        if not lesson_record:
            unavailable = _unverified_knowledge_response(model_question)
            if on_thinking:
                on_thinking("answering")
            if on_chunk:
                on_chunk(unavailable)
            _add_to_history(question, unavailable)
            if on_done:
                on_done(unavailable)
            print("ℹ️ [RAG] Circuit breaker: không có đúng một bài đã qua semantic gate; không gọi LLM.")
            return unavailable

    # Với câu hỏi tra từ trực tiếp, lấy đáp án từ dữ liệu bài học đã xác thực.
    # Nhánh này vừa nhanh vừa tránh để model nhỏ làm sai Kanji/Hiragana/Romaji.
    grounded_answer = (grounded_learning_answer(model_question, lesson_record)
                       if intent_decision.intent is Intent.KNOWLEDGE_QNA else None)
    if grounded_answer:
        # Publish hiển thị (Kanji/Tiếng Anh/Tiếng Việt) lên MQTT để OLED hiển thị
        publish_learning_display(model_question, lesson_record)
                
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(grounded_answer)
        _add_to_history(question, grounded_answer)
        if on_done:
            on_done(grounded_answer)
        print(f'✅ [RAG] Trả lời xác thực: "{grounded_answer[:80]}"')
        return grounded_answer
        
    # Xử lý các câu đố vui / sự thật giải trí từ Hash Map
    entertain_answer = (get_entertainment(model_question)
                        if intent_decision.intent is not Intent.KNOWLEDGE_QNA else None)
    if entertain_answer:
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(entertain_answer)
        _add_to_history(question, entertain_answer)
        if on_done:
            on_done(entertain_answer)
        print(f'✅ [ENTERTAIN] Kể chuyện/Đố vui: "{entertain_answer[:80]}"')
        return entertain_answer

    if not _client:
        if lesson_record:
            fallback = _grounded_lesson_template(model_question, lesson_record)
            if on_thinking:
                on_thinking("answering")
            if on_chunk:
                on_chunk(fallback)
            _add_to_history(question, fallback)
            if on_done:
                on_done(fallback)
            return fallback
        error_msg = "Xin lỗi, Moon chưa kết nối được với Qwen. Vui lòng kiểm tra Ollama."
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(error_msg)
        if on_done:
            on_done(error_msg)
        return error_msg

    print(f"🧠 [LLM] Câu hỏi: \"{question}\" | Model: {_model_name}")
    t0 = time.time()

    try:
        messages = _get_messages(model_question, intent_decision, lesson_record=lesson_record)

        # Nếu có bài học RAG liên quan, hiển thị lên OLED ngay
        disp_info = lesson_record or learning_display_info(model_question)
        if disp_info:
            publish_learning_display(model_question, disp_info)

        # Extra params cho DeepSeek Reasoner
        extra_kwargs = {}
        if _is_deepseek and "reasoner" in _model_name:
            extra_kwargs["max_tokens"] = 8000  # reasoner cần nhiều token hơn

        if on_thinking:
            on_thinking("answering")

        max_tokens = extra_kwargs.get("max_tokens", 150)
        temperature = 0.0 if _provider_name == "ollama" else 0.7
        
        expected_lang = response_language(model_question)
        attempts = 0
        max_attempts = 2
        full_response = ""

        while attempts < max_attempts:
            stream = _stream_provider(
                _client,
                _provider_name,
                _model_name,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            attempt_chunks = []
            for chunk in stream:
                attempt_chunks.append(chunk)
                if on_chunk and lesson_record is None:
                    on_chunk(chunk)

            candidate = _strip_thinking("".join(attempt_chunks))
            if not candidate:
                attempts += 1
                continue

            full_response = candidate
            break

        if not full_response:
            full_response = (_grounded_lesson_template(model_question, lesson_record)
                             if lesson_record else language_failure_message(expected_lang))
            if on_chunk and lesson_record is None:
                on_chunk(full_response)

        if lesson_record:
            full_response = _guard_lesson_answer(full_response, model_question, lesson_record)
            if on_chunk:
                # Buffer lesson generation until the output guard has run so
                # invalid text never reaches the browser/TTS stream.
                on_chunk(full_response)

        elapsed = time.time() - t0
        print(
            f"✅ [LLM] Xong ({elapsed:.2f}s) | {_provider_name}/{_model_name}: "
            f"\"{full_response[:80]}\""
        )

        _add_to_history(question, full_response)
        
        # Lưu vào cache cho lần hỏi sau
        _semantic_cache[model_question] = full_response

        if on_done:
            on_done(full_response)

        return full_response

    except Exception as e:
        error_msg = (_grounded_lesson_template(model_question, lesson_record)
                     if lesson_record else "Xin lỗi, Moon gặp sự cố khi suy nghĩ. Bạn thử hỏi lại nhé!")
        print(f"❌ [LLM] Lỗi: {e}")
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(error_msg)
        if on_done:
            on_done(error_msg)
        return error_msg


_quick_cloud_client = None
_quick_cloud_provider = None

# Ưu tiên Gemini cho tác vụ phụ vì token miễn phí rất dư dả
if GEMINI_API_KEY:
    try:
        from server.llm_providers.gemini import GeminiTextClient
        _quick_cloud_client = GeminiTextClient(GEMINI_API_KEY, GEMINI_LLM_MODEL)
        _quick_cloud_provider = "gemini"
    except Exception:
        pass
# Nếu không có Gemini thì dự phòng bằng Groq
elif GROQ_API_KEY:
    try:
        from groq import Groq
        _quick_cloud_client = Groq(api_key=GROQ_API_KEY)
        _quick_cloud_provider = "groq"
    except Exception:
        pass

def quick(prompt: str, max_tokens: int = 200) -> str:
    """Completion cực ngắn, không lịch sử — dùng tạo caption OLED / sửa lỗi ASR /
    chọn cảm xúc. Dùng model INSTANT (nhanh gấp ~10 lần gpt-oss reasoning).
    Hỗ trợ fallback nhiều tầng: Cloud API (Gemini/Groq) -> Local Ollama/Client -> Safe default."""
    # ── Tầng 1: Thử Cloud API (Gemini/Groq) nếu khả dụng ─────────────────────
    if _quick_cloud_client:
        try:
            if _quick_cloud_provider == "gemini":
                return _quick_cloud_client.complete(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=0.2,
                )
            elif _quick_cloud_provider == "groq":
                response = _quick_cloud_client.chat.completions.create(
                    model=QUICK_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.2,
                    stream=False,
                )
                return (response.choices[0].message.content or "").strip()
        except Exception as cloud_err:
            print(f"⚠️ [LLM] quick() cloud API ({_quick_cloud_provider}/{QUICK_MODEL}) lỗi: {cloud_err}. Fallback sang local Ollama...")

    # ── Tầng 2: Fallback sang Client chính đang hoạt động (Ollama/Gemini/Groq) ──
    if _client:
        try:
            if _provider_name in {"gemini", "ollama"}:
                return _client.complete(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=0.2,
                )

            quick_model = QUICK_MODEL if _provider_name == "groq" else _model_name
            response = _client.chat.completions.create(
                model=quick_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
                stream=False,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as client_err:
            print(f"⚠️ [LLM] quick() client fallback lỗi: {client_err}")

    # ── Tầng 3: Thử trực tiếp Ollama local nếu các tầng trên chưa dùng được ────
    try:
        from server.llm_providers.ollama import OllamaTextClient
        local_client = OllamaTextClient(OLLAMA_LLM_MODEL, OLLAMA_HOST)
        return local_client.complete(
            prompt,
            max_tokens=max_tokens,
            temperature=0.2,
        )
    except Exception as local_err:
        print(f"⚠️ [LLM] quick() local Ollama direct fallback lỗi: {local_err}")

    return ""


def chat_async(
    question: str,
    on_thinking: callable = None,
    on_chunk: callable = None,
    on_done: callable = None,
    conversation_id: str | None = None,
    turn_id: str | None = None,
    should_cancel: callable = None,
) -> threading.Thread:
    """Phiên bản bất đồng bộ — chạy trong thread riêng."""
    # Calls without an identity get a private one-shot conversation. New clients
    # pass a stable session id explicitly to enable retrieval safely.
    conversation_id = conversation_id or f"ephemeral-{uuid.uuid4().hex}"
    t = threading.Thread(
        target=chat,
        args=(question, on_thinking, on_chunk, on_done, conversation_id, turn_id, should_cancel),
        daemon=True,
    )
    t.start()
    return t


# ─── Test ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test LLM Module ===")
    print(f"Client: {_provider_name or 'none'} | Model: {_model_name}\n")

    def on_thinking(stage):
        print("🧠 Thinking..." if stage == "thinking" else "✍️  Answering...")

    def on_chunk(chunk):
        print(chunk, end="", flush=True)

    def on_done(full_text):
        print(f"\n\n✅ Done! ({len(full_text)} chars)")

    chat("Moon ơi, hôm nay bạn cảm thấy thế nào?",
         on_thinking=on_thinking, on_chunk=on_chunk, on_done=on_done)
