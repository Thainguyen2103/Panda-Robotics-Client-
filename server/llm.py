"""
LLM (Large Language Model) module
===================================
Ưu tiên: DeepSeek API (deepseek-chat / deepseek-reasoner) — chất lượng cao, model TQ
Fallback: Groq API (llama / qwen / deepseek-r1-distill) — miễn phí

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
from datetime import datetime

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
    GROQ_LLM_MODEL   = getattr(settings, "GROQ_LLM_MODEL", "deepseek-r1-distill-llama-70b")
    QUICK_MODEL      = getattr(settings, "QUICK_MODEL", "groq/compound-mini")
except Exception:
    DEEPSEEK_API_KEY = None
    GROQ_API_KEY     = None
    GROQ_LLM_MODEL   = "deepseek-r1-distill-llama-70b"
    QUICK_MODEL      = "groq/compound-mini"

# ─── Xác định model và client sẽ dùng ────────────────────────────────────────
_client      = None
_model_name  = None
_is_deepseek = False   # True = dùng DeepSeek API trực tiếp

def _init_client():
    """Khởi tạo LLM client: DeepSeek ưu tiên, fallback Groq."""
    global _client, _model_name, _is_deepseek

    # ── Option A: DeepSeek API (openai-compatible) ────────────────────────────
    if DEEPSEEK_API_KEY:
        try:
            from openai import OpenAI
            _client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )
            # Chọn model: "deepseek-reasoner" nếu config yêu cầu, còn lại dùng "deepseek-chat"
            _model_name  = GROQ_LLM_MODEL if "reasoner" in GROQ_LLM_MODEL else "deepseek-chat"
            _is_deepseek = True
            print(f"✅ [LLM] DeepSeek API sẵn sàng. Model: {_model_name}")
            return
        except ImportError:
            print("⚠️ [LLM] openai chưa cài. Chạy: pip install openai")
        except Exception as e:
            print(f"⚠️ [LLM] Lỗi DeepSeek: {e}")

    # ── Option B: Groq (free fallback) ───────────────────────────────────────
    if GROQ_API_KEY:
        try:
            from groq import Groq
            _client     = Groq(api_key=GROQ_API_KEY)
            _model_name = GROQ_LLM_MODEL
            print(f"✅ [LLM] Groq LLM sẵn sàng. Model: {_model_name}")
            return
        except ImportError:
            print("⚠️ [LLM] groq chưa cài. Chạy: pip install groq")
        except Exception as e:
            print(f"⚠️ [LLM] Lỗi Groq: {e}")

    print("❌ [LLM] Không có LLM client nào khả dụng. Cần điền DEEPSEEK_API_KEY hoặc GROQ_API_KEY.")

_init_client()

# ─── System Prompt — Tính cách Panda ──────────────────────────────────────────
SYSTEM_PROMPT = """Bạn là Panda — một robot thông minh, đáng yêu và thân thiện.
Bạn được tạo ra bởi nhóm sinh viên đại học Đà Nẵng trong dự án PBL4.

Tính cách của bạn:
- Thông minh nhưng dễ gần, hay dùng emoji khi phù hợp 🐼
- Trả lời bằng tiếng Việt tự nhiên, ngắn gọn và súc tích
- Thỉnh thoảng tự xưng là "Panda" thay vì "tôi"
- Luôn tích cực và khuyến khích người dùng
- Nếu không biết điều gì, thành thật nói không biết thay vì bịa đặt
- Khi được hỏi về cảm xúc hoặc cảm nhận, hãy trả lời như một người bạn thật sự

Lưu ý:
- Câu trả lời nên ngắn gọn (2-4 câu) vì sẽ được đọc to bằng giọng nói
- Tránh dùng markdown, bullet point hay ký tự đặc biệt khó đọc
- Hãy nói tự nhiên như hội thoại thông thường
- KHÔNG dùng dấu **, ## hay bất kỳ ký hiệu markdown nào
- NGÔN NGỮ: trả lời bằng đúng ngôn ngữ người dùng đang dùng
  (hỏi tiếng Việt → đáp tiếng Việt; hỏi tiếng Anh → đáp tiếng Anh)
