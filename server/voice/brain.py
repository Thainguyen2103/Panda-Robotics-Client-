"""
brain.py — State Machine + Multi-turn Conversation Pipeline
=============================================================
Điều phối toàn bộ luồng hội thoại của Robot Panda.

State Machine:
  IDLE      → Chỉ chạy Wake Word (Porcupine / Whisper dual-pass)
  LISTENING → VAD mở mic, thu câu hỏi
  THINKING  → Groq STT → LLM+RAG (panda_tutor) → chuẩn bị TTS
  SPEAKING  → SentencePlayer phát từng câu

Multi-turn (Listening Window):
  Sau khi SPEAKING xong, tự động mở lại LISTENING trong 8 giây.
  Người dùng nói tiếp → quay lại THINKING (cùng session).
  Hết 8 giây im lặng → về IDLE (cần gọi "Panda" lại).

Barge-in:
  Trong SPEAKING, VAD ngầm chạy trên thread riêng.
  Phát hiện giọng nói → gọi tts.stop_speaking() → về LISTENING ngay.
"""

import os
import re
import sys
import time
import uuid
import threading
import json

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings

# ─── Voice sub-modules ────────────────────────────────────────────────────────
from server.voice import vad, stt, tts
import random

# ─── LLM + RAG ────────────────────────────────────────────────────────────────
try:
    from server.llm.panda_tutor import ask_panda, clean_tts_text
except ImportError:
    from llm.panda_tutor import ask_panda, clean_tts_text

# ─── MQTT (tuỳ chọn) ──────────────────────────────────────────────────────────
try:
    from server import mqtt_bridge
    _mqtt_ok = True
except Exception:
    mqtt_bridge = None
    _mqtt_ok = False

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
QUESTION_SILENCE_SEC  = getattr(settings, "QUESTION_SILENCE_SEC", 2.0)
QUESTION_MAX_SEC      = getattr(settings, "QUESTION_MAX_SEC",    20.0)
MULTI_TURN_WINDOW_SEC = getattr(settings, "MULTI_TURN_WINDOW_SEC", 8.0)  # Listening Window
LLM_TIMEOUT_SEC       = 30.0
TTS_TIMEOUT_SEC       = 60.0

BARGE_IN_ENABLED = getattr(settings, "BARGE_IN_ENABLED", True)

# ─── MQTT topics (mặc định an toàn nếu settings thiếu) ───────────────────────
def _t(attr, default="panda/noop"):
    return getattr(settings, attr, default)

TOPIC_AI_STATE   = _t("TOPIC_AI_STATE",   "panda/ai/state")
TOPIC_AI_THINKING= _t("TOPIC_AI_THINKING","panda/ai/thinking")
TOPIC_AI_RESPONSE= _t("TOPIC_AI_RESPONSE","panda/ai/response")
TOPIC_FACE       = _t("TOPIC_FACE",       "panda/cmd/face")
TOPIC_BUZZ       = _t("TOPIC_BUZZ",       "panda/cmd/buzz")
TOPIC_VOICE_LOG  = _t("TOPIC_VOICE_LOG",  "panda/log/voice")

# ─── Emoji RE (loại khỏi câu TTS) ────────────────────────────────────────────
_EMOJI_RE = re.compile("[\U0001F000-\U0010FFFF\u2600-\u27BF\uFE0F]")

# ══════════════════════════════════════════════════════════════════════════════
#  STATE MACHINE
# ══════════════════════════════════════════════════════════════════════════════

class VoiceState:
    BOOTING   = "booting"
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"


_state      = VoiceState.BOOTING
_state_lock = threading.Lock()
_pipeline_running = threading.Event()   # Set khi đang xử lý wake→TTS


def _set_state(new_state: str):
    global _state
    with _state_lock:
        if _state != new_state:
            print(f"🧠 [BRAIN] State: {_state} → {new_state}")
            _state = new_state

    # MQTT publish
    if _mqtt_ok:
        mqtt_bridge.publish(TOPIC_AI_STATE, new_state)

    # Đồng bộ với VAD: khi không ở standby → pause mic loop
    if new_state in (VoiceState.IDLE, VoiceState.BOOTING):
        _pipeline_running.clear()
    else:
        _pipeline_running.set()


