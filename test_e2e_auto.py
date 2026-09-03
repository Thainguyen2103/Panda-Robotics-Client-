"""
test_e2e_auto.py — Kiểm thử E2E KHÔNG tương tác cho Robot Panda
================================================================
Xác minh 4 module lõi không cần người nói vào mic:

  1. STT  : nhận diện giọng nói → text
            - transcribe file ghi âm có sẵn (_test_vi.wav)
            - round-trip: TTS tổng hợp "Panda ơi..." → STT đọc lại → phải bắt được wake-word
  2. LLM  : text → AI phản hồi (stream + done)
  3. TTS  : text → speech (tổng hợp Fish Audio + phát ra loa thật)
 4. OLED  : chạy pipeline wake-word giả lập, subscribe MQTT để kiểm chứng
            chuỗi hoạt ảnh: questioning → ai-thinking → speaking → neutral
            và chuỗi state:  listening → thinking → speaking → standby

Cách dùng:
    server/venv/Scripts/python.exe test_e2e_auto.py

Lưu ý: TTS sẽ PHÁT RA LOA trong lúc test — bạn sẽ nghe thấy Panda nói.
"""

import sys
import os
import time
import threading

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt

from config import settings
from server import voice, llm, tts, brain

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = 0
FAIL = 0

def ok(msg):   global PASS; PASS += 1; print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg): global FAIL; FAIL += 1; print(f"  {RED}❌ {msg}{RESET}")
def info(msg): print(f"  {CYAN}ℹ️  {msg}{RESET}")

def section(title):
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}")


# ═══════════════════════════════════════════════════════════════════
#  TEST 1 — STT: giọng nói → text
# ═══════════════════════════════════════════════════════════════════

def test_stt():
    section("TEST 1 — STT: nhận diện giọng nói → text")

    # 1a. File ghi âm có sẵn
    wav_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_vi.wav")
    if os.path.exists(wav_path):
        with open(wav_path, "rb") as f:
            data = f.read()
        t0 = time.time()
        text = voice.transcribe_bytes(data, filename="_test_vi.wav")
        info(f"Transcript file có sẵn ({time.time()-t0:.2f}s): \"{text}\"")
        if text:
            ok(f"STT nhận diện file wav: \"{text}\"")
        else:
            fail("STT trả về rỗng cho file wav có sẵn")
    else:
        info("Không có _test_vi.wav — bỏ qua phần 1a")

    # 1b. Round-trip TTS → STT (kiểm tra độ chính xác + wake-word)
    info("Tổng hợp câu test bằng Fish Audio: \"Panda ơi, bạn tên là gì?\"")
    audio = tts._synth_fish("Panda ơi, bạn tên là gì?")
    if not audio:
        fail("Fish Audio không tổng hợp được audio round-trip")
        return
    t0 = time.time()
    text = voice.transcribe_bytes(audio, filename="roundtrip.mp3")
    info(f"STT đọc lại ({time.time()-t0:.2f}s): \"{text}\"")

    if not text:
        fail("STT không nhận diện được audio do chính TTS sinh ra")
        return
    ok(f"Round-trip TTS→STT hoạt động: \"{text}\"")

    if voice._contains_wake_word(text):
        ok("Wake-word \"Panda\" được phát hiện trong round-trip")
    else:
        fail(f"Wake-word KHÔNG được phát hiện trong: \"{text}\"")

    if not voice._is_hallucination(text):
        ok("Bộ lọc hallucination chấp nhận transcript hợp lệ")
    else:
        fail("Bộ lọc hallucination chặn nhầm transcript hợp lệ")


# ═══════════════════════════════════════════════════════════════════
#  TEST 2 — LLM: text → AI phản hồi
# ═══════════════════════════════════════════════════════════════════

def test_llm():
    section("TEST 2 — LLM: text → AI phản hồi")

    done_ev = threading.Event()
    result  = [""]
    chunks  = []

    def on_chunk(c): chunks.append(c)
    def on_done(t):  result[0] = t; done_ev.set()

    t0 = time.time()
    llm.chat_async(question="Bạn là ai? Trả lời trong 1 câu ngắn.",
                   on_chunk=on_chunk, on_done=on_done)
    finished = done_ev.wait(timeout=30)

    if not finished:
        fail("LLM timeout sau 30s")
        return
    ok(f"LLM phản hồi trong {time.time()-t0:.1f}s")

    if len(result[0]) > 5:
        ok(f"Response hợp lệ ({len(result[0])} ký tự): \"{result[0][:80]}\"")
    else:
        fail(f"Response rỗng/quá ngắn: \"{result[0]}\"")

    if chunks:
        ok(f"Stream hoạt động ({len(chunks)} chunks)")
    else:
        fail("Stream không có chunk nào")


# ═══════════════════════════════════════════════════════════════════
#  TEST 3 — TTS: text → speech (phát ra loa)
# ═══════════════════════════════════════════════════════════════════

