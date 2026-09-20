"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: brain.py (Hệ thần kinh trung ương)
--------------------------------------------------------------------------------
Đây là file quan trọng nhất, đóng vai trò điều phối toàn bộ vòng lặp giao tiếp của robot.

[CẤU TRÚC CHÍNH]
1. State Machine (VoiceState): Quản lý 5 trạng thái (BOOTING, IDLE, LISTENING, THINKING, SPEAKING).
2. Hàm start(): Khởi chạy 2 luồng ngầm:
   - _warmup_task: Nạp sẵn AI 5GB vào RAM để chống giật lag.
   - _voice_loop: Bật liên tục micro để chờ người dùng gọi 'Moon ơi'.
3. Hàm _handle_wake_word(): Bắt đầu quy trình xử lý khi nghe gọi tên.
   - Thu âm câu hỏi (_listen_for_question).
   - Gọi LLM để suy nghĩ (_run_qa_pipeline).
   - Mở lại mic 8 giây chờ hỏi tiếp (Multi-turn).
4. Hàm _run_qa_pipeline(): Nối LLM (Ollama) với TTS (Fish Audio) để phát âm thanh ngay lập tức (streaming) theo từng câu.
"""
# ==============================================================================
# brain.py — State Machine + Multi-turn Conversation Pipeline
# Cỗ máy trạng thái (State Machine) và chu trình hội thoại (Pipeline) của Robot
# ==============================================================================

import os
import re
import sys
import time
import uuid
import threading
import json

# Cấu hình chuẩn đầu ra utf-8 để Windows Console in tiếng Việt không bị lỗi font
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Thêm thư mục gốc vào đường dẫn hệ thống để import được file config
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import settings

# ─── Các bộ phận cảm giác và phát âm (Sensors & Actuators) ────────────────────
# Nhập các file xử lý âm thanh vào (vad: lọc ồn, stt: nhận diện chữ, tts: phát loa)
from server.voice import vad, stt, tts
import random

# ─── Bộ não (LLM + RAG) ────────────────────────────────────────────────────────
# Nhập hàm ask_moon (để hỏi Ollama) và clean_tts_text (để dọn dẹp chữ trước khi đọc)
try:
    from server.llm.moon_tutor import ask_moon, clean_tts_text
except ImportError:
    from llm.moon_tutor import ask_moon, clean_tts_text

# ─── Mạch giao tiếp với phần cứng Robot (MQTT) ───────────────────────────────
try:
    from server import mqtt_bridge
    _mqtt_ok = True
except Exception:
    mqtt_bridge = None
    _mqtt_ok = False

# ─── Cấu hình các thông số thời gian (Timing Settings) ─────────────────────────
# Người dùng im lặng bao lâu thì chốt xong câu hỏi? (2 giây)
QUESTION_SILENCE_SEC  = getattr(settings, "QUESTION_SILENCE_SEC", 2.0)
# Câu hỏi dài tối đa bao nhiêu giây để tránh tràn RAM (20 giây)
QUESTION_MAX_SEC      = getattr(settings, "QUESTION_MAX_SEC",    20.0)
# Cửa sổ nghe câu hỏi tiếp theo (Multi-turn): sau khi nói xong, mở mic chờ 8 giây
MULTI_TURN_WINDOW_SEC = getattr(settings, "MULTI_TURN_WINDOW_SEC", 8.0)
# Thời gian chờ AI trả lời tối đa (30 giây)
LLM_TIMEOUT_SEC       = 30.0
# Thời gian chờ Loa đọc tối đa (60 giây)
TTS_TIMEOUT_SEC       = 60.0
# Cho phép cướp lời (Barge-in): Robot đang nói mà bạn nói xen vào thì robot nín lặng
BARGE_IN_ENABLED = getattr(settings, "BARGE_IN_ENABLED", True)


# Hàm tiện ích để đọc file config hoặc lấy giá trị mặc định
def _t(attr, default="moon/noop"):
    return getattr(settings, attr, default)

# Các kênh MQTT để điều khiển LED và giao diện UI trên web
TOPIC_AI_STATE   = _t("TOPIC_AI_STATE",   "moon/ai/state")
TOPIC_AI_THINKING= _t("TOPIC_AI_THINKING","moon/ai/thinking")
TOPIC_AI_RESPONSE= _t("TOPIC_AI_RESPONSE","moon/ai/response")
TOPIC_FACE       = _t("TOPIC_FACE",       "moon/cmd/face")     # Đổi mặt cười, nháy mắt
TOPIC_BUZZ       = _t("TOPIC_BUZZ",       "moon/cmd/buzz")     # Rung hoặc báo động
TOPIC_VOICE_LOG  = _t("TOPIC_VOICE_LOG",  "moon/log/voice")    # In ra chữ người dùng vừa nói

# Biểu thức chính quy (Regex) quét các biểu tượng cảm xúc (Emoji) để bỏ ra khỏi loa
_EMOJI_RE = re.compile("[\U0001F000-\U0010FFFF\u2600-\u27BF\uFE0F]")


# ══════════════════════════════════════════════════════════════════════════════
#  STATE MACHINE (TRẠNG THÁI CỦA ROBOT)
#  Robot luôn ở 1 trong 5 trạng thái này. Việc chia trạng thái giúp tránh xung đột
#  (vd: không lỡ nghe nhầm tiếng tivi lúc đang suy nghĩ).
# ══════════════════════════════════════════════════════════════════════════════
class VoiceState:
    BOOTING   = "booting"    # Trạng thái 1: Đang nạp AI 5GB vào RAM lúc mới bật
    IDLE      = "idle"       # Trạng thái 2: Đang rảnh, chờ người dùng gọi "Moon ơi"
    LISTENING = "listening"  # Trạng thái 3: Đang mở mic thu âm câu hỏi của người dùng
    THINKING  = "thinking"   # Trạng thái 4: Đang đẩy câu hỏi cho Ollama suy nghĩ
    SPEAKING  = "speaking"   # Trạng thái 5: Đang phát âm thanh trả lời ra loa

# Mặc định khi bật máy là trạng thái Đang khởi động (BOOTING)
_state      = VoiceState.BOOTING
# Khóa an toàn (Lock) giúp nhiều luồng (thread) đổi trạng thái mà không bị vấp nhau
_state_lock = threading.Lock()
# Cờ báo hiệu Pipeline đang bận để báo cho mic (VAD) ngắt thu âm tiếng ồn
_pipeline_running = threading.Event()


def _set_state(new_state: str):
    """Đổi trạng thái của robot một cách an toàn."""
    global _state
    with _state_lock:
        if _state != new_state:
            print(f"🧠 [BRAIN] State: {_state} → {new_state}")
            _state = new_state

    # Nếu có MQTT, bắn trạng thái mới xuống cho phần cứng / UI web biết
    if _mqtt_ok:
        mqtt_bridge.publish(TOPIC_AI_STATE, new_state)

    # Đồng bộ với VAD: Nếu đang ngủ hoặc chờ gọi tên thì thả cờ cho mic lắng nghe
    if new_state in (VoiceState.IDLE, VoiceState.BOOTING):
        _pipeline_running.clear()
    else:
        # Nếu đang bận (nghe, nghĩ, nói) thì khóa luồng mic nền lại
        _pipeline_running.set()


def get_state() -> str:
    """Trả về trạng thái hiện tại."""
    return _state


def _publish(topic: str, payload):
    """Hàm trung gian gửi lệnh MQTT."""
    if _mqtt_ok:
        try:
            # Nếu payload là mảng/dictionary thì tự ép kiểu sang JSON string
            mqtt_bridge.publish(topic, payload if isinstance(payload, str) else json.dumps(payload))
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  CÁC HÀM TIỆN ÍCH (HELPERS)
# ══════════════════════════════════════════════════════════════════════════════
def _clean_for_tts(text: str) -> str:
    """Loại bỏ các ký tự Markdown thừa và Emoji trước khi đọc ra loa."""
    text = re.sub(r"[*_#`>]+", "", text)
    text = _EMOJI_RE.sub("", text)
    return text.strip()


def _extract_inline_question(trigger_text: str) -> str | None:
    """
    Nếu người dùng nói nhanh: "Moon ơi hôm nay thứ mấy?" trong cùng 1 hơi thở
    Thì hàm này sẽ tách lấy chữ "hôm nay thứ mấy?" làm câu hỏi luôn, đỡ phải hỏi lại.
    """
    lower = trigger_text.lower()
    # Lấy danh sách tên gọi robot (Moon ơi, Moon, hey Moon...)
    wake_list = sorted(
        getattr(settings, "MOON_WAKE_WORDS", ["moon"]),
        key=len, reverse=True,
    )
    for wake in wake_list:
        if wake in lower:
            # Cắt bỏ tên robot, lấy phần còn lại phía sau
            after = lower.split(wake, 1)[1].strip().lstrip(",.?!:;- ")
            # Câu hỏi hợp lệ phải có ít nhất 2 từ hoặc dài trên 4 ký tự (tránh nhận nhầm tiếng ồn)
            if len(after.split()) >= 2 or len(after) >= 5:
                return after
    return None


def _listen_for_question(timeout: float = None) -> str | None:
    """
    Quy trình nghe 1 câu hỏi hoàn chỉnh: Mở mic → Ghi âm tới lúc im lặng → Gửi lên mạng lấy chữ (STT).
    """
    # 1. Gọi hàm ghi âm thông minh của VAD
    pcm = vad.record_until_silence(
        silence_sec=QUESTION_SILENCE_SEC,  # Ngừng ghi khi im lặng 2s
        max_sec=QUESTION_MAX_SEC,          # Tối đa 20s
        wait_timeout=timeout,
        # Nếu robot đổi trạng thái (như bị tắt) thì ép dừng ghi âm ngay
        is_active_fn=lambda: _state in (VoiceState.LISTENING, VoiceState.THINKING),
    )
    if not pcm:
        # Nếu không thu được tiếng nào thì báo hủy
        return None

    # 2. Quăng file ghi âm lên Groq AI (Whisper) để chuyển thành chữ
    text = stt.transcribe_pcm(pcm, model=stt.STT_MODEL_QUESTION)
    
    # 3. Lọc ảo giác (Nhiều khi Whisper điếc nên tự bịa ra chữ 'Xin chào')
    if not text or stt.is_hallucination(text):
        print(f"🔇 [BRAIN] Không nhận ra câu hỏi: \"{text}\"")
        return None

    # 4. Gửi log câu hỏi lên giao diện UI web
    _publish(TOPIC_VOICE_LOG, text)
    print(f"❓ [BRAIN] Câu hỏi: \"{text}\"")
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  CƠ CHẾ CƯỚP LỜI (BARGE-IN MONITOR)
# ══════════════════════════════════════════════════════════════════════════════
def _barge_in_monitor(stop_event: threading.Event):
    """
    Hàm này chạy song song lúc Loa đang phát nhạc.
    Nếu nó phát hiện người dùng nói (mic thu được âm thanh to), nó sẽ lập tức TẮT LOA.
    """
    # Nếu bị cấm ở cài đặt, hoặc máy tính không có mic, thì thoát
    if not BARGE_IN_ENABLED or vad._sd is None:
        return

    import queue as _queue
    q = _queue.Queue()
    dev = vad.select_input_device()
    if dev is None:
        return

    # Callback nạp dữ liệu âm thanh vào hàng đợi
    def _cb(indata, frames, t, status):
        q.put(bytes(indata))

    try:
        # Mở mic chạy nền
        with vad._sd.InputStream(
            samplerate=vad.SAMPLE_RATE, channels=1, dtype="int16",
            device=dev[0], blocksize=vad.BLOCK_FRAMES, callback=_cb,
        ):
            # Lặp liên tục tới khi cờ stop_event báo dừng
            while not stop_event.is_set():
                try:
                    data = q.get(timeout=0.1)
                except Exception:
                    continue
                
                # Tính độ ồn của âm thanh vừa thu được
                rms = vad._rms(data)
                
                # Nếu độ ồn quá lớn (gấp 3 lần tiếng ồn môi trường) -> Xác nhận là có tiếng người nói xen vào
                if rms > vad.VAD_NOISE_FLOOR * 3:
                    print(f"🤚 [BRAIN] Barge-in detected (RMS={rms:.3f}) — dừng TTS")
                    # Tắt loa ngay lập tức
                    tts.stop_speaking()
                    break
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  QA PIPELINE: TỪ LÚC SUY NGHĨ (THINKING) ĐẾN LÚC NÓI (SPEAKING)
# ══════════════════════════════════════════════════════════════════════════════
def _run_qa_pipeline(question: str, session_id: str) -> bool:
    """
    Chu trình Hỏi-Đáp cốt lõi. Chạy 1 vòng hoàn chỉnh:
      - Đổi trạng thái sang THINKING.
      - Gửi câu hỏi cho LLM (Ollama) và RAG.
      - Nhận chữ trả về (Dạng stream từng chữ cái) -> Ghép thành từng câu ngắn.
      - Đẩy từng câu cho Fish Audio đọc (SPEAKING) ngay lập tức.
    """
    # Đổi trạng thái
    _set_state(VoiceState.THINKING)
    # Báo lên UI
    _publish(TOPIC_AI_THINKING, json.dumps({"stage": "thinking", "text": "Moon đang suy nghĩ..."}))
    # Đổi mặt robot sang biểu cảm đang suy nghĩ
    _publish(TOPIC_FACE, "questioning")

    player     = None
    barge_stop = threading.Event()
    t_start    = time.time()

    try:
        response_chunks = []
        llm_done_event  = threading.Event()
        full_response   = [""]
        sentence_buffer = [""]

        # Khởi tạo Bộ phát nhạc thông minh (Đọc câu 1 trong lúc tải ngầm câu 2)
        player = tts.SentencePlayer(on_play_start=_on_speech_start)

        # Hàm đẩy một câu vào hàng đợi của loa
        def _push_sentence(raw: str):
            s = _clean_for_tts(raw)
            if s:
                player.push(s)

        # Hàm này được gọi mỗi lần Ollama phun ra 1 chữ cái mới
        def on_chunk(chunk: str):
            # Lưu chữ mới vô danh sách
            response_chunks.append(chunk)
            partial = "".join(response_chunks)
            # Gửi đoạn văn đang sinh dở lên UI Web để hiển thị hiệu ứng đánh chữ
            _publish(TOPIC_AI_RESPONSE, json.dumps({"done": False, "text": partial}))
            
            # Cắt câu: Cứ thấy dấu chấm, dấu hỏi, chấm than là coi như xong 1 câu
            sentence_buffer[0] += chunk
            parts = re.split(r"(?<=[.!?…])\s+", sentence_buffer[0])
            if len(parts) > 1:
                # Nếu đã đủ 1 câu, đẩy luôn câu đó vào loa phát
                for part in parts[:-1]:
                    _push_sentence(part)
                # Giữ lại đoạn lẻ tẻ phía sau để ghép tiếp
                sentence_buffer[0] = parts[-1]

        # Hàm này gọi khi Ollama đã nói xong câu cuối cùng
        def on_done(text: str):
            full_response[0] = text
            _publish(TOPIC_AI_RESPONSE, json.dumps({"done": True, "text": text}))
            # Đẩy nốt phần đuôi của văn bản vào loa
            _push_sentence(sentence_buffer[0])
            sentence_buffer[0] = ""
            # Chốt hàng đợi loa
            player.finish()
            llm_done_event.set()

        # ── Gọi LLM + RAG trong một luồng (thread) phụ để không làm đứng máy ───
        def _llm_thread():
            try:
                # Gọi thẳng hàm ask_moon từ file moon_tutor.py
                result = ask_moon(
                    question=question,
                    session_id=session_id,
                    stream=True,
                    on_chunk=on_chunk,
                )
                if not llm_done_event.is_set():
                    on_done(result)
            except Exception as e:
                print(f"❌ [BRAIN] LLM lỗi: {e}")
                on_done("Xin lỗi, Moon gặp chút trục trặc. Bé thử hỏi lại nhé!")

        # Bắt đầu chạy luồng nghĩ
        threading.Thread(target=_llm_thread, daemon=True).start()

        # Chờ tối đa 30s. Nếu 30s mà AI không nhả được chữ nào thì hủy luôn
        if not llm_done_event.wait(timeout=LLM_TIMEOUT_SEC):
            print(f"⚠️  [BRAIN] LLM timeout ({LLM_TIMEOUT_SEC}s)!")
            if player:
                player.stop()
            return False

        answer = full_response[0].strip()
        if not answer:
            return False

        # Tính thời gian trễ từ lúc gọi đến lúc AI trả lời xong
        print(f"⏱  [BRAIN] Thời gian xử lý: {time.time()-t_start:.1f}s")

        # ── Chờ loa đọc hết, và cùng lúc đó chạy ngầm bộ theo dõi Cướp Lời (Barge-in) ───
        barge_thread = threading.Thread(
            target=_barge_in_monitor, args=(barge_stop,), daemon=True
        )
        barge_thread.start()

        # Chờ bộ phát loa kết thúc
        player.wait(timeout=TTS_TIMEOUT_SEC)
        # Đọc xong rồi thì tắt bộ theo dõi cướp lời đi
        barge_stop.set()

        return True

    except Exception as e:
        print(f"❌ [BRAIN] Pipeline lỗi: {e}")
        if player:
            player.stop()
        return False

    finally:
        barge_stop.set()
        if player:
            player.stop()


def _on_speech_start():
    """Hàm này tự động kích hoạt khi loa phát ra tiếng nói đầu tiên."""
    # Đổi trạng thái sang Đang Nói
    _set_state(VoiceState.SPEAKING)
    # Phát tiếng 'Bíp' nhẹ (tùy chọn)
    tts.play_tick()
    # Hiển thị mặt đang hát/nói trên màn hình LED
    _publish(TOPIC_FACE, "speaking")


# ══════════════════════════════════════════════════════════════════════════════
#  XỬ LÝ KHI NGHE ĐƯỢC TỪ KHÓA (WAKE-WORD HANDLER)
# ══════════════════════════════════════════════════════════════════════════════
# Tạo ổ khóa để tránh người dùng gọi liên tiếp 2 3 câu cùng lúc
_pipeline_lock = threading.Lock()


def _handle_wake_word(trigger_text: str):
    """
    Chạy khi VAD phát hiện được chữ "Moon ơi" từ người dùng.
    """
    # Nếu người dùng gọi khi máy mới bật, AI chưa kịp nạp vào RAM
    if _state == VoiceState.BOOTING:
        print("⚠️  [BRAIN] Wake word trong lúc đang khởi động.")
        tts.speak("Moon vẫn đang ngái ngủ, chờ mình vài giây nhé!")
        return

    # Cố gắng lấy khóa (Lock). Nếu khóa bị người khác chiếm (robot đang bận) -> Bỏ qua lời gọi
    if not _pipeline_lock.acquire(blocking=False):
        print("⚠️  [BRAIN] Đang bận — bỏ qua wake-word.")
        return

    # Sinh mã ngẫu nhiên cho buổi trò chuyện (Để AI lưu đúng lịch sử)
    session_id = str(uuid.uuid4())
    print(f"🐼 [BRAIN] Wake! Trigger: \"{trigger_text}\" | Session: {session_id[:8]}")

    try:
        # Phát ra tiếng bíp nhỏ để báo hiệu "Đã nghe"
        tts.play_beep()
        # Rung mô-tơ trên người robot (nếu có lắp phần cứng)
        _publish(TOPIC_BUZZ, "on")
        time.sleep(0.1)
        _publish(TOPIC_BUZZ, "off")
        # Chuyển mặt robot sang vui vẻ
        _publish(TOPIC_FACE, "happy")

        # ── Lấy câu hỏi ───────────────────────────────────────────────────────
        _set_state(VoiceState.LISTENING)
        _publish(TOPIC_AI_THINKING, json.dumps({"stage": "listening", "text": "Moon đang lắng nghe..."}))

        # Thử xem có câu hỏi nào dính liền sau tên gọi không (VD: Moon ơi mấy giờ rồi)
        question = _extract_inline_question(trigger_text) 
        
        # Nếu chỉ gọi trần trụi "Moon ơi"
        if not question:
            # Random một câu chào thân thiện
            greetings = [
                "Mình đây, bạn cần hỏi gì à?",
                "Dạ Moon nghe đây!",
                "Moon đây, bạn hỏi đi!",
                "Chào bạn, mình có thể giúp gì?"
            ]
            # Phát câu chào ra loa
            tts.speak(random.choice(greetings))
            
            # Đợi mở mic lên nghe câu hỏi thực sự
            question = _listen_for_question()

        if not question:
            print("🔇 [BRAIN] Không nghe được câu hỏi.")
            return

        # ── VÒNG LẶP HỘI THOẠI ĐA LƯỢT (MULTI-TURN) ───────────────────────────
        # Vòng lặp này giúp bạn hỏi tới tấp mà không cần gọi lại chữ "Moon ơi"
        while question:
            # Chạy toàn bộ quy trình: Nghĩ -> Nói
            _run_qa_pipeline(question, session_id)

            # ── WINDOW LẮNG NGHE LẠI ──────────────────────────────────────────
            _set_state(VoiceState.LISTENING)
            _publish(TOPIC_AI_THINKING, json.dumps({
                "stage": "listening",
                "text": f"Bạn có muốn hỏi thêm gì không? (còn {int(MULTI_TURN_WINDOW_SEC)}s)",
            }))
            _publish(TOPIC_FACE, "questioning")

            # Mở mic đợi 8 giây xem có ai hỏi tiếp không
            print(f"👂 [BRAIN] Cửa sổ Lắng nghe mở {MULTI_TURN_WINDOW_SEC}s — chờ câu tiếp theo...")
            question = _listen_for_question(timeout=MULTI_TURN_WINDOW_SEC)

            # Nếu 8 giây trôi qua mà im lặng thì BREAK thoát khỏi vòng lặp
            if not question:
                print("⏰ [BRAIN] Listening Window hết hạn — về IDLE.")
                break

            print(f"🔄 [BRAIN] Câu tiếp theo (multi-turn): \"{question}\"")

    except Exception as e:
        print(f"❌ [BRAIN] Lỗi pipeline: {e}")

    finally:
        # Luôn phải dọn dẹp và reset về IDLE (Đang rảnh) khi xong việc
        _set_state(VoiceState.IDLE)
        _publish(TOPIC_FACE, "neutral")
        _publish(TOPIC_AI_THINKING, json.dumps({"stage": "idle"}))
        # Mở khóa để ai muốn gọi Moon ơi tiếp thì gọi
        _pipeline_lock.release()
        print("✅ [BRAIN] Pipeline kết thúc → IDLE")


# ══════════════════════════════════════════════════════════════════════════════
#  VÒNG LẶP CHÍNH CỦA TAI (NGHE LÉN VÀ ĐỢI GỌI TÊN)
# ══════════════════════════════════════════════════════════════════════════════
def _voice_loop():
    """
    Hàm này chạy ẩn vĩnh viễn lúc máy rảnh rỗi.
    Nó sẽ ghi từng đoạn âm thanh nhỏ 0.5s, quăng lên mạng xem có phải chữ 'Moon ơi' không.
    """
    import queue as _queue
    import collections

    if vad._sd is None or stt.groq_client is None:
        print("❌ [BRAIN] Thiếu thư viện hoặc API Key — không thể nghe.")
        return

    print("👂 [BRAIN] Voice loop bắt đầu. Nói \"Moon\" để gọi mình!")

    # Tìm Microphone xịn nhất
    dev = vad.select_input_device()
    while dev is None:
        time.sleep(2)
        dev = vad.select_input_device()

    q = _queue.Queue()

    def _cb(indata, frames, t, status):
        q.put(bytes(indata))

    # Hàm xử lý các clip âm thanh bị cắt ra
    def _emit_clip(audio: bytes):
        def _work():
            # Nếu robot đang bận nói hoặc bận nghĩ thì điếc
            if _pipeline_running.is_set():
                return
            if tts.is_speaking():
                return

            # Gọi Groq dịch file âm thanh sang text
            text = stt.transcribe_dual(audio)
            # Lọc rác
            if not text or stt.is_hallucination(text):
                return

            # Nếu trong chữ có chứa từ khóa (Moon)
            if stt.contains_wake_word(text):
                # Bắt đầu chạy pipeline Wake-word trên một luồng khác
                threading.Thread(
                    target=_handle_wake_word,
                    args=(text,),
                    daemon=True,
                ).start()

        threading.Thread(target=_work, daemon=True).start()

    min_blocks   = int(vad.MIN_SPEECH_SEC * 1000 / vad.BLOCK_MS)
    preroll_max  = int(1.5 * 1000 / vad.BLOCK_MS)
    
    # Bắt đầu mở Microphone
    with vad._sd.InputStream(
        samplerate=vad.SAMPLE_RATE, channels=1, dtype="int16",
        device=dev[0], blocksize=vad.BLOCK_FRAMES, callback=_cb,
    ):
        # ── Đo độ ồn môi trường mất 1s lúc khởi động ────────────────────────
        samples = []
        t0 = time.time()
        while time.time() - t0 < 1.0:
            try:
                data = q.get(timeout=2)
            except _queue.Empty:
                break
            if time.time() - t0 < 0.4:
                continue
            samples.append(vad._rms(data))
        samples.sort()
        ambient = samples[len(samples) // 2] if samples else 0.0
        # Thiết lập ngưỡng nhạy cảm dựa trên độ ồn thực tế
        threshold_base = max(vad.VAD_NOISE_FLOOR, ambient * vad.VAD_AMBIENT_MULT)
        print(f"🎚️  [BRAIN] Ồn nền đo được: {ambient:.3f} → Ngưỡng lọc ồn mới: {threshold_base:.3f}")

        # ── Tiến trình nghe lén liên tục ─────────────────────────────────────
        state_vad = "idle"
        preroll   = collections.deque(maxlen=preroll_max)
        clip, peak, speech_blocks = [], 0.0, 0
        last_speech, speech_start = 0.0, 0.0

        # Nếu đang gọi tên mà im lặng 0.45s là chốt luôn gửi đi, giúp robot phản xạ siêu nhanh
        WAKE_SILENCE = getattr(settings, "WAKE_SILENCE_SEC", 0.45)

        while True:
            # Nếu robot bắt đầu làm việc khác, xóa sạch bộ nhớ nghe lén đi
            if _pipeline_running.is_set() or tts.is_speaking():
                while not q.empty():
                    try:
                        q.get_nowait()
                    except _queue.Empty:
                        break
                state_vad, clip, peak, speech_blocks = "idle", [], 0.0, 0
                preroll.clear()
                time.sleep(0.1)
                continue

            try:
                data = q.get(timeout=1.0)
            except _queue.Empty:
                continue

            now = time.time()
            # Tính năng lượng (to nhỏ) của cục âm thanh
            rms = vad._rms(data)
            rel = peak * 0.55 if state_vad == "speech" else 0.0
            
            # Công thức xác định xem CÓ TIẾNG NÓI hay không
            is_sp = (
                rms >= threshold_base
                and rms >= rel
                and vad._spectral_flatness(data) < vad.SPEECH_FLAT_MAX
            )

            # Máy trạng thái nhỏ: Bắt đầu có tiếng -> đang nói -> im lặng -> xuất file
            if state_vad == "idle":
                if is_sp:
                    state_vad = "speech"
                    speech_start = now
                    clip = list(preroll) + [data]
                    peak = rms
                    speech_blocks = 1
                    last_speech = now
                else:
                    preroll.append(data)

            elif state_vad == "speech":
                if is_sp:
                    clip.append(data)
                    peak = max(peak, rms)
                    speech_blocks += 1
                    last_speech = now
                else:
                    clip.append(data)
                    # Nếu thấy im lặng đủ lâu (0.45s) thì chốt clip
                    if now - last_speech >= WAKE_SILENCE:
                        if speech_blocks >= min_blocks:
                            _emit_clip(b"".join(clip))
                        # Chốt xong thì reset lại mọi thứ
                        state_vad = "idle"
                        clip, peak, speech_blocks = [], 0.0, 0
                        preroll.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API (CÁC HÀM GỌI TỪ FILE MAIN)
# ══════════════════════════════════════════════════════════════════════════════
def start():
    """
    Hàm này được chạy đầu tiên khi khởi động file python.
    Nó tạo 2 luồng ngầm (nạp AI và nghe lén) rồi bỏ mặc chúng tự chạy.
    """
    print("🧠 [BRAIN] ═══════════════════════════════════════")
    print("🧠 [BRAIN]  Robot Moon — Voice AI khởi động")
    print("🧠 [BRAIN]  Pipeline: VAD → Groq STT → LLM+RAG → Fish TTS")
    print("🧠 [BRAIN] ═══════════════════════════════════════")

    # 1. Luồng Warm-up: Dùng để nạp file 5GB Ollama vào RAM máy tính
    def _warmup_task():
        # Đổi hình con mắt ngủ
        _publish(TOPIC_FACE, "sleeping")
        tts.speak("Moon đang thức dậy, các bạn đợi một lát nhé!")
        
        try:
            from server.llm.moon_tutor import warmup_model
            # Ép Ollama Load lên RAM
            warmup_model()
            
            # Nạp xong rồi thì báo cáo mặt cười và tiếng tút
            _publish(TOPIC_FACE, "happy")
            tts.play_tick()
            tts.speak("Moon đã sẵn sàng, hãy gọi Moon ơi nhé!")
        except Exception as e:
            print(f"⚠️ [BRAIN] Không thể gọi warmup_model: {e}")
        finally:
            # Trả trạng thái về IDLE
            _set_state(VoiceState.IDLE)
            
    threading.Thread(target=_warmup_task, daemon=True).start()

    # 2. Bật luồng nghe lén liên tục
    vt = threading.Thread(target=_voice_loop, daemon=True)
    vt.start()
    print("✅ [BRAIN] Voice loop đang chạy (Whisper Wake-word).")


def stop():
    """Tắt công tắc, dừng mọi hành động của robot."""
    tts.stop_speaking()
    _set_state(VoiceState.IDLE)
    print("🛑 [BRAIN] Voice AI dừng.")


# ─── Nếu vô tình gọi file này độc lập ─────────────────────────────────────────
if __name__ == "__main__":
    start()
    print("▶  Đang chạy — nhấn Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()
        print("👋 Tạm biệt!")