def get_state() -> str:
    return _state


def _publish(topic: str, payload):
    if _mqtt_ok:
        try:
            mqtt_bridge.publish(topic, payload if isinstance(payload, str) else json.dumps(payload))
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _clean_for_tts(text: str) -> str:
    """Loại markdown, emoji trước khi đưa vào Fish Audio."""
    text = re.sub(r"[*_#`>]+", "", text)
    text = _EMOJI_RE.sub("", text)
    return text.strip()


def _extract_inline_question(trigger_text: str) -> str | None:
    """
    Nếu user nói "Panda hôm nay thời tiết thế nào" trong 1 câu →
    trích phần sau wake-word làm câu hỏi luôn, không cần nghe thêm.
    """
    lower = trigger_text.lower()
    wake_list = sorted(
        getattr(settings, "PANDA_WAKE_WORDS", ["panda"]),
        key=len, reverse=True,
    )
    for wake in wake_list:
        if wake in lower:
            after = lower.split(wake, 1)[1].strip().lstrip(",.?!:;- ")
            # Câu hỏi hợp lệ phải có ít nhất 2 từ hoặc dài hơn 4 ký tự 
            if len(after.split()) >= 2 or len(after) >= 5:
                return after
    return None


def _listen_for_question(timeout: float = None) -> str | None:
    """
    Mở mic, chờ tiếng nói → chốt clip → Groq STT → trả về text.
    timeout: nếu không ai nói trong `timeout` giây → trả về None.
    """
    pcm = vad.record_until_silence(
        silence_sec=QUESTION_SILENCE_SEC,
        max_sec=QUESTION_MAX_SEC,
        wait_timeout=timeout,
        is_active_fn=lambda: _state in (VoiceState.LISTENING, VoiceState.THINKING),
    )
    if not pcm:
        return None

    text = stt.transcribe_pcm(pcm, model=stt.STT_MODEL_QUESTION)
    if not text or stt.is_hallucination(text):
        print(f"🔇 [BRAIN] Không nhận ra câu hỏi: \"{text}\"")
        return None

    _publish(TOPIC_VOICE_LOG, text)
    print(f"❓ [BRAIN] Câu hỏi: \"{text}\"")
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  BARGE-IN MONITOR
# ══════════════════════════════════════════════════════════════════════════════

def _barge_in_monitor(stop_event: threading.Event):
    """
    Chạy song song trong SPEAKING:
    VAD ngầm theo dõi mic — nếu phát hiện giọng nói → dừng TTS.
    """
    if not BARGE_IN_ENABLED or vad._sd is None:
        return

    import queue as _queue
    q = _queue.Queue()
    dev = vad.select_input_device()
    if dev is None:
        return

    def _cb(indata, frames, t, status):
        q.put(bytes(indata))

    try:
        with vad._sd.InputStream(
            samplerate=vad.SAMPLE_RATE, channels=1, dtype="int16",
            device=dev[0], blocksize=vad.BLOCK_FRAMES, callback=_cb,
        ):
            while not stop_event.is_set():
                try:
                    data = q.get(timeout=0.1)
                except Exception:
                    continue
                rms = vad._rms(data)
                # Ngưỡng barge-in: cao hơn VAD thường để tránh nhạy quá
                if rms > vad.VAD_NOISE_FLOOR * 3:
                    print(f"🤚 [BRAIN] Barge-in detected (RMS={rms:.3f}) — dừng TTS")
                    tts.stop_speaking()
                    break
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  QA PIPELINE: THINKING → SPEAKING
# ══════════════════════════════════════════════════════════════════════════════

