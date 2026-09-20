"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: moon_tutor.py (Bộ não LLM & Giao tiếp)
--------------------------------------------------------------------------------
Nhiệm vụ: Giao tiếp với Ollama, đóng vai chú gấu trúc nhí nhảnh và lấy dữ liệu từ RAG.

[CẤU TRÚC CHÍNH]
1. _session_history: Bộ nhớ lưu lại 5 câu hỏi-đáp gần nhất của người dùng để trả lời bám sát ngữ cảnh.
2. SYSTEM_PROMPT: Luật cấm LLM bịa đặt kiến thức học thuật, nhưng ép LLM phải nói chuyện dễ thương, dùng từ tượng thanh (bíp bíp) và biết đùa giỡn khi rảnh rỗi.
3. ask_moon(): Hàm chính ném toàn bộ Context (Câu hỏi + RAG + Lịch sử) vào Ollama và stream kết quả về cho TTS.
4. warmup_model(): Nạp trước mô hình 5GB vào RAM để chống lag cho câu hỏi đầu tiên.
"""
# ==============================================================================
# moon_tutor.py — Điều phối Trợ lý AI Moon (Ollama Qwen2.5 + RAG)
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

# Cấu hình UTF-8 cho console Windows để in tiếng Việt không bị lỗi font
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import module RAG (Bộ máy tìm kiếm kiến thức)
try:
    from server.llm.rag_engine import MoonRAG
except ImportError:
    from rag_engine import MoonRAG

# Khai báo địa chỉ IP và Port của Ollama chạy dưới máy local (mặc định là 11434)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
# Tên của mô hình AI đang sử dụng
MODEL_NAME  = "moon-tutor"

# Khởi tạo bộ máy RAG để tra cứu sách giáo khoa
rag_engine = MoonRAG()

# ─── Session Memory (multi-turn) ──────────────────────────────────────────────
# Biến _session_history là một cuốn sổ tay ghi nhớ hội thoại của từng người dùng (session_id)
# Cấu trúc: { "mã_người_dùng_1": [{"role": "user", "content": "..."}], ... }
_session_history: dict = {}
# Khóa (Lock) để tránh lỗi khi 2 người dùng cùng chat một lúc dẫn đến ghi đè dữ liệu
_session_lock = threading.Lock()
# Chỉ nhớ tối đa 5 lượt hỏi-đáp (10 tin nhắn) để AI không bị "loãng" bộ nhớ và chạy nhanh hơn
MAX_HISTORY_TURNS = 5   


def check_tts_ready(text: str) -> str:
    """
    Hàm hỗ trợ bạn phụ trách phần TTS:
    Kiểm tra và chuẩn hóa văn bản đầu ra trước khi đưa vào mô hình chuyển giọng nói
    (loại bỏ markdown, dấu *, #, gạch đầu dòng để loa phát tự nhiên không bị vấp).
    """
    # Tìm và xóa các đoạn code block (nếu AI lỡ sinh ra) bằng biểu thức chính quy (Regex)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Xóa các dấu định dạng in đậm, in nghiêng (**, *, #, ~, `, _, >)
    text = re.sub(r"[*#_~`>]", "", text)
    # Xóa các gạch đầu dòng (- hoặc +) ở đầu mỗi câu
    text = re.sub(r"^\s*[-+*]\s+", "", text, flags=re.MULTILINE)
    # Gom nhiều khoảng trắng hoặc dòng trống liên tiếp thành 1 khoảng trắng duy nhất
    text = re.sub(r"\s+", " ", text)
    # Cắt bỏ khoảng trắng dư thừa ở hai đầu chuỗi
    return text.strip()


def get_led_display_info(question: str) -> Optional[dict]:
    """
    Hỗ trợ xuất thông tin nhanh cho màn hình LED/OLED:
    Tìm chữ Hán (Kanji), Romaji, Hiragana, từ tiếng Anh và tiếng Việt
    để hiển thị trực tiếp lên bảng LED của robot.
    """
    # Tìm kiếm bài học sát nhất (top_k=1) với câu hỏi của bé
    items = rag_engine.search(question, top_k=1)
    if not items:
        # Nếu không tìm thấy trong RAG thì trả về None
        return None
    # Lấy kết quả đầu tiên (tốt nhất)
    top_item = items[0]
    # Trả về một dictionary chứa đầy đủ các trường để vẽ lên LED
    return {
        "kanji": top_item.get("kanji", ""),
        "hiragana": top_item.get("japanese_hiragana", ""),
        "romaji": top_item.get("japanese_romaji", ""),
        "english": top_item.get("english", ""),
        "vietnamese": top_item.get("vietnamese", ""),
        "topic": top_item.get("topic", "")
    }


def ask_moon(
    question: str,
    session_id: str = "default",
    stream: bool = False,
    on_chunk: Optional[Callable[[str], None]] = None,
    use_rag: bool = True
) -> str:
    """
    Hỏi chú robot Moon thông qua Ollama kết hợp RAG.

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
    # Chuẩn bị biến chứa nội dung sách giáo khoa (nếu có)
    rag_context = ""
    # Nếu được phép dùng RAG (use_rag = True)
    if use_rag:
        # Gọi hàm tìm kiếm RAG, lấy 2 bài học liên quan nhất
        retrieved_items = rag_engine.search(question, top_k=2)
        # Nếu tìm thấy ít nhất 1 bài học
        if retrieved_items:
            # Biến đổi dữ liệu JSON thành văn bản dễ hiểu cho AI đọc
            rag_context = rag_engine.format_context_for_prompt(retrieved_items)
            # In ra màn hình console số lượng bài học tìm được
            print(f"📚 [RAG] Tìm thấy {len(retrieved_items)} bài học liên quan.")

    # ── Lịch sử hội thoại (session memory) ──────────────────────────────────
    # Mở khóa để lấy lịch sử chat an toàn
    with _session_lock:
        # Lấy lịch sử của session_id hiện tại (nếu chưa có thì trả về list rỗng [])
        history = list(_session_history.get(session_id, []))

    history_text = ""
    # Chỉ lấy 10 tin nhắn gần nhất (5 lượt hỏi-đáp)
    for msg in history[-(MAX_HISTORY_TURNS * 2):]:
        # Dán nhãn "Bé" cho user và "Moon" cho AI
        role_label = "Bé" if msg["role"] == "user" else "Moon"
        # Nối vào chuỗi lịch sử hội thoại
        history_text += f"{role_label}: {msg['content']}\n"

    # ── Tạo prompt ───────────────────────────────────────────────────────────
    # Đây là System Prompt 2 mặt: Quy định cả việc học lẫn việc chơi đùa
    SYSTEM_PROMPT = """Bạn là một chú Robot gấu trúc thông minh, đồ chơi tên là Moon, tính cách cực kỳ nhí nhảnh, thích nói 'Tèn ten!' và hay cười 'hihi'. Bạn đang nói chuyện với một em bé.

Quy tắc cốt lõi:
1. Học thuật (Tiếng Anh, Tiếng Nhật): Nếu bé hỏi kiến thức và có Thông tin RAG bên dưới, HÃY dùng thông tin đó để trả lời thật dễ hiểu, ví dụ sinh động. Tuyệt đối không bịa đặt kiến thức học thuật để tránh ảo giác.
2. Giao tiếp & Giải trí: Nếu RAG trống rỗng hoặc bé đang trêu đùa, rủ chơi game: HÃY phớt lờ RAG, dùng sự sáng tạo của bạn để chơi đùa, kể chuyện cổ tích, hoặc đố vui với bé. Tuyệt đối KHÔNG ĐƯỢC nói "Tôi không có thông tin" hay "Không tìm thấy trong tài liệu".
3. Âm thanh vui nhộn: Dùng nhiều từ tượng thanh (Bíp bíp, meo meo, vèo vèo, bùm chéo) để giọng đọc sinh động.
4. Tương tác: Trẻ em rất nhanh chán. Luôn kết thúc bằng một câu đố hoặc lời mời gợi mở (VD: "Thế bé có biết... không?").
5. An toàn (Guardrails): Tuyệt đối KHÔNG kể chuyện ma, KHÔNG bạo lực, KHÔNG gây sợ hãi dù em bé có yêu cầu.
6. Độ dài: Luôn giữ câu trả lời dưới 3 câu ngắn gọn."""

    # Chuẩn bị chuỗi Prompt đầy đủ để gửi cho LLM
    full_prompt = ""
    # Nhét dữ liệu sách giáo khoa RAG vào (nếu có)
    if rag_context:
        full_prompt += f"--- THÔNG TIN RAG (Chỉ dùng nếu câu hỏi liên quan học thuật) ---\n{rag_context}\n--------------------------------------------------------------\n\n"
    # Nhét lịch sử trò chuyện cũ vào để AI nhớ ngữ cảnh
    if history_text:
        full_prompt += f"[Lịch sử hội thoại]\n{history_text}\n"
    # Nhét câu hỏi mới nhất của bé vào cuối cùng
    full_prompt += f"Câu hỏi của bé: {question}"

    # Lấy cấu hình số GPU từ môi trường (Nếu chạy CPU thì num_gpu = 0)
    num_gpu = int(os.environ.get("OLLAMA_NUM_GPU", "0"))
    # Các thông số tinh chỉnh tính cách AI
    opts = {
        "temperature": 0.45,  # Mức 0.45: Cân bằng hoàn hảo giữa tính chính xác (RAG) và tính sáng tạo (chơi đùa)
        "top_p": 0.85,        # Lọc bớt các từ ngữ quá kỳ quặc
        "num_predict": 256,   # Giới hạn số từ trả về tối đa (tránh nói quá dài)
    }
    # Nếu môi trường ép chạy CPU, đưa thẳng thông số num_gpu vào
    if num_gpu == 0:
        opts["num_gpu"] = 0

    # Đóng gói toàn bộ cấu hình, Prompt thành dạng Dictionary (JSON)
    payload = {
        "model": MODEL_NAME,         # Tên mô hình (moon-tutor)
        "prompt": full_prompt,       # Dữ liệu truyền vào (Câu hỏi + RAG)
        "system": SYSTEM_PROMPT,     # Chỉ thị cốt lõi
        "stream": stream,            # Chế độ trả về từng từ (Stream)
        "options": opts,             # Tham số cấu hình AI
        "keep_alive": -1             # GIỮ MÔ HÌNH TRONG RAM VĨNH VIỄN (Chống lag ở câu hỏi đầu tiên)
    }

    # URL trỏ tới API của phần mềm Ollama
    url = f"{OLLAMA_HOST}/api/generate"

    # Hàm ẩn phụ trách việc gửi HTTP Request xuống Ollama
    def _call_ollama(pl):
        # Chuyển Dictionary thành chuỗi JSON dạng byte
        data_bytes = json.dumps(pl).encode("utf-8")
        # Khởi tạo một POST Request
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )
        # Gửi Request đi và chờ tối đa 90 giây
        with urllib.request.urlopen(req, timeout=90) as resp:
            # Nếu bật chế độ Stream (trả về từng chữ một cho loa đọc ngay)
            if stream:
                text_acc = ""
                # Duyệt từng dòng trả về qua mạng
                for line in resp:
                    if line:
                        # Đọc cục JSON nhỏ xíu đó
                        chunk_obj = json.loads(line.decode("utf-8"))
                        # Trích xuất chữ cái AI vừa phun ra
                        chunk_text = chunk_obj.get("response", "")
                        # Nối vào chuỗi kết quả chung
                        text_acc += chunk_text
                        # Bắn chữ cái đó qua Callback để TTS (loa) hát lên
                        if on_chunk:
                            on_chunk(chunk_text)
                return text_acc
            else:
                # Nếu không Stream, chờ AI nghĩ xong toàn bộ rồi mới lấy 1 cục
                resp_json = json.loads(resp.read().decode("utf-8"))
                return resp_json.get("response", "")

    full_text = ""
    try:
        # Bắt đầu gọi hàm gửi Request
        full_text = _call_ollama(payload)
    except urllib.error.HTTPError as he:
        # Nếu Card Đồ Họa (GPU) bị lỗi 500, tự động hạ xuống chạy bằng CPU (num_gpu: 0)
        print(f"⚠️ [Ollama] Lỗi HTTP {he.code}. Đang chuyển sang chế độ CPU (num_gpu: 0)...")
        try:
            payload["options"]["num_gpu"] = 0
            full_text = _call_ollama(payload)
        except Exception as retry_err:
            print(f"❌ [Ollama Retry Error]: {retry_err}")
            return "Xin lỗi bé nha, Moon gặp chút trục trặc khi suy nghĩ. Bé thử hỏi lại xem sao nha!"
    except urllib.error.URLError as e:
        # Nếu chưa bật phần mềm Ollama
        err_msg = "Xin lỗi bé nha, Moon chưa kết nối được với não bộ Ollama. Bé bật Ollama lên giúp Moon nhé!"
        print(f"❌ [Ollama Error]: {e}")
        return err_msg
    except Exception as e:
        # Bắt các lỗi vặt khác
        print(f"❌ [Error]: {e}")
        return "Moon đang hơi buồn ngủ một xíu, bé nói lại lần nữa cho Moon nghe rõ nhé!"

    # ── Lưu lịch sử vào session ──────────────────────────────────────────────
    # Mở khóa để thêm lịch sử hội thoại
    with _session_lock:
        # Nếu đây là người dùng mới, tạo sổ tay trắng cho họ
        if session_id not in _session_history:
            _session_history[session_id] = []
        # Lưu câu hỏi của User
        _session_history[session_id].append({"role": "user",      "content": question})
        # Lưu câu trả lời của AI (nhớ xóa khoảng trắng dư thừa)
        _session_history[session_id].append({"role": "assistant", "content": full_text.strip()})
        
        # Giới hạn kích thước sổ tay để tránh nổ RAM và loạn trí nhớ AI
        max_msgs = MAX_HISTORY_TURNS * 2
        if len(_session_history[session_id]) > max_msgs:
            _session_history[session_id] = _session_history[session_id][-max_msgs:]

    # Trả về câu trả lời nguyên bản (giữ nguyên chữ Kanji, tiếng Anh)
    return full_text.strip()


