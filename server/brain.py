"""
Brain — Bộ não trung tâm của Robot Panda
=========================================
Pipeline chính:
  Người nói
    → voice.py (VAD + Groq STT) → transcript text
      → Phát hiện wake-word "Panda"
        → Nghe câu hỏi (nếu cần)
          → llm.py (DeepSeek/Groq) → stream câu trả lời
            → tts.py (Fish Audio) → phát âm thanh
              → Quay về standby, tiếp tục nghe

Modules kết hợp:
  - server/voice.py  : STT (Groq Whisper)
  - server/llm.py    : LLM (DeepSeek / Groq)
  - server/tts.py    : TTS (Fish Audio)
  - server/vision.py : CV (YuNet face + FER+ emotion)
  - server/mqtt_bridge : giao tiếp với robot và dashboard
"""

import time
import threading
import json
import re
import sys
import os

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

from config import settings
from server import mqtt_bridge
from server.vision import start_vision
from server.voice import (register_callbacks, continuous_listen_loop,
                          listen_for_question, pause_listening, resume_listening,
                          transcribe_bytes, _is_hallucination, _contains_wake_word,
                          STT_MODEL_QUESTION, _levenshtein, _strip_diacritics)
from server.tts import speak, SentencePlayer
from server import tts   # module object — cho tts.play_beep()/play_tick()
from server import llm
from server.topics import classify_topic, TOPIC_LABELS

# ─── Hằng số timeout ─────────────────────────────────────────────────────────
LLM_TIMEOUT_SEC = 30.0   # Nếu LLM không trả lời sau 30s → tự về standby
TTS_TIMEOUT_SEC = 60.0   # Nếu TTS treo sau 60s → tự về standby

# Emoji → LOẠI khỏi câu TTS: Fish Audio "đọc" emoji 🕐😊 thành tiếng cười/kỳ lạ.
# (Emoji vẫn giữ trên dashboard chat — chỉ bỏ ở phần phát thanh)
_EMOJI_RE = re.compile("[\U0001F000-\U0010FFFF\u2600-\u27BF\uFE0F]")

# ─── Global states ────────────────────────────────────────────────────────────
current_state      = "IDLE"
last_state_change  = time.time()
obstacle_detected  = False
button_pressed     = False

# ─── Tracking person & OLED Face ─────────────────────────────────────────────
greeted              = False
last_person_seen_time = 0
last_greet_time      = 0.0   # chống chào liên tục khi face detection nhấp nháy
_pending_face        = None   # debounce cảm xúc mirror: phải ổn định 1.5s mới đổi OLED
_pending_face_since  = 0.0
current_oled_face    = "neutral"
last_reported_status = {"emotion": None, "action": None}

# ─── Voice / AI state ─────────────────────────────────────────────────────────
# "standby"   — liên tục nghe, chờ wake-word
# "listening" — đã nghe thấy "Panda", đang thu câu hỏi
# "thinking"  — đang gọi LLM
# "speaking"  — TTS đang phát
voice_ai_state = "standby"
_voice_lock    = threading.Lock()
_current_topic = ["chat"]   # chủ đề hiện tại của phiên hỏi-đáp (cho caption OLED)


# ═══════════════════════════════════════════════════════════════════════════════
#  STATE MACHINE
# ═══════════════════════════════════════════════════════════════════════════════

def change_state(new_state: str):
    global current_state, last_state_change
    if current_state != new_state:
        print(f"🧠 [BRAIN] State: {current_state} → {new_state}")
        current_state     = new_state
        last_state_change = time.time()
        handle_state_entry(new_state)