def _run_qa_pipeline(question: str, session_id: str) -> bool:
    """
    Chạy 1 vòng THINKING → SPEAKING:
      STT text → LLM+RAG → TTS streaming theo câu
    Trả về True nếu thành công.
    """
    _set_state(VoiceState.THINKING)
    _publish(TOPIC_AI_THINKING, json.dumps({"stage": "thinking", "text": "Panda đang suy nghĩ..."}))
    _publish(TOPIC_FACE, "questioning")

    player     = None
    barge_stop = threading.Event()
    t_start    = time.time()

    try:
        response_chunks = []
        llm_done_event  = threading.Event()
        full_response   = [""]
        sentence_buffer = [""]

        player = tts.SentencePlayer(on_play_start=_on_speech_start)

        def _push_sentence(raw: str):
            s = _clean_for_tts(raw)
            if s:
                player.push(s)

        def on_chunk(chunk: str):
            response_chunks.append(chunk)
            partial = "".join(response_chunks)
            _publish(TOPIC_AI_RESPONSE, json.dumps({"done": False, "text": partial}))
            sentence_buffer[0] += chunk
            parts = re.split(r"(?<=[.!?…])\s+", sentence_buffer[0])
            if len(parts) > 1:
                for part in parts[:-1]:
                    _push_sentence(part)
                sentence_buffer[0] = parts[-1]

        def on_done(text: str):
            full_response[0] = text
            _publish(TOPIC_AI_RESPONSE, json.dumps({"done": True, "text": text}))
            _push_sentence(sentence_buffer[0])
            sentence_buffer[0] = ""
            player.finish()
            llm_done_event.set()

        # ── Gọi LLM + RAG trong thread riêng ────────────────────────────────
        def _llm_thread():
            try:
                result = ask_panda(
                    question=question,
                    session_id=session_id,
                    stream=True,
                    on_chunk=on_chunk,
                )
                if not llm_done_event.is_set():
                    on_done(result)
            except Exception as e:
                print(f"❌ [BRAIN] LLM lỗi: {e}")
                on_done("Xin lỗi, Panda gặp chút trục trặc. Bé thử hỏi lại nhé!")

        threading.Thread(target=_llm_thread, daemon=True).start()

        # Chờ LLM với timeout
        if not llm_done_event.wait(timeout=LLM_TIMEOUT_SEC):
            print(f"⚠️  [BRAIN] LLM timeout ({LLM_TIMEOUT_SEC}s)!")
            if player:
                player.stop()
            return False

        answer = full_response[0].strip()
        if not answer:
            return False

        print(f"⏱  [BRAIN] wake→câu TTS đầu tiên: {time.time()-t_start:.1f}s")

        # ── Chờ TTS phát xong, chạy barge-in monitor song song ──────────────
        barge_thread = threading.Thread(
            target=_barge_in_monitor, args=(barge_stop,), daemon=True
        )
        barge_thread.start()

        player.wait(timeout=TTS_TIMEOUT_SEC)
        barge_stop.set()   # dừng monitor dù có barge-in hay không

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
    """Callback khi audio TTS đầu tiên bắt đầu phát."""
    _set_state(VoiceState.SPEAKING)
    tts.play_tick()
    _publish(TOPIC_FACE, "speaking")


# ══════════════════════════════════════════════════════════════════════════════
#  WAKE-WORD HANDLER: Pipeline chính + Multi-turn
# ══════════════════════════════════════════════════════════════════════════════

_pipeline_lock = threading.Lock()