def test_tts():
    section("TEST 3 — TTS: text → speech (bạn sẽ NGHE thấy loa)")

    audio = tts._synth_fish("Xin chào! Mình là Panda, đang kiểm tra giọng nói.")
    if audio and len(audio) > 1024:
        ok(f"Fish Audio tổng hợp OK ({len(audio)//1024} KB)")
    else:
        fail("Fish Audio tổng hợp thất bại")
        return

    t0 = time.time()
    played = tts._speak_fish("Kiểm tra một hai ba bốn năm.")
    if played:
        ok(f"Audio đã phát ra loa ({time.time()-t0:.1f}s) — bạn có nghe thấy không?")
    else:
        fail("Phát audio thất bại — kiểm tra loa/driver")


# ═══════════════════════════════════════════════════════════════════
#  TEST 4 — OLED/state: chuỗi hoạt ảnh theo pipeline
# ═══════════════════════════════════════════════════════════════════

def test_oled_sequence():
    section("TEST 4 — OLED: chuỗi hoạt ảnh Listening → Thinking → Speaking")

    events = []

    def on_msg(client, userdata, msg):
        events.append((msg.topic, msg.payload.decode()))

    sub = mqtt.Client()
    sub.on_message = on_msg

    def on_connect(client, userdata, flags, rc):
        for t in [settings.TOPIC_FACE, settings.TOPIC_AI_STATE,
                  settings.TOPIC_AI_THINKING, settings.TOPIC_AI_RESPONSE]:
            client.subscribe(t)
    sub.on_connect = on_connect

    try:
        sub.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
    except Exception as e:
        fail(f"Không kết nối được MQTT broker: {e}")
        return
    sub.loop_start()
    time.sleep(0.5)

    info("Chạy pipeline wake-word giả lập: \"Panda, bạn tên là gì?\"")
    info("(Panda sẽ NÓI câu trả lời ra loa trong bước này)")
    t0 = time.time()
    brain._handle_wake_word("Panda, bạn tên là gì?")
    time.sleep(1.0)   # chờ MQTT drain
    sub.loop_stop()
    info(f"Pipeline hoàn thành sau {time.time()-t0:.1f}s")

    faces  = [p for t, p in events if t == settings.TOPIC_FACE]
    states = [p for t, p in events if t == settings.TOPIC_AI_STATE]
    resp   = [p for t, p in events if t == settings.TOPIC_AI_RESPONSE]

    info(f"Chuỗi face  : {faces}")
    info(f"Chuỗi state : {states}")

    def idx(seq, val):
        return seq.index(val) if val in seq else -1

    # ── Kiểm tra chuỗi OLED face ──
    i_q, i_t, i_s, i_n = (idx(faces, v) for v in
                          ["questioning", "ai-thinking", "speaking", "neutral"])
    if i_q >= 0:
        ok("OLED 'questioning' (?) hiển thị khi lắng nghe")
    else:
        fail("Thiếu face 'questioning'")
    if i_t >= 0 and i_q < i_t:
        ok("OLED 'ai-thinking' (dots) hiển thị sau questioning")
    else:
        fail("Thiếu/sai thứ tự face 'ai-thinking'")
    if i_s >= 0 and i_t < i_s:
        ok("OLED 'speaking' (equalizer) hiển thị khi nói")
    else:
        fail("Thiếu/sai thứ tự face 'speaking'")
    if i_n >= 0 and i_s < i_n:
        ok("OLED quay về 'neutral' khi kết thúc")
    else:
        fail("Thiếu/sai thứ tự face 'neutral' cuối pipeline")

    # ── Kiểm tra chuỗi AI state ──
    j_l, j_t, j_s, j_b = (idx(states, v) for v in
                          ["listening", "thinking", "speaking", "standby"])
    if j_l == 0:
        ok("State bắt đầu bằng 'listening'")
    else:
        fail(f"State đầu tiên không phải listening: {states[:1]}")
    if j_l < j_t < j_s < j_b and j_b >= 0:
        ok("Chuỗi state đúng: listening → thinking → speaking → standby")
    else:
        fail(f"Chuỗi state sai: {states}")

    # ── Kiểm tra AI response stream ──
    if resp and '"done": true' in resp[-1]:
        ok("AI response stream hoàn thành (done=true)")
    else:
        fail("Không nhận được response done=true")


# ═══════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{CYAN}[PANDA] E2E Auto Test — không cần mic{RESET}")
    test_stt()
    test_llm()
    test_tts()
    test_oled_sequence()

    total = PASS + FAIL
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  KẾT QUẢ: {PASS}/{total} checks passed{RESET}")
    if FAIL == 0:
        print(f"{GREEN}{BOLD}  🎉 Tất cả PASSED! Pipeline Voice→LLM→TTS→OLED liền mạch.{RESET}")
    else:
        print(f"{RED}{BOLD}  ⚠️  {FAIL} check(s) FAILED — xem log phía trên.{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    main()