def handle_state_entry(state: str):
    """Xử lý hành động khi vào state mới — chạy trong thread riêng."""
    def _run():
        global current_oled_face
        if state == "IDLE":
            current_oled_face = "neutral"
            mqtt_bridge.publish(settings.TOPIC_FACE, "neutral")
            mqtt_bridge.publish(settings.TOPIC_MOVE, "stop")

        elif state == "GREETING":
            current_oled_face = "happy"
            mqtt_bridge.publish(settings.TOPIC_FACE, "happy")
            mqtt_bridge.publish(settings.TOPIC_MOVE, "forward")
            mqtt_bridge.publish(settings.TOPIC_ARM,  "wave")
            mqtt_bridge.publish(settings.TOPIC_TEXT, "XIN CHAO!")
            speak("Xin chào bạn! Mình là Panda!")
            time.sleep(2)
            mqtt_bridge.publish(settings.TOPIC_MOVE, "stop")
            change_state("IDLE")

        elif state == "COMFORT":
            current_oled_face = "sad"
            mqtt_bridge.publish(settings.TOPIC_FACE, "sad")
            speak("Đừng buồn, có mình ở đây rồi.")
            time.sleep(2)
            change_state("IDLE")

        elif state == "OBSTACLE":
            current_oled_face = "surprised"
            mqtt_bridge.publish(settings.TOPIC_MOVE, "stop")
            mqtt_bridge.publish(settings.TOPIC_FACE, "surprised")
            mqtt_bridge.publish(settings.TOPIC_BUZZ, "on")
            mqtt_bridge.publish(settings.TOPIC_TEXT, "OOPS!")
            time.sleep(1)
            mqtt_bridge.publish(settings.TOPIC_BUZZ, "off")
            change_state("IDLE")

        elif state == "ANIMATION":
            current_oled_face = "happy"
            mqtt_bridge.publish(settings.TOPIC_FACE, "happy")
            mqtt_bridge.publish(settings.TOPIC_ARM,  "wave")
            time.sleep(2)
            change_state("IDLE")

    threading.Thread(target=_run, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
#  MQTT: STATUS TỪ ROBOT
# ═══════════════════════════════════════════════════════════════════════════════

def on_status_received(client, userdata, msg):
    global obstacle_detected, button_pressed
    try:
        data = json.loads(msg.payload.decode())
        dist = data.get("dist", 100)
        btn  = data.get("btn", 0)

        if dist < 15:
            if not obstacle_detected:
                obstacle_detected = True
                if current_state != "OBSTACLE":
                    change_state("OBSTACLE")
        else:
            obstacle_detected = False

        if btn == 1:
            button_pressed = True
            if current_state != "ANIMATION":
                change_state("ANIMATION")
        else:
            button_pressed = False

    except Exception as e:
        print(f"❌ [BRAIN] Lỗi đọc status: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  VISION CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

def on_vision_update(person_detected: bool, emotion: str, action: str):
    global current_state, last_reported_status, greeted, last_person_seen_time, current_oled_face, last_greet_time, _pending_face, _pending_face_since
    now = time.time()

    if person_detected:
        last_person_seen_time = now

        # Cập nhật UI nếu emotion/action thay đổi
        if emotion != last_reported_status["emotion"] or action != last_reported_status["action"]:
            print(f"👁️  [BRAIN] Emotion: {emotion} | Action: {action}")
            # vision.py publishes full status, including absence and confidence.
            last_reported_status["emotion"] = emotion
            last_reported_status["action"]  = action

        # Chào lần đầu khi thấy người (có cooldown — không chào lại liên tục)
        if (not greeted and current_state == "IDLE" and voice_ai_state == "standby"
                and (now - last_greet_time) > getattr(settings, "GREET_COOLDOWN_SEC", 60.0)):
            greeted = True
            last_greet_time = now
            change_state("GREETING")
            return

        # Mirror cảm xúc người dùng lên OLED — MẶC ĐỊNH TẮT để idle TỰ CHỦ
        # (Panda tự diễn biểu cảm; bật lại bằng EMOTION_MIRROR=True trong settings)
        if (getattr(settings, "EMOTION_MIRROR", False)
                and current_state == "IDLE" and voice_ai_state == "standby"):
            face_map = {
                "happy": "happy", "sad": "sad",
                "angry": "angry", "surprised": "surprised",
            }
            face_target = face_map.get(emotion, "neutral")
            if face_target != current_oled_face:
                if face_target != _pending_face:
                    _pending_face = face_target
                    _pending_face_since = now
                elif now - _pending_face_since >= 1.5:
                    current_oled_face = face_target
                    mqtt_bridge.publish(settings.TOPIC_FACE, face_target)
                    _pending_face = None
    else:
        # Không thấy người liên tục > grace → mới coi là người đã rời đi
        if now - last_person_seen_time > getattr(settings, "PERSON_LOST_GRACE_SEC", 10.0):
            greeted = False
            if current_oled_face != "neutral" and current_state == "IDLE":
                current_oled_face = "neutral"
                mqtt_bridge.publish(settings.TOPIC_FACE, "neutral")


# ═══════════════════════════════════════════════════════════════════════════════
#  VOICE AI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _set_voice_ai_state(state: str):
    """Cập nhật state và publish lên MQTT để dashboard cập nhật badge."""
    global voice_ai_state
    voice_ai_state = state
    mqtt_bridge.publish(settings.TOPIC_AI_STATE, state)
    print(f"🐼 [BRAIN] AI state → {state}")

    # Pause/resume vòng lặp nghe để tránh 2 luồng mở mic cùng lúc
    # và tránh Panda tự nghe thấy giọng mình nói
    if state == "standby":
        resume_listening()
    else:
        pause_listening()


def _publish_thinking(stage: str, text: str = ""):
    """Publish trạng thái xử lý AI lên dashboard (chat panel)."""
    mqtt_bridge.publish(settings.TOPIC_AI_THINKING, json.dumps({
        "stage": stage,
        "text":  text,
    }))


def _topic_caption(tid: str, question: str) -> str:
    """Caption dữ liệu thật dưới emoji chủ đề (kiểu Vector): giờ thật, nhiệt độ thật..."""
    if tid == "time":
        from datetime import datetime
        return datetime.now().strftime("%H:%M")
    if tid == "weather":
        wx = llm._maybe_weather(question)
        if wx:
            m = re.search(r"(-?\d+(?:\.\d+)?)°C", wx)
            if m:
                return m.group(1) + "°C"
    return TOPIC_LABELS.get(tid, "")


def _correct_asr(text: str) -> str:
    """ASR post-editing: tự sửa lỗi chính tả/nhận dạng giọng nói trước khi
    hiển thị OLED + phân loại chủ đề + hỏi LLM — đẹp hơn và chính xác hơn
    (vd: "Thời tiệc bây giờ..." → "Thời tiết bây giờ như thế nào?").
    Gate an toàn: chỉ nhận bản sửa nếu cùng số từ và mỗi từ chỉ khác ≤1 ký tự
    (bỏ dấu) — tức chỉ sửa dấu/từ gần đồng âm, KHÔNG cho viết lại lung tung."""
    if not text or len(text) < 4:
        return text
    fixed = llm.quick(
        "Khôi phục câu gốc người dùng đã nói, từ bản chép giọng nói bị lỗi dưới đây. "
        "Hãy dựa vào PHÁT ÂM gần đúng để suy đoán câu đúng chính tả. "
        "Giữ nguyên tên riêng như 'Panda' nếu có. Chỉ trả về câu khôi phục.\n" +
        "Ví dụ:\n"
        "- 'Hơ tiếp hôm nay như thế nào?' → 'Thời tiết hôm nay như thế nào?'\n"
        "- 'bây giờ là mẹ giờ' → 'Bây giờ là mấy giờ?'\n"
        "- 'ngon bị nào cao nhất thế giới' → 'Ngọn núi nào cao nhất thế giới?'\n"
        "- 'hai bạn nàng' / 'hey tanda' → 'Hey Panda'\n"
        "Câu cần sửa: " + text)
    fixed = (fixed or "").strip().strip('"').strip()
    if not fixed:
        return text
    # Sanity gate nhẹ: độ dài và số từ không lệch nhiều → chặn viết lại lung tung
    a = _strip_diacritics(text).split()
    b = _strip_diacritics(fixed).split()
    if abs(len(fixed) - len(text)) <= max(8, len(text) // 2) and abs(len(a) - len(b)) <= 1:
        return fixed
    return text


_TOPIC_ENUM = ("time,weather,math,story,emotion,food,music,sport,animal,nature,"
               "place,study,tech,people,game,science,history,geography,space,"
               "health,money,movie,chat")


def _correct_and_classify(text: str):
    """HYBRID tiết kiệm trễ: 1 call compound-mini vừa sửa lỗi chính tả vừa
    phân loại chủ đề → (topic_id | None, câu đã sửa)."""
    r = llm.quick(
        "Bạn là bộ sửa lỗi + phân loại cho trợ lý giọng nói tiếng Việt.\n"
        "Chọn 1 chủ đề phù hợp nhất và sửa lỗi chính tả câu chép từ giọng nói.\n"
        f"Danh sách chủ đề: {_TOPIC_ENUM}\n"
        "Ví dụ:\n"
        "- 'Hơ tiếp hôm nay như thế nào?' → weather|Thời tiết hôm nay như thế nào?\n"
        "- 'bây giờ là mẹ giờ' → time|Bây giờ là mấy giờ?\n"
        "- 'Tích phân là gì' → math|Tích phân là gì?\n"
        "Trả về đúng 1 dòng dạng: topic_id|câu_đã_sửa\n"
        f"Câu: {text}")
    if not r or "|" not in r:
        return None, text
    line = r.strip().splitlines()[0]
    tid, _, fixed = line.partition("|")
    tid = tid.strip().lower()
    fixed = fixed.strip().strip('"')
    if tid not in _TOPIC_ENUM.split(","):
        tid = None
    if not fixed or abs(len(fixed) - len(text)) > max(8, len(text) // 2):
        fixed = text
    return tid, fixed


_EMOTIONS = ("happy", "sad", "surprised", "angry", "love", "wink",
             "sleepy", "dizzy", "cool", "cute", "neutral")


def _classify_emotion(question: str, answer: str):
    """Chọn 1 trong 11 biểu cảm OLED cho khoảnh khắc SAU trả lời,
    dựa vào cả câu hỏi lẫn câu trả lời (ngữ cảnh hội thoại)."""
    r = llm.quick(
        "Chọn đúng 1 cảm xúc phù hợp nhất cho robot diễn SAU khi trả lời câu hỏi.\n"
        f"Danh sách: {', '.join(_EMOTIONS)}\n"
        "Gợi ý: được khen → wink/cute; sự thật ấn tượng → surprised/cool; an ủi → sad/love; "
        "chuyện vui → happy; câu hỏi hóc búa/gây rối → dizzy; tâm sự đêm khuya → sleepy.\n"
        f"Câu hỏi: {question[:200]}\nCâu trả lời: {answer[:200]}\n"
        "Chỉ trả về 1 từ.")
    r = (r or "").strip().lower()
    for e in _EMOTIONS:
        if e in r:
            return e
    return None


def _publish_answer_caption(answer: str):
    """Sau khi LLM trả lời: tóm tắt trọng tâm thành nhãn ≤12 ký tự (1+1=2, Everest...)
    và cập nhật live lên OLED trong lúc TTS vẫn đang đọc."""
    cap = llm.quick(
        "Tạo nhãn OLED TỐI ĐA 12 ký tự tóm tắt TRỌNG TÂM câu trả lời sau "
        "(ví dụ: 1+1=2, 29°C, Everest, 23:47). Chỉ trả về nhãn, không giải thích.\n"
        "Câu trả lời: " + answer[:400])
    cap = (cap or "").strip().strip("\"'`*. ")
    cap = _EMOJI_RE.sub("", cap).strip()   # caption neon không kèm emoji màu
    if 0 < len(cap) <= 12:
        mqtt_bridge.publish(settings.TOPIC_AI_TOPIC, json.dumps({
            "id": _current_topic[0], "cap": cap,
        }))


def _extract_inline_question(trigger_text: str) -> str | None:
    """
    Nếu user nói "Panda hôm nay thời tiết thế nào" trong 1 câu →
    trích xuất phần sau wake-word làm câu hỏi luôn, không cần nghe lại.
    """
    lower = trigger_text.lower()
    wake_list = getattr(settings, "PANDA_WAKE_WORDS", ["panda"])
    # Sắp xếp từ dài nhất đến ngắn nhất để ưu tiên cụm từ đầy đủ (VD: "hai phan ta" trước "phan ta")
    sorted_wakes = sorted(wake_list, key=len, reverse=True)

    for wake in sorted_wakes:
        if wake in lower:
            after = lower.split(wake, 1)[1].strip()
            after = after.lstrip(",.?!:;- ")
            if len(after) >= 2:
                return after
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  PIPELINE CHÍNH: Wake-word → LLM → TTS
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_wake_word(trigger_text: str):
    """
    Pipeline đầy đủ khi phát hiện wake-word "Panda":

    1. Nghe câu hỏi (hoặc dùng inline nếu có)
    2. Gửi lên LLM → stream câu trả lời lên dashboard
    3. TTS phát câu trả lời bằng Fish Audio
    4. Quay về standby

    Được bảo vệ bởi try/finally → luôn trả về standby dù có lỗi.
    """
    global voice_ai_state

    # Chỉ cho phép 1 pipeline chạy cùng lúc
    with _voice_lock:
        if voice_ai_state != "standby":
            print("⚠️  [BRAIN] Đang bận — bỏ qua wake-word.")
            return
        _set_voice_ai_state("listening")

    print(f"🐼 [BRAIN] Wake-word! Trigger: \"{trigger_text}\"")

    player = None   # SentencePlayer — tạo trước LLM, cleanup trong finally
    _t_wake = time.time()   # đồng hồ bấm giờ từng chặng (soi trễ)
    try:
        # Ack kiểu Anki Vector: bíp kép + buzz + face vui báo "tôi nghe thấy bạn gọi"
        tts.play_beep()
        mqtt_bridge.publish(settings.TOPIC_BUZZ, "on")
        time.sleep(0.15)
        mqtt_bridge.publish(settings.TOPIC_BUZZ, "off")
        mqtt_bridge.publish(settings.TOPIC_FACE, "happy")
        # ── BƯỚC 1: Lấy câu hỏi ──────────────────────────────────────────────
        _publish_thinking("listening", "Panda đang lắng nghe...")
        mqtt_bridge.publish(settings.TOPIC_FACE, "questioning")  # ? + spinning ring

        question = _extract_inline_question(trigger_text)

        if question:
            print(f"✅ [BRAIN] Câu hỏi inline: \"{question}\"")
        else:
            print("🎤 [BRAIN] Nghe câu hỏi...")
            question = listen_for_question()

        if not question:
            print("🔇 [BRAIN] Không nghe được câu hỏi.")
            _publish_thinking("idle")
            return   # finally sẽ reset state

        # ASR post-editing + phân loại chủ đề HYBRID:
        # keyword bắt được → dùng ngay (0ms); hụt → LLM chọn (gộp chung call sửa lỗi)
        kw = classify_topic(question)
        llm_topic, question = _correct_and_classify(question)
        print(f"⏱ [BRAIN] wake→câu hỏi sẵn sàng: {time.time()-_t_wake:.1f}s")

        # ── BƯỚC 2: Hiển thị câu hỏi người dùng lên màn hình LED ─────────────
        _publish_thinking("question", question)
        # Chủ đề câu hỏi → OLED hiện icon + caption dữ liệu thật khi trả lời
        _tid = kw if kw != "chat" else (llm_topic or "chat")
        _current_topic[0] = _tid
        mqtt_bridge.publish(settings.TOPIC_AI_TOPIC, json.dumps({
            "id": _tid, "cap": _topic_caption(_tid, question),
        }))
        print(f"❓ [BRAIN] Câu hỏi: \"{question}\"")
        time.sleep(getattr(settings, "QUESTION_DISPLAY_SEC", 0.4))  # đủ để OLED hiện text, không gây lag

        # ── BƯỚC 3: Chuyển sang chế độ suy nghĩ ──────────────────────────────
        # OLED GIỮ transcript đã nghe (mode 'hearing') trong suốt lúc thinking —
        # người dùng thấy Panda "đọc lại" những gì đã nghe; dots thinking chỉ
        # hiện trên dashboard (không publish face ai-thinking nữa).
        _set_voice_ai_state("thinking")
        _publish_thinking("thinking", "Panda đang suy nghĩ...")

        response_chunks  = []
        llm_done_event   = threading.Event()
        full_response    = [""]  # list để có thể ghi từ closure

        # ── TTS streaming theo câu: câu nào xong trước đọc trước (Vector-like) ──
        def _on_speech_start():
            """Audio đầu tiên bắt đầu vang lên → tick + chuyển state speaking."""
            print(f"⏱ [BRAIN] wake→tiếng đầu tiên: {time.time()-_t_wake:.1f}s")
            tts.play_tick()
            _set_voice_ai_state("speaking")
            mqtt_bridge.publish(settings.TOPIC_FACE, "speaking")  # equalizer bars

        player = SentencePlayer(on_play_start=_on_speech_start)
        sentence_buffer = [""]

        def _push_sentence(raw: str):
            """Làm sạch markdown + emoji rồi đẩy 1 câu vào hàng đợi TTS."""
            s = re.sub(r"[*_#`>]+", "", raw)
            s = _EMOJI_RE.sub("", s).strip()
            if s:
                player.push(s)

        def on_thinking(stage: str):
            if stage == "thinking":
                _publish_thinking("thinking", "Panda đang suy nghĩ...")
                print("🧠 [BRAIN] LLM thinking...")
            elif stage == "answering":
                _publish_thinking("answering", "Panda đang soạn câu trả lời...")
                print("✍️  [BRAIN] LLM answering...")

        def on_chunk(chunk: str):
            """Stream từng token lên dashboard + tách câu đẩy sang TTS ngay."""
            response_chunks.append(chunk)
            partial = "".join(response_chunks)
            mqtt_bridge.publish(settings.TOPIC_AI_RESPONSE, json.dumps({
                "done": False,
                "text": partial,
            }))
            # Tách câu tại dấu kết thúc (. ! ? …) — câu xong trước đọc trước
            sentence_buffer[0] += chunk
            parts = re.split(r"(?<=[.!?…])\s+", sentence_buffer[0])
            if len(parts) > 1:
                for part in parts[:-1]:
                    _push_sentence(part)
                sentence_buffer[0] = parts[-1]

        def on_done(text: str):
            """LLM hoàn thành — lưu full text, flush câu cuối và signal."""
            full_response[0] = text
            mqtt_bridge.publish(settings.TOPIC_AI_RESPONSE, json.dumps({
                "done": True,
                "text": text,
            }))
            _publish_thinking("done")
            _push_sentence(sentence_buffer[0])   # phần cuối không có dấu kết thúc
            sentence_buffer[0] = ""
            player.finish()
            # Caption = trọng tâm câu TRẢ LỜI (1+1=2, Everest...) — chạy nền
            threading.Thread(target=_publish_answer_caption,
                             args=(text,), daemon=True).start()
            llm_done_event.set()

        # Chạy LLM trong thread riêng (non-blocking) với timeout
        llm_thread = llm.chat_async(
            question=question,
            on_thinking=on_thinking,
            on_chunk=on_chunk,
            on_done=on_done,
        )

        # Chờ LLM với timeout
        finished = llm_done_event.wait(timeout=LLM_TIMEOUT_SEC)
        if not finished:
            print(f"⚠️  [BRAIN] LLM timeout sau {LLM_TIMEOUT_SEC}s!")
            player.stop()
            return   # finally reset state

        answer = full_response[0].strip()
        if not answer:
            print("⚠️  [BRAIN] LLM trả về rỗng.")
            return

        # ── BƯỚC 4: Chờ TTS phát xong (đã bắt đầu từ khi LLM ra câu đầu) ─────
        print(f"🔊 [BRAIN] TTS: \"{answer[:60]}{'...' if len(answer) > 60 else ''}\"")
        if not player.wait(timeout=TTS_TIMEOUT_SEC):
            # Watchdog: phát treo (MCI kẹt...) → ngắt để giải phóng pipeline,
            # nhờ đó finally mới chạy và OLED trở về neutral
            print("⚠️  [BRAIN] TTS không kết thúc đúng hạn — ngắt phát.")
            player.stop()

        # ── BƯỚC 5: Biểu cảm kết thúc — Panda "có hồn" theo ngữ cảnh hội thoại ──
        emo = _classify_emotion(question, answer)
        if emo and emo != "neutral":
            print(f"💫 [BRAIN] Biểu cảm kết thúc: {emo}")
            mqtt_bridge.publish(settings.TOPIC_FACE, emo)
            time.sleep(1.8)   # giữ cảm xúc 1.8s rồi finally trả về neutral

        print("✅ [BRAIN] Hoàn thành pipeline Voice → LLM → TTS.")

    except Exception as e:
        print(f"❌ [BRAIN] Lỗi pipeline: {e}")
        if player:
            player.stop()
        _publish_thinking("idle")

    finally:
        if player:
            player.stop()   # an toàn gọi nhiều lần — no-op nếu đã phát xong
        # Luôn trả về standby, dù pipeline thành công hay lỗi/timeout
        _set_voice_ai_state("standby")
        mqtt_bridge.publish(settings.TOPIC_FACE, "neutral")


# ═══════════════════════════════════════════════════════════════════════════════
#  LỆNH GIỌNG NÓI NGẮN (khi standby, không cần wake-word)
# ═══════════════════════════════════════════════════════════════════════════════

def _process_command(text: str):
    """
    Xử lý lệnh điều khiển robot đơn giản từ giọng nói.
    Chỉ kích hoạt khi AI đang ở standby (không trong pipeline LLM).
    """
    cmd = text.lower()

    if any(w in cmd for w in ["tới", "tiến", "đi thẳng"]):
        mqtt_bridge.publish(settings.TOPIC_MOVE, "forward")
        mqtt_bridge.publish(settings.TOPIC_TEXT, "OK!")

    elif any(w in cmd for w in ["dừng", "stop", "đứng lại"]):
        mqtt_bridge.publish(settings.TOPIC_MOVE, "stop")
        mqtt_bridge.publish(settings.TOPIC_TEXT, "OK!")

    elif any(w in cmd for w in ["lùi", "lui"]):
        mqtt_bridge.publish(settings.TOPIC_MOVE, "back")

    elif any(w in cmd for w in ["chào", "vẫy tay"]):
        change_state("GREETING")

    elif "buồn" in cmd:
        change_state("COMFORT")

    elif any(w in cmd for w in ["yêu", "thương"]):
        mqtt_bridge.publish(settings.TOPIC_FACE, "love")
        mqtt_bridge.publish(settings.TOPIC_TEXT, "LOVE YOU <3")
        speak("Mình cũng yêu bạn!", blocking=False)

    elif "ngủ" in cmd:
        mqtt_bridge.publish(settings.TOPIC_FACE, "sleepy")
        speak("Khò khò, mình đi ngủ đây...", blocking=False)

    elif "nháy mắt" in cmd:
        mqtt_bridge.publish(settings.TOPIC_FACE, "wink")

    elif "ngầu" in cmd:
        mqtt_bridge.publish(settings.TOPIC_FACE, "cool")
        speak("Trông mình ngầu chưa?", blocking=False)

    elif any(w in cmd for w in ["dễ thương", "cute"]):
        mqtt_bridge.publish(settings.TOPIC_FACE, "cute")
        speak("Cảm ơn bạn nha!", blocking=False)


def _handle_transcript(text: str):
    """
    Callback mỗi khi voice.py nhận được transcript từ Groq.
    Note: voice.py đã tự publish lên panda/log/voice rồi —
          ở đây chỉ xử lý lệnh điều khiển.
    """
    if voice_ai_state != "standby":
        return   # Đang bận (listening/thinking/speaking) → bỏ qua
    _process_command(text)


# ═══════════════════════════════════════════════════════════════════════════════
#  VOICE TỪ TRÌNH DUYỆT (dashboard push-to-talk)
# ═══════════════════════════════════════════════════════════════════════════════

def _process_browser_audio(b64_payload: bytes):
    """Giải mã base64 webm từ dashboard → Groq STT → route như transcript thường."""
    import base64
    try:
        data = base64.b64decode(b64_payload)
    except Exception as e:
        print(f"❌ [BRAIN] Lỗi decode audio browser: {e}")
        return

    if len(data) < 1024:
        print("⚠️  [BRAIN] Audio browser quá ngắn — bỏ qua.")
        return

    # Groq Whisper hỗ trợ webm trực tiếp — không cần convert (model chính xác nhất)
    text = transcribe_bytes(data, filename="browser_audio.webm", model=STT_MODEL_QUESTION)
    if not text or _is_hallucination(text):
        print(f"🔇 [BRAIN] Audio browser không nhận dạng được: \"{text}\"")
        return

    mqtt_bridge.publish(settings.TOPIC_VOICE_LOG, text)

    if _contains_wake_word(text):
        threading.Thread(target=_handle_wake_word, args=(text,), daemon=True).start()
    else:
        _process_command(text)


def on_browser_audio(client, userdata, msg):
    """MQTT callback cho audio push-to-talk từ dashboard."""
    if voice_ai_state != "standby":
        print("⚠️  [BRAIN] Đang bận — bỏ qua audio từ dashboard.")
        return
    print("🎤 [BRAIN] Nhận audio từ trình duyệt...")
    threading.Thread(target=_process_browser_audio, args=(msg.payload,), daemon=True).start()


def on_mic_live(client, userdata, msg):
    """Dashboard bật/tắt live-mic → bảo vòng lặp server nhường đường."""
    on = msg.payload.decode() == "1"
    voice.set_external_mic(on)


def on_browser_clip(client, userdata, msg):
    """Clip PCM sạch (DSP trình duyệt) từ live-mic → route như transcript standby."""
    if voice_ai_state != "standby":
        return
    # Echo guard: bỏ clip tới trong lúc Panda đang nói / vừa nói xong (<1s)
    if tts.is_speaking() or (time.time() - tts.speech_end_time()) < 1.0:
        return
    threading.Thread(target=_process_browser_clip, args=(msg.payload,), daemon=True).start()


def _process_browser_clip(b64_payload: bytes):
    import base64
    try:
        data = base64.b64decode(b64_payload)
    except Exception:
        return
    if len(data) < int(16000 * 0.3) * 2:   # < 0.3s → bỏ
        return

    text = voice._transcribe_dual(data)   # PCM 16k int16 → 3 pass vi/en/vi+prompt
    if not text or voice._is_hallucination(text):
        return

    mqtt_bridge.publish(settings.TOPIC_VOICE_LOG, text)
    _handle_transcript(text)              # lệnh ngắn khi standby
    if voice._contains_wake_word(text):
        threading.Thread(target=_handle_wake_word, args=(text,), daemon=True).start()
    else:
        # Cứu hộ wake cho đường mic trình duyệt
        fixed = _correct_asr(text)
        if fixed != text and voice._contains_wake_word(fixed):
            print(f"🛟 [BRAIN] Wake cứu hộ (browser): \"{text}\" → \"{fixed}\"")
            threading.Thread(target=_handle_wake_word, args=(fixed,), daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
#  VOICE LISTENING THREAD
# ═══════════════════════════════════════════════════════════════════════════════

def voice_listening_thread():
    """
    Thread lắng nghe liên tục.
    Khi phát hiện wake-word → spawn thread riêng để chạy pipeline
    (không block vòng lặp nghe chính).
    """
    register_callbacks(
        on_transcript=_handle_transcript,
        on_wake_word=lambda text: threading.Thread(
            target=_handle_wake_word,
            args=(text,),
            daemon=True,
        ).start(),
        on_wake_rescue=_correct_asr,
    )
    continuous_listen_loop()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("🧠 [BRAIN] ═══════════════════════════════")
    print("🧠 [BRAIN]  Robot Panda — Khởi động não bộ")
    print("🧠 [BRAIN] ═══════════════════════════════")
    print(f"🧠 [BRAIN]  Pipeline: Voice (Groq) → LLM (DeepSeek) → TTS (Fish Audio)")
    print()

    # Subscribe MQTT status từ robot
    mqtt_bridge.client.subscribe(settings.TOPIC_STATUS)
    mqtt_bridge.client.message_callback_add(settings.TOPIC_STATUS, on_status_received)

    # Subscribe audio push-to-talk từ dashboard
    mqtt_bridge.client.subscribe(settings.TOPIC_BROWSER_AUDIO)
    mqtt_bridge.client.message_callback_add(settings.TOPIC_BROWSER_AUDIO, on_browser_audio)

    # Subscribe live-mic trình duyệt (clip PCM + trạng thái)
    mqtt_bridge.client.subscribe(settings.TOPIC_BROWSER_CLIP)
    mqtt_bridge.client.message_callback_add(settings.TOPIC_BROWSER_CLIP, on_browser_clip)
    mqtt_bridge.client.subscribe(settings.TOPIC_MIC_LIVE)
    mqtt_bridge.client.message_callback_add(settings.TOPIC_MIC_LIVE, on_mic_live)

    # Thread nghe giọng nói
    v_thread = threading.Thread(target=voice_listening_thread, daemon=True)
    v_thread.start()
    print("✅ [BRAIN] Voice thread đang chạy.")

    # Wake-word on-device (Porcupine) nếu đã cấu hình — đúng kiểu Anki Vector:
    # KWS local bắt "Panda" mọi ngôn ngữ, ASR cloud xử lý phần còn lại.
    from server import wakeword
    if wakeword.available():
        threading.Thread(target=wakeword.run_loop, kwargs=dict(
            on_wake=lambda: threading.Thread(
                target=_handle_wake_word, args=("Panda",), daemon=True).start(),
            should_listen=lambda: voice_ai_state == "standby",
        ), daemon=True).start()
        print("✅ [BRAIN] Porcupine wake-word on-device đang chạy.")
    else:
        print("ℹ️  [BRAIN] Chưa cấu hình Porcupine — dùng wake-word Whisper dual-pass.")

    # Vision (blocking — chạy trên main thread)
    print("✅ [BRAIN] Khởi động Vision module...")
    start_vision(on_vision_update)


if __name__ == "__main__":
    main()