def _handle_wake_word(trigger_text: str):
    """
    Pipeline đầy đủ khi phát hiện wake-word.
    """
    if _state == VoiceState.BOOTING:
        print("⚠️  [BRAIN] Wake word trong lúc đang khởi động.")
        tts.speak("Panda vẫn đang ngái ngủ, chờ mình vài giây nhé!")
        return

    # Chỉ bắt đầu khi đang IDLE
    if not _pipeline_lock.acquire(blocking=False):
        print("⚠️  [BRAIN] Đang bận — bỏ qua wake-word.")
        return

    session_id = str(uuid.uuid4())
    print(f"🐼 [BRAIN] Wake! Trigger: \"{trigger_text}\" | Session: {session_id[:8]}")

    try:
        # Ack: beep + buzz
        tts.play_beep()
        _publish(TOPIC_BUZZ, "on")
        time.sleep(0.1)
        _publish(TOPIC_BUZZ, "off")
        _publish(TOPIC_FACE, "happy")

        # ── Lấy câu hỏi đầu tiên ────────────────────────────────────────────
        _set_state(VoiceState.LISTENING)
        _publish(TOPIC_AI_THINKING, json.dumps({"stage": "listening", "text": "Panda đang lắng nghe..."}))

        question = _extract_inline_question(trigger_text) 
        
        # Nếu người dùng chỉ gọi "Panda ơi" mà chưa hỏi luôn, thì Robot đáp lại bằng giọng nói
        if not question:
            greetings = [
                "Mình đây, bạn cần hỏi gì à?",
                "Dạ Panda nghe đây!",
                "Panda đây, bạn hỏi đi!",
                "Chào bạn, mình có thể giúp gì?"
            ]
            tts.speak(random.choice(greetings))
            
            # Sau khi nói lời chào, bật mic nghe câu hỏi
            question = _listen_for_question()

        if not question:
            print("🔇 [BRAIN] Không nghe được câu hỏi.")
            return

        # ── VÒNG LẶP ĐA LƯỢT ───────────────────────────────────────────────
        while question:
            # THINKING → SPEAKING
            _run_qa_pipeline(question, session_id)

            # ── LISTENING WINDOW: chờ câu tiếp theo ─────────────────────────
            _set_state(VoiceState.LISTENING)
            _publish(TOPIC_AI_THINKING, json.dumps({
                "stage": "listening",
                "text": f"Bạn có muốn hỏi thêm gì không? (còn {int(MULTI_TURN_WINDOW_SEC)}s)",
            }))
            _publish(TOPIC_FACE, "questioning")

            print(f"👂 [BRAIN] Listening Window {MULTI_TURN_WINDOW_SEC}s — chờ câu tiếp theo...")
            question = _listen_for_question(timeout=MULTI_TURN_WINDOW_SEC)

            if not question:
                print("⏰ [BRAIN] Listening Window hết hạn — về IDLE.")
                break

            print(f"🔄 [BRAIN] Câu tiếp (multi-turn): \"{question}\"")

    except Exception as e:
        print(f"❌ [BRAIN] Lỗi pipeline: {e}")

    finally:
        _set_state(VoiceState.IDLE)
        _publish(TOPIC_FACE, "neutral")
        _publish(TOPIC_AI_THINKING, json.dumps({"stage": "idle"}))
        _pipeline_lock.release()
        print("✅ [BRAIN] Pipeline kết thúc → IDLE")


# ══════════════════════════════════════════════════════════════════════════════
#  CONTINUOUS LISTEN LOOP (IDLE — chờ wake word)
# ══════════════════════════════════════════════════════════════════════════════