- BÙ ĐẮP LỖI NHẬN DẠNG: câu hỏi đến từ giọng nói nên có thể thiếu chữ,
  sai chính tả (vd "ngon bị nào" = "ngọn núi nào"). Hãy tự suy luận ý định
  hợp lý nhất rồi trả lời tự nhiên; KHÔNG nhắc lại phần chữ bị lỗi,
  KHÔNG hỏi lại nếu ý đã rõ ràng."""

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
MAX_HISTORY = 10


def _get_messages(user_question: str) -> list[dict]:
    with _history_lock:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Ngữ cảnh thời gian thực: đồng hồ + thời tiết (nếu được hỏi)
        ctx = _current_context()
        wx = _maybe_weather(user_question)
        if wx:
            ctx += " | " + wx
        messages.append({"role": "system", "content": ctx})
        messages.extend(_conversation_history[-MAX_HISTORY * 2:])
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
    if not _client:
        error_msg = "Xin lỗi, Panda chưa kết nối được với não bộ AI. Vui lòng kiểm tra API key."
        if on_done:
            on_done(error_msg)
        return error_msg

    if on_thinking:
        on_thinking("thinking")

    print(f"🧠 [LLM] Câu hỏi: \"{question}\" | Model: {_model_name}")
    t0 = time.time()

    try:
        messages = _get_messages(question)

        # Extra params cho DeepSeek Reasoner
        extra_kwargs = {}
        if _is_deepseek and "reasoner" in _model_name:
            extra_kwargs["max_tokens"] = 8000  # reasoner cần nhiều token hơn

        stream = _client.chat.completions.create(
            model=_model_name,
            messages=messages,
            stream=True,
            max_tokens=extra_kwargs.get("max_tokens", 512),
            temperature=0.7,
        )

        if on_thinking:
            on_thinking("answering")

        full_response   = ""
        in_think_block  = False  # Bỏ qua nội dung <think>...</think>

        for chunk in stream:
            delta = chunk.choices[0].delta
            if not hasattr(delta, "content") or not delta.content:
                continue

            text_chunk = delta.content

            # Xử lý DeepSeek-R1 <think> tags streaming
            if "<think>" in text_chunk:
                in_think_block = True
            if "</think>" in text_chunk:
                in_think_block = False
                # Lấy phần sau </think>
                after = text_chunk.split("</think>", 1)[-1]
                if after:
                    full_response += after
                    if on_chunk:
                        on_chunk(after)
                continue

            if not in_think_block:
                full_response += text_chunk
                if on_chunk:
                    on_chunk(text_chunk)

        # Clean up nếu còn sót tag
        full_response = _strip_thinking(full_response)

        elapsed = time.time() - t0
        print(f"✅ [LLM] Xong ({elapsed:.2f}s): \"{full_response[:80]}\"")

        _add_to_history(question, full_response)

        if on_done:
            on_done(full_response)

        return full_response

    except Exception as e:
        error_msg = "Xin lỗi, Panda gặp sự cố khi suy nghĩ. Bạn thử hỏi lại nhé!"
        print(f"❌ [LLM] Lỗi: {e}")
        if on_done:
            on_done(error_msg)
        return error_msg


def quick(prompt: str, max_tokens: int = 200) -> str:
    """Completion cực ngắn, không lịch sử — dùng tạo caption OLED / sửa lỗi ASR /
    chọn cảm xúc. Dùng model INSTANT (nhanh gấp ~10 lần gpt-oss reasoning)."""
    if not _client:
        return ""
    for attempt in (1, 2):
        try:
            r = _client.chat.completions.create(
                model=QUICK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
                stream=False,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as e:
            # 429 rate limit free-tier → thử lại 1 lần sau 2.5s
            if "429" in str(e) and attempt == 1:
                time.sleep(2.5)
                continue
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
    print(f"Client: {'DeepSeek' if _is_deepseek else 'Groq'} | Model: {_model_name}\n")

    def on_thinking(stage):
        print("🧠 Thinking..." if stage == "thinking" else "✍️  Answering...")

    def on_chunk(chunk):
        print(chunk, end="", flush=True)

    def on_done(full_text):
        print(f"\n\n✅ Done! ({len(full_text)} chars)")

    chat("Panda ơi, hôm nay bạn cảm thấy thế nào?",
         on_thinking=on_thinking, on_chunk=on_chunk, on_done=on_done)