def clear_session(session_id: str):
    """Xóa lịch sử của 1 người dùng cụ thể (session_id)."""
    with _session_lock:
        _session_history.pop(session_id, None)
    print(f"🧹 [TUTOR] Đã xóa lịch sử session: {session_id[:8]}")


def clear_all_sessions():
    """Xóa sạch sổ tay lịch sử của tất cả người dùng."""
    with _session_lock:
        _session_history.clear()
    print("🧹 [TUTOR] Đã xóa toàn bộ lịch sử hội thoại.")


def warmup_model():
    """
    Hàm gọi Ẩn: Được chạy ở chế độ nền lúc vừa khởi động phần mềm.
    Mục đích: Bắn 1 câu chào 'hi' giả mạo xuống Ollama, ép Ollama lấy mô hình AI
    từ ổ cứng nhét vào thanh RAM. Vì kèm theo keep_alive=-1, nó sẽ ở yên trong RAM mãi mãi.
    """
    print(f"🔥 [TUTOR] Đang nạp mô hình AI ({MODEL_NAME}) vào RAM. Vui lòng đợi vài giây...")
    try:
        # Gói tin giả mạo (Không cần stream)
        payload = {
            "model": MODEL_NAME,
            "prompt": "hi",
            "stream": False,
            "keep_alive": -1
        }
        url = f"{OLLAMA_HOST}/api/generate"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
        # Chờ tối đa 120s cho lần load ổ cứng đầu tiên
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        print("✅ [TUTOR] Đã nạp xong mô hình! Robot đã sẵn sàng phản hồi siêu tốc.")
    except Exception as e:
        print(f"⚠️ [TUTOR] Khởi động mô hình thất bại (không sao, sẽ tự load khi bạn hỏi): {e}")