def _voice_loop():
    """
    Vòng lặp nghe liên tục khi IDLE:
    Ghi clip ngắn → transcribe_dual() → nếu có wake-word → spawn pipeline thread.
    """
    import queue as _queue
    import collections

    if vad._sd is None or stt.groq_client is None:
        print("❌ [BRAIN] Thiếu sounddevice hoặc Groq — không thể nghe.")
        return

    print("👂 [BRAIN] Voice loop bắt đầu. Nói \"Panda\" để gọi mình!")

    dev = vad.select_input_device()
    while dev is None:
        time.sleep(2)
        dev = vad.select_input_device()

    q = _queue.Queue()

    def _cb(indata, frames, t, status):
        q.put(bytes(indata))

    def _emit_clip(audio: bytes):
        """Transcribe trong thread riêng — tai không ngừng nghe."""
        def _work():
            if _pipeline_running.is_set():
                return   # pipeline đang chạy → bỏ qua
            if tts.is_speaking():
                return

            text = stt.transcribe_dual(audio)
            if not text or stt.is_hallucination(text):
                return

            if stt.contains_wake_word(text):
                threading.Thread(
                    target=_handle_wake_word,
                    args=(text,),
                    daemon=True,
                ).start()

        threading.Thread(target=_work, daemon=True).start()

    min_blocks   = int(vad.MIN_SPEECH_SEC * 1000 / vad.BLOCK_MS)
    preroll_max  = int(1.5 * 1000 / vad.BLOCK_MS)
    calib_blocks = int(0.6 * 1000 / vad.BLOCK_MS)

    with vad._sd.InputStream(
        samplerate=vad.SAMPLE_RATE, channels=1, dtype="int16",
        device=dev[0], blocksize=vad.BLOCK_FRAMES, callback=_cb,
    ):
        # ── Warm-up + hiệu chuẩn ồn nền 1 lần ──────────────────────────────
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
        threshold_base = max(vad.VAD_NOISE_FLOOR, ambient * vad.VAD_AMBIENT_MULT)
        print(f"🎚️  [BRAIN] Ồn nền: {ambient:.3f} → ngưỡng {threshold_base:.3f}")

        # ── VAD streaming ────────────────────────────────────────────────────
        state_vad = "idle"
        preroll   = collections.deque(maxlen=preroll_max)
        clip, peak, speech_blocks = [], 0.0, 0
        last_speech, speech_start = 0.0, 0.0

        # GIẢM ĐỘ TRỄ: Chỉ cần im lặng 0.45s sau khi gọi "Panda" là ngắt clip gửi đi ngay
        WAKE_SILENCE = getattr(settings, "WAKE_SILENCE_SEC", 0.45)

        while True:
            # Pipeline đang chạy / TTS phát → xả hàng đợi & reset
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
            rms = vad._rms(data)
            rel = peak * 0.55 if state_vad == "speech" else 0.0
            is_sp = (
                rms >= threshold_base
                and rms >= rel
                and vad._spectral_flatness(data) < vad.SPEECH_FLAT_MAX
            )

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
                    if now - last_speech >= WAKE_SILENCE:
                        # Clip kết thúc
                        if speech_blocks >= min_blocks:
                            _emit_clip(b"".join(clip))
                        state_vad = "idle"
                        clip, peak, speech_blocks = [], 0.0, 0
                        preroll.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def start():
    """
    Khởi động hệ thống voice:
      - Thread nghe liên tục (VAD + dual-pass STT)
    Blocking: không block, trả về ngay sau khi spawn threads.
    """
    print("🧠 [BRAIN] ═══════════════════════════════════════")
    print("🧠 [BRAIN]  Robot Panda — Voice AI khởi động")
    print("🧠 [BRAIN]  Pipeline: VAD → Groq STT → LLM+RAG → Fish TTS")
    print("🧠 [BRAIN] ═══════════════════════════════════════")

    # Gọi hàm Warm-up mô hình trong một Thread ẩn
    def _warmup_task():
        _publish(TOPIC_FACE, "sleeping")
        tts.speak("Panda đang thức dậy, các bạn đợi một lát nhé!")
        
        try:
            from server.llm.panda_tutor import warmup_model
            warmup_model()
            
            _publish(TOPIC_FACE, "happy")
            tts.play_tick()
            tts.speak("Panda đã sẵn sàng, hãy gọi Panda ơi nhé!")
        except Exception as e:
            print(f"⚠️ [BRAIN] Không thể gọi warmup_model: {e}")
        finally:
            _set_state(VoiceState.IDLE)
            
    threading.Thread(target=_warmup_task, daemon=True).start()

    # Thread nghe liên tục
    vt = threading.Thread(target=_voice_loop, daemon=True)
    vt.start()
    print("✅ [BRAIN] Voice loop đang chạy (Whisper Wake-word).")


def stop():
    """Gửi tín hiệu dừng (set state về IDLE, dừng TTS nếu đang phát)."""
    tts.stop_speaking()
    _set_state(VoiceState.IDLE)
    print("🛑 [BRAIN] Voice AI dừng.")


# ─── Chạy độc lập ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start()
    print("▶  Đang chạy — nhấn Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()
        print("👋 Tạm biệt!")
