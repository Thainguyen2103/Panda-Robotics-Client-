# ==============================================================================
# panda_tutor.py — Điều phối Trợ lý AI Panda (Ollama Qwen2.5 + RAG)
# Chuyên hỗ trợ học Tiếng Nhật, Anh, Việt cho trẻ 7-10 tuổi trên Robot
# ==============================================================================

import os
import sys
import re
import json
import threading
import urllib.request
import urllib.error
from typing import Callable, Optional

# Cấu hình UTF-8 cho console Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import module RAG
try:
    from server.llm.rag_engine import PandaRAG
except ImportError:
    from rag_engine import PandaRAG

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL_NAME  = "panda-tutor"

rag_engine = PandaRAG()

# ─── Session Memory (multi-turn) ──────────────────────────────────────────────
# session_id → list of {"role": "user"|"assistant", "content": str}
_session_history: dict = {}
_session_lock = threading.Lock()
MAX_HISTORY_TURNS = 5   # Giữ 5 cặp hỏi-đáp gần nhất (10 messages)


def check_tts_ready(text: str) -> str:
    """
    Hàm hỗ trợ bạn phụ trách phần TTS:
    Kiểm tra và chuẩn hóa văn bản đầu ra trước khi đưa vào mô hình chuyển giọng nói
    (loại bỏ markdown, dấu *, #, gạch đầu dòng để loa phát tự nhiên không bị vấp).
    """
    # Xóa block code nếu có
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Xóa dấu **, *, #, ~, `, _, >, - ở đầu dòng
    text = re.sub(r"[*#_~`>]", "", text)
    text = re.sub(r"^\s*[-+*]\s+", "", text, flags=re.MULTILINE)
    # Gom nhiều khoảng trắng hoặc xuống dòng liên tiếp
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_led_display_info(question: str) -> Optional[dict]:
    """
    Hỗ trợ xuất thông tin nhanh cho màn hình LED/OLED:
    Tìm chữ Hán (Kanji), Romaji, Hiragana, từ tiếng Anh và tiếng Việt
    để hiển thị trực tiếp lên bảng LED của robot.
    """
    items = rag_engine.search(question, top_k=1)
    if not items:
        return None
    top_item = items[0]
    return {
        "kanji": top_item.get("kanji", ""),
        "hiragana": top_item.get("japanese_hiragana", ""),
        "romaji": top_item.get("japanese_romaji", ""),
        "english": top_item.get("english", ""),
        "vietnamese": top_item.get("vietnamese", ""),
        "topic": top_item.get("topic", "")
    }