# Tạo đường tắt (Alias) để các file khác gọi check_tts_ready nhanh hơn
clean_tts_text = check_tts_ready


def send_to_robot_mqtt(
    question: str,
    broker: str = "localhost",
    port: int = 1883,
    topic_display: str = "moon/cmd/display",
    topic_tts: str = "moon/ai/response"
) -> dict:
    """
    Cầu nối xuất dữ liệu tổng hợp cho nhóm phần cứng (MQTT):
    1. Lấy dữ liệu tiếng Nhật -> Đẩy xuống LED hiển thị
    2. Lấy câu trả lời sạch (TTS) -> Đẩy xuống loa ngoài phát
    """
    # 1. Trích xuất thông tin Kanji/Hiragana cho màn hình LED
    led_info = get_led_display_info(question) or {}

    # 2. Bắt AI suy nghĩ ra câu trả lời (Không Stream vì cần nguyên 1 cục để đẩy MQTT)
    full_reply = ask_moon(question, stream=False, use_rag=True)

    # 3. Lọc bỏ các ký hiệu thừa để loa đọc không bị vấp
    tts_text = check_tts_ready(full_reply)

    # Đóng gói toàn bộ thông tin
    packet = {
        "question": question,
        "full_text": full_reply,
        "tts_text": tts_text,
        "led": led_info
    }

    # 4. Phát sóng MQTT xuống phần cứng Robot
    try:
        import paho.mqtt.publish as publish
        # Bắn cho bạn phụ trách mạch LED (đẩy JSON)
        publish.single(topic_display, json.dumps(led_info, ensure_ascii=False), hostname=broker, port=port)
        # Bắn cho bạn phụ trách mạch Loa (đẩy chuỗi thô)
        publish.single(topic_tts, tts_text, hostname=broker, port=port)
        print(f"📡 [MQTT] Đã phát sóng dữ liệu tới topic '{topic_display}' và '{topic_tts}'.")
    except ImportError:
        print("ℹ️ [MQTT] Chưa cài paho-mqtt (pip install paho-mqtt). Dữ liệu đã đóng gói sẵn.")
    except Exception as e:
        print(f"⚠️ [MQTT] Không thể kết nối broker {broker}:{port} - {e}")

    return packet


# ─── Script chạy thử nghiệm độc lập ──────────────────────────────────────────
if __name__ == "__main__":
    print("🐼 === ROBOT MOON - BẠN ĐỒNG HÀNH HỌC TẬP (TEXT + LED KANJI) ===")
    sample_queries = [
        "Moon ơi, con mèo tiếng Nhật đọc sao?",
        "Bé muốn học từ quả táo tiếng Anh và tiếng Nhật!",
    ]

    for q in sample_queries:
        print(f"\n👦 Bé: {q}")
        
        # Test phần LED
        led_info = get_led_display_info(q)
        if led_info:
            print(f"📟 [MÀN HÌNH LED]: Chữ Hán: '{led_info['kanji']}' | Hiragana: '{led_info['hiragana']}'")

        # Test phần Giao tiếp & Trả lời
        print("🐼 Moon: ", end="", flush=True)
        def print_chunk(c):
            print(c, end="", flush=True)
        # Chạy Stream thật để giả lập tốc độ loa
        reply = ask_moon(q, stream=True, on_chunk=print_chunk, use_rag=True)
        print("\n" + "-" * 50)
