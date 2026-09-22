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
import unicodedata
from datetime import datetime

from server.llm_language import (
    language_failure_message,
    normalize_user_question,
    response_language,
    response_language_instruction,
    response_language_matches,
    strict_retry_instruction,
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
    OLLAMA_MAX_TOKENS = getattr(settings, "OLLAMA_MAX_TOKENS", 128)
    LLM_PROVIDER     = getattr(settings, "LLM_PROVIDER", "ollama")
    LEARNING_RAG_ENABLED = getattr(settings, "LEARNING_RAG_ENABLED", True)
    QUICK_MODEL      = getattr(settings, "QUICK_MODEL", "groq/compound-mini")
except Exception:
    DEEPSEEK_API_KEY = None
    GROQ_API_KEY     = None
    GEMINI_API_KEY   = None
    GROQ_LLM_MODEL   = "deepseek-r1-distill-llama-70b"
    GEMINI_LLM_MODEL = "gemini-3.5-flash-lite"
    OLLAMA_HOST = "http://127.0.0.1:11434"
    OLLAMA_LLM_MODEL = "moon-tutor"
    OLLAMA_MAX_TOKENS = 128
    LLM_PROVIDER     = "ollama"
    LEARNING_RAG_ENABLED = True
    QUICK_MODEL      = "groq/compound-mini"

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
if LEARNING_RAG_ENABLED:
    try:
        from server.learning import get_display_info as _get_learning_display_info
        from server.learning import retrieve_context as _retrieve_learning_context
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


def learning_context(question: str) -> str:
    """Return verified lesson context without making the whole LLM depend on RAG."""
    if not _retrieve_learning_context or not has_learning_intent(question):
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


_VOCAB_LOOKUP_MARKERS = (
    "tiếng nhật", "đọc thế nào", "đọc là gì", "viết thế nào", "nghĩa là gì",
    "chữ hán", "hán tự", "kanji", "hiragana", "romaji",
    "how do you say", "in japanese", "how is", "pronounce", "written in",
    "日本語", "読み", "読ん", "書き", "漢字", "ひらがな", "ローマ字", "意味",
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
            f"現在は{now:%H時%M分}、{now.year}年{now.month}月{now.day}日"
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


def grounded_learning_answer(question: str) -> str | None:
    """Answer direct vocabulary lookups from verified lesson fields.

    Small local models can omit a field or alter a Kanji even when the prompt
    contains correct RAG data. Direct lookups therefore use a deterministic
    sentence assembled from the lesson; Qwen remains responsible for normal
    conversation and open-ended teaching.
    """
    normalized = unicodedata.normalize("NFC", question or "").casefold()
    if not any(marker in normalized for marker in _VOCAB_LOOKUP_MARKERS):
        return None

    info = learning_display_info(question)
    if not info:
        return None

    kanji = str(info.get("kanji") or "").strip()
    hiragana = str(info.get("hiragana") or "").strip()
    romaji = str(info.get("romaji") or "").strip()
    english = str(info.get("english") or "").strip()
    vietnamese = str(info.get("vietnamese") or "").strip()
    if not all((kanji, hiragana, romaji, english, vietnamese)):
        return None

    language = response_language(question)
    if language == "ja":
        return (
            f"日本語では「{kanji}」と書き、「{hiragana}」"
            f"（ローマ字: {romaji}）と読みます。英語では「{english}」、"
            f"ベトナム語では「{vietnamese}」です。"
        )
    if language == "en":
        return (
            f"In Japanese, {english} is written {kanji} and read {hiragana} "
            f"({romaji}); in Vietnamese, it means {vietnamese}."
        )
    return (
        f"Trong tiếng Nhật, {vietnamese} viết là {kanji}, đọc là {hiragana} "
        f"({romaji}); tiếng Anh là {english}."
    )

# ─── System Prompt — Tính cách Moon ──────────────────────────────────────────
SYSTEM_PROMPT = """You are Moon, a friendly panda robot from the PBL4 project.
- Reply only in the language of the user's latest message: Vietnamese, English, or Japanese.
- Never use Chinese unless the user speaks Chinese.
- Give a natural, accurate voice answer in one to three short sentences.
- Follow an explicit sentence limit and do not use Markdown.
- If unsure, say you do not know instead of inventing facts.
- Input comes from STT; silently repair an obvious minor transcription error."""

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
# Bốn lượt gần nhất đủ giữ mạch hội thoại nhưng không làm prompt local tăng dần
# đến mức chậm rõ rệt sau một phút trò chuyện.
MAX_HISTORY = 4


def _get_messages(user_question: str) -> list[dict]:
    with _history_lock:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Câu hỏi giờ/ngày đã có nhánh deterministic. Chỉ bơm thời tiết khi
        # được hỏi để model nhỏ không lặp lại giờ hệ thống trong hội thoại thường.
        wx = _maybe_weather(user_question)
        if wx:
            messages.append({"role": "system", "content": wx})
        lesson_context = learning_context(user_question)
        if lesson_context:
            print("📚 [RAG] Đã thêm bài học xác thực vào prompt.")
            messages.append({
                "role": "system",
                "content": (
                    "[Verified learning material] For language-learning facts, use the "
                    "following lesson exactly. Do not invent or silently alter Kanji, "
                    "Hiragana, Romaji, translations, examples, or quiz content. When "
                    "teaching a Japanese word, include its Kanji, Hiragana, Romaji, and "
                    "meaning in the response language.\n\n"
                    + lesson_context
                ),
            })
        messages.extend(_conversation_history[-MAX_HISTORY * 2:])
        messages.append({"role": "system", "content": response_language_instruction(user_question)})
        messages.append({"role": "user", "content": user_question})
    return messages


def _add_to_history(user_msg: str, assistant_msg: str):
    with _history_lock:
        _conversation_history.append({"role": "user",      "content": user_msg})
        _conversation_history.append({"role": "assistant", "content": assistant_msg})
        if len(_conversation_history) > MAX_HISTORY * 2:
            _conversation_history[:] = _conversation_history[-MAX_HISTORY * 2:]


def clear_history():
    with _history_lock:
        _conversation_history.clear()
    print("🧹 [LLM] Đã xóa lịch sử hội thoại.")


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


# ─── Chat function ─────────────────────────────────────────────────────────────
def chat(
    question: str,
    on_thinking: callable = None,
    on_chunk: callable = None,
    on_done: callable = None,
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
    if on_thinking:
        on_thinking("thinking")

    model_question = normalize_user_question(question)
    if model_question != question:
        print(f'✍️ [LLM] Hiệu chỉnh chắc chắn: "{question}" → "{model_question}"')

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

    # Với câu hỏi tra từ trực tiếp, lấy đáp án từ dữ liệu bài học đã xác thực.
    # Nhánh này vừa nhanh vừa tránh để model nhỏ làm sai Kanji/Hiragana/Romaji.
    grounded_answer = grounded_learning_answer(model_question)
    if grounded_answer:
        if on_thinking:
            on_thinking("answering")
        if on_chunk:
            on_chunk(grounded_answer)
        _add_to_history(question, grounded_answer)
        if on_done:
            on_done(grounded_answer)
        print(f'✅ [RAG] Trả lời xác thực: "{grounded_answer[:80]}"')
        return grounded_answer

    if not _client:
        error_msg = "Xin lỗi, Moon chưa kết nối được với Qwen. Vui lòng kiểm tra Ollama."
        if on_done:
            on_done(error_msg)
        return error_msg

    print(f"🧠 [LLM] Câu hỏi: \"{question}\" | Model: {_model_name}")
    t0 = time.time()

    try:
        messages = _get_messages(model_question)

        # Extra params cho DeepSeek Reasoner
        extra_kwargs = {}
        if _is_deepseek and "reasoner" in _model_name:
            extra_kwargs["max_tokens"] = 8000  # reasoner cần nhiều token hơn

        if on_thinking:
            on_thinking("answering")

        max_tokens = extra_kwargs.get(
            "max_tokens",
            OLLAMA_MAX_TOKENS if _provider_name == "ollama" else 512,
        )
        temperature = 0.25 if _provider_name == "ollama" else 0.7
        full_response = _generate_response(messages, max_tokens, temperature)
        if not full_response:
            raise RuntimeError(f"{_provider_name} trả về nội dung rỗng")

        expected_language = response_language(model_question)
        if not response_language_matches(full_response, expected_language):
            print(
                "⚠️ [LLM] Câu trả lời sai ngôn ngữ; tạo lại trước khi gửi TTS "
                f"(cần {expected_language})."
            )
            retry_messages = messages[:-1] + [
                {
                    "role": "system",
                    "content": strict_retry_instruction(expected_language),
                },
                messages[-1],
            ]
            full_response = _generate_response(retry_messages, max_tokens, 0.1)
            if not response_language_matches(full_response, expected_language):
                full_response = language_failure_message(expected_language)

        # Không phát bản nháp ra loa. Chỉ câu đã qua kiểm tra ngôn ngữ mới được
        # chuyển cho bộ tách câu/TTS ở Brain.
        if on_chunk:
            on_chunk(full_response)

        elapsed = time.time() - t0
        print(
            f"✅ [LLM] Xong ({elapsed:.2f}s) | {_provider_name}/{_model_name}: "
            f"\"{full_response[:80]}\""
        )

        _add_to_history(question, full_response)

        if on_done:
            on_done(full_response)

        return full_response

    except Exception as e:
        error_msg = "Xin lỗi, Moon gặp sự cố khi suy nghĩ. Bạn thử hỏi lại nhé!"
        print(f"❌ [LLM] Lỗi: {e}")
        if on_done:
            on_done(error_msg)
        return error_msg


def quick(prompt: str, max_tokens: int = 200) -> str:
    """Completion cực ngắn, không lịch sử — dùng tạo caption OLED / sửa lỗi ASR /
    chọn cảm xúc. Dùng model INSTANT (nhanh gấp ~10 lần gpt-oss reasoning)."""
    if not _client:
        return ""

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
    except Exception as e:
        print(f"⚠️ [LLM] quick() lỗi: {e}")
        return ""


def chat_async(
    question: str,
    on_thinking: callable = None,
    on_chunk: callable = None,
    on_done: callable = None,
) -> threading.Thread:
    """Phiên bản bất đồng bộ — chạy trong thread riêng."""
    t = threading.Thread(
        target=chat,
        args=(question, on_thinking, on_chunk, on_done),
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