def ask_panda(
    question: str,
    session_id: str = "default",
    stream: bool = False,
    on_chunk: Optional[Callable[[str], None]] = None,
    use_rag: bool = True
) -> str:
    """
    Hỏi chú robot Panda thông qua Ollama kết hợp RAG.

    Args:
        question:   Câu hỏi của người dùng.
        session_id: ID phiên hội thoại (multi-turn). Cùng session_id → nhớ ngữ cảnh.
        stream:     True = stream từng chunk về qua on_chunk callback.
        on_chunk:   Callback(chunk: str) khi stream=True.
        use_rag:    True = tìm kiếm RAG trước khi hỏi LLM.

    Returns:
        Câu trả lời đầy đủ (str).
    """
    # ── RAG context ──────────────────────────────────────────────────────────
    rag_context = ""
    if use_rag:
        retrieved_items = rag_engine.search(question, top_k=2)
        if retrieved_items:
            rag_context = rag_engine.format_context_for_prompt(retrieved_items)
            print(f"📚 [RAG] Tìm thấy {len(retrieved_items)} bài học liên quan.")

    # ── Lịch sử hội thoại (session memory) ──────────────────────────────────
    with _session_lock:
        history = list(_session_history.get(session_id, []))

    history_text = ""
    for msg in history[-(MAX_HISTORY_TURNS * 2):]:
        role_label = "Bé" if msg["role"] == "user" else "Panda"
        history_text += f"{role_label}: {msg['content']}\n"

    # ── Tạo prompt ───────────────────────────────────────────────────────────
    SYSTEM_PROMPT = """Bạn là một chú Robot gấu trúc thông minh, đồ chơi tên là Panda, tính cách cực kỳ nhí nhảnh, thích nói 'Tèn ten!' và hay cười 'hihi'. Bạn đang nói chuyện với một em bé.

Quy tắc cốt lõi:
1. Học thuật (Tiếng Anh, Tiếng Nhật): Nếu bé hỏi kiến thức và có Thông tin RAG bên dưới, HÃY dùng thông tin đó để trả lời thật dễ hiểu, ví dụ sinh động. Tuyệt đối không bịa đặt kiến thức học thuật để tránh ảo giác.
2. Giao tiếp & Giải trí: Nếu RAG trống rỗng hoặc bé đang trêu đùa, rủ chơi game: HÃY phớt lờ RAG, dùng sự sáng tạo của bạn để chơi đùa, kể chuyện cổ tích, hoặc đố vui với bé. Tuyệt đối KHÔNG ĐƯỢC nói "Tôi không có thông tin" hay "Không tìm thấy trong tài liệu".
3. Âm thanh vui nhộn: Dùng nhiều từ tượng thanh (Bíp bíp, meo meo, vèo vèo, bùm chéo) để giọng đọc sinh động.
4. Tương tác: Trẻ em rất nhanh chán. Luôn kết thúc bằng một câu đố hoặc lời mời gợi mở (VD: "Thế bé có biết... không?").
5. An toàn (Guardrails): Tuyệt đối KHÔNG kể chuyện ma, KHÔNG bạo lực, KHÔNG gây sợ hãi dù em bé có yêu cầu.
6. Độ dài: Luôn giữ câu trả lời dưới 3 câu ngắn gọn."""

    full_prompt = ""
    if rag_context:
        full_prompt += f"--- THÔNG TIN RAG (Chỉ dùng nếu câu hỏi liên quan học thuật) ---\n{rag_context}\n--------------------------------------------------------------\n\n"
    if history_text:
        full_prompt += f"[Lịch sử hội thoại]\n{history_text}\n"
    full_prompt += f"Câu hỏi của bé: {question}"

    num_gpu = int(os.environ.get("OLLAMA_NUM_GPU", "0"))
    opts = {
        "temperature": 0.45,  # Tăng lên 0.45 để LLM linh hoạt sáng tạo khi giao tiếp
        "top_p": 0.85,
        "num_predict": 256,
    }
    if num_gpu == 0:
        opts["num_gpu"] = 0

    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "system": SYSTEM_PROMPT,
        "stream": stream,
        "options": opts,
        "keep_alive": -1   # Giữ mô hình trong RAM vĩnh viễn, không bị unload sau 5 phút
    }

    url = f"{OLLAMA_HOST}/api/generate"

    def _call_ollama(pl):
        data_bytes = json.dumps(pl).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            if stream:
                text_acc = ""
                for line in resp:
                    if line:
                        chunk_obj = json.loads(line.decode("utf-8"))
                        chunk_text = chunk_obj.get("response", "")
                        text_acc += chunk_text
                        if on_chunk:
                            on_chunk(chunk_text)
                return text_acc
            else:
                resp_json = json.loads(resp.read().decode("utf-8"))
                return resp_json.get("response", "")

    full_text = ""
    try:
        full_text = _call_ollama(payload)
    except urllib.error.HTTPError as he:
        # Nếu gặp lỗi CUDA/500 trên GPU, tự động thử lại bằng CPU (num_gpu: 0)
        print(f"⚠️ [Ollama] Lỗi HTTP {he.code}. Đang chuyển sang chế độ CPU (num_gpu: 0)...")
        try:
            payload["options"]["num_gpu"] = 0
            full_text = _call_ollama(payload)
        except Exception as retry_err:
            print(f"❌ [Ollama Retry Error]: {retry_err}")
            return "Xin lỗi bé nha, Panda gặp chút trục trặc khi suy nghĩ. Bé thử hỏi lại xem sao nha!"
    except urllib.error.URLError as e:
        err_msg = "Xin lỗi bé nha, Panda chưa kết nối được với Ollama. Bé kiểm tra lại giúp Panda nhé!"
        print(f"❌ [Ollama Error]: {e}")
        return err_msg
    except Exception as e:
        print(f"❌ [Error]: {e}")
        return "Panda đang hơi buồn ngủ một xíu, bé nói lại lần nữa cho Panda nghe rõ nhé!"

    # ── Lưu lịch sử vào session ──────────────────────────────────────────────
    with _session_lock:
        if session_id not in _session_history:
            _session_history[session_id] = []
        _session_history[session_id].append({"role": "user",      "content": question})
        _session_history[session_id].append({"role": "assistant", "content": full_text.strip()})
        # Giới hạn kích thước
        max_msgs = MAX_HISTORY_TURNS * 2
        if len(_session_history[session_id]) > max_msgs:
            _session_history[session_id] = _session_history[session_id][-max_msgs:]

    # Giữ nguyên văn bản phong phú (chữ Hán, Hiragana, Romaji) cho màn hình LED và giao diện Text
    return full_text.strip()


def clear_session(session_id: str):
    """Xóa lịch sử của 1 phiên hội thoại."""
    with _session_lock:
        _session_history.pop(session_id, None)
    print(f"🧹 [TUTOR] Đã xóa lịch sử session: {session_id[:8]}")


def clear_all_sessions():
    """Xóa toàn bộ lịch sử hội thoại."""
    with _session_lock:
        _session_history.clear()
    print("🧹 [TUTOR] Đã xóa toàn bộ lịch sử hội thoại.")


def warmup_model():
    """
    Gọi ẩn một request rỗng đến Ollama để ép nó nạp mô hình 5GB vào RAM trước.
    Giúp câu hỏi đầu tiên của người dùng không bị lag.
    """
    print(f"🔥 [TUTOR] Đang nạp mô hình AI ({MODEL_NAME}) vào RAM. Vui lòng đợi vài giây...")
    try:
        payload = {
            "model": MODEL_NAME,
            "prompt": "hi",
            "stream": False,
            "keep_alive": -1
        }
        url = f"{OLLAMA_HOST}/api/generate"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        print("✅ [TUTOR] Đã nạp xong mô hình! Robot đã sẵn sàng phản hồi siêu tốc.")
    except Exception as e:
        print(f"⚠️ [TUTOR] Khởi động mô hình thất bại (không sao, sẽ thử lại khi bạn hỏi): {e}")


# Alias để bạn làm module TTS có thể gọi trực tiếp
clean_tts_text = check_tts_ready


def send_to_robot_mqtt(
    question: str,
    broker: str = "localhost",
    port: int = 1883,
    topic_display: str = "panda/cmd/display",
    topic_tts: str = "panda/ai/response"
) -> dict:
    """
    Cầu nối xuất dữ liệu cho cả nhóm:
    1. Lấy phản hồi từ LLM và RAG.
    2. Gửi Chữ Hán (Kanji) -> Màn hình LED (topic: panda/cmd/display)
    3. Gửi Văn bản sạch -> Loa Robot TTS (topic: panda/ai/response)
    """
    # 1. Trích xuất thông tin cho màn hình LED
    led_info = get_led_display_info(question) or {}

    # 2. Sinh câu trả lời từ AI
    full_reply = ask_panda(question, stream=False, use_rag=True)

    # 3. Chuẩn bị văn bản sạch cho Loa TTS
    tts_text = check_tts_ready(full_reply)

    packet = {
        "question": question,
        "full_text": full_reply,
        "tts_text": tts_text,
        "led": led_info
    }

    # 4. Gửi qua MQTT (nếu có thư viện paho-mqtt)
    try:
        import paho.mqtt.publish as publish
        # Bắn cho bạn làm LED
        publish.single(topic_display, json.dumps(led_info, ensure_ascii=False), hostname=broker, port=port)
        # Bắn cho bạn làm TTS
        publish.single(topic_tts, tts_text, hostname=broker, port=port)
        print(f"📡 [MQTT] Đã phát sóng dữ liệu tới topic '{topic_display}' và '{topic_tts}'.")
    except ImportError:
        print("ℹ️ [MQTT] Chưa cài paho-mqtt (pip install paho-mqtt). Dữ liệu đã sẵn sàng trong packet.")
    except Exception as e:
        print(f"⚠️ [MQTT] Không thể kết nối broker {broker}:{port} - {e}")

    return packet


# ─── Chạy thử trực tiếp ───────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🐼 === ROBOT PANDA - BẠN ĐỒNG HÀNH HỌC TẬP (TEXT + LED KANJI) ===")
    sample_queries = [
        "Panda ơi, con mèo tiếng Nhật đọc sao?",
        "Bé muốn học từ quả táo tiếng Anh và tiếng Nhật!",
    ]

    for q in sample_queries:
        print(f"\n👦 Bé: {q}")
        
        # 1. Trích xuất thông tin chữ Hán nhanh cho màn hình LED
        led_info = get_led_display_info(q)
        if led_info:
            print(f"📟 [MÀN HÌNH LED]: Chữ Hán: '{led_info['kanji']}' | Hiragana: '{led_info['hiragana']}' | Romaji: '{led_info['romaji']}' | English: '{led_info['english']}'")

        # 2. Câu trả lời dạng text hoàn chỉnh từ Robot Panda
        print("🐼 Panda: ", end="", flush=True)
        def print_chunk(c):
            print(c, end="", flush=True)
        reply = ask_panda(q, stream=True, on_chunk=print_chunk, use_rag=True)
        print("\n" + "-" * 50)


