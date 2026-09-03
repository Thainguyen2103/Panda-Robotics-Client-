"""
test_pipeline.py — Kiểm tra toàn bộ pipeline Voice → LLM → TTS
================================================================
Chạy từng test một để xác nhận từng module hoạt động đúng.

Cách dùng:
    python test_pipeline.py          # Chạy tất cả test
    python test_pipeline.py --tts    # Chỉ test TTS
    python test_pipeline.py --llm    # Chỉ test LLM
    python test_pipeline.py --voice  # Chỉ test Voice (STT)
    python test_pipeline.py --full   # Test toàn bộ pipeline
"""

import sys
import os
import time
import threading

# Fix Windows terminal encoding
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Màu sắc terminal ─────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg): print(f"  {RED}❌ {msg}{RESET}")
def info(msg): print(f"  {CYAN}ℹ️  {msg}{RESET}")
def warn(msg): print(f"  {YELLOW}⚠️  {msg}{RESET}")

def section(title):
    print(f"\n{BOLD}{'═'*55}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'═'*55}{RESET}")

PASS = 0
FAIL = 0

def assert_ok(condition, msg_pass, msg_fail):
    global PASS, FAIL
    if condition:
        ok(msg_pass); PASS += 1
    else:
        fail(msg_fail); FAIL += 1


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 1: LLM (DeepSeek)
# ═══════════════════════════════════════════════════════════════════════════════

def test_llm():
    section("TEST 1 — LLM (DeepSeek API)")
    from server import llm

    assert_ok(llm._client is not None,
              "LLM client khởi tạo OK",
              "LLM client KHÔNG khởi tạo được — kiểm tra DEEPSEEK_API_KEY")

    assert_ok(llm._model_name is not None,
              f"Model: {llm._model_name}",
              "Không xác định được model name")

    info("Gửi câu hỏi test lên LLM...")
    chunks     = []
    done_event = threading.Event()
    result     = [None]

    def on_chunk(c): chunks.append(c)
    def on_done(t):  result[0] = t; done_event.set()

    t0 = time.time()
    llm.chat_async(
        question="Bạn là ai? Trả lời trong 1 câu ngắn.",
        on_chunk=on_chunk,
        on_done=on_done,
    )

    finished = done_event.wait(timeout=20)
    elapsed  = time.time() - t0

    assert_ok(finished,
              f"LLM phản hồi trong {elapsed:.1f}s",
              f"LLM timeout sau 20s — kiểm tra kết nối internet")

    if result[0]:
        assert_ok(len(result[0]) > 5,
                  f"Response OK ({len(result[0])} ký tự): \"{result[0][:80]}\"",
                  "Response quá ngắn hoặc rỗng")
        assert_ok(len(chunks) > 0,
                  f"Stream hoạt động ({len(chunks)} chunks)",
                  "Stream không có chunk nào")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 2: TTS (Fish Audio)
# ═══════════════════════════════════════════════════════════════════════════════

def test_tts():
    section("TEST 2 — TTS (Fish Audio)")
    from server import tts

    assert_ok(tts.fish_client is not None,
              "Fish Audio client OK",
              "Fish Audio KHÔNG khởi tạo — kiểm tra FISH_AUDIO_API_KEY")

    info(f"Voice ID: {tts.FISH_VOICE_ID or '(default)'}")
    info(f"Model   : {tts.FISH_TTS_MODEL}")

    info("Phát âm câu test — lắng nghe xem có tiếng không...")
    t0 = time.time()
    tts.speak("Xin chào! Mình là Panda, đang test hệ thống giọng nói.", blocking=True)
    elapsed = time.time() - t0

    assert_ok(elapsed > 0.5,
              f"TTS phát âm xong trong {elapsed:.1f}s",
              "TTS kết thúc quá nhanh — có thể lỗi im lặng")

    print()
    result = input(f"  {YELLOW}❓ Bạn có nghe thấy giọng nói không? (y/n): {RESET}").strip().lower()
    assert_ok(result == 'y',
              "TTS phát âm đúng",
              "TTS không có tiếng — kiểm tra loa/driver âm thanh")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 3: STT (Groq Whisper)
# ═══════════════════════════════════════════════════════════════════════════════

def test_voice():
    section("TEST 3 — STT (Groq Whisper)")
    from server import voice

    assert_ok(voice.groq_client is not None,
              "Groq client OK",
              "Groq KHÔNG khởi tạo — kiểm tra GROQ_API_KEY")

    assert_ok(voice.sd is not None,
              "sounddevice OK",
              "sounddevice KHÔNG có — pip install sounddevice")

    # Test mic
    info("Kiểm tra microphone...")
    device = voice._select_input_device()
    assert_ok(device is not None,
              f"Mic phát hiện: #{device[0]} — {device[1]}" if device else "No mic",
              "Không tìm thấy microphone hoạt động")

    if device is None:
        return

    # Test ghi âm + transcribe
    print()
    input(f"  {YELLOW}❓ Nhấn Enter rồi nói 1 câu bất kỳ (2 giây im lặng để dừng)...{RESET}")

    t0    = time.time()
    audio = voice._record_until_silence()
    elapsed = time.time() - t0

    assert_ok(audio is not None,
              f"Ghi âm thành công ({elapsed:.1f}s audio)",
              "Không thu được âm thanh — kiểm tra mic")

    if audio is None:
        return

    info("Đang gửi lên Groq Whisper...")
    t0   = time.time()
    text = voice._transcribe(audio)
    elapsed = time.time() - t0

    if text and voice._is_hallucination(text):
        warn("Transcript giống tiếng ồn/TV/YouTube (không phải giọng bạn) — "
             "tắt video/loa và nói lại gần mic rồi test lại")

    assert_ok(bool(text),
              f"Nhận dạng OK ({elapsed:.2f}s): \"{text}\"",
              "Groq trả về rỗng — có thể mic không thu được tiếng")

    if text:
        print()
        result = input(f"  {YELLOW}❓ Transcript \"{text}\" có đúng không? (y/n): {RESET}").strip().lower()
        assert_ok(result == 'y',
                  "STT chính xác",
                  "STT chưa chính xác — thử nói to và rõ hơn")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 4: Wake-word Detection
# ═══════════════════════════════════════════════════════════════════════════════

def test_wake_word():
    section("TEST 4 — Wake-word \"Panda\"")
    from server import voice

    if not voice.groq_client or not voice.sd:
        warn("Bỏ qua — thiếu Groq hoặc sounddevice"); return

    from config import settings
    wake_words = getattr(settings, "PANDA_WAKE_WORDS", ["panda"])
    info(f"Wake words: {wake_words}")

    voice._select_input_device()   # warm-up mic trước để probe không nuốt mất giọng bạn
    print()
    input(f"  {YELLOW}❓ Nhấn Enter rồi nói \"Panda\" (hoặc \"Hey Panda\")...{RESET}")

    audio = voice._record_until_silence()
    text  = voice._transcribe_dual(audio) if audio else ""   # dual vi+en giống pipeline thật

    if text and voice._is_hallucination(text):
        warn("Transcript giống tiếng ồn/TV/YouTube (không phải giọng bạn) — "
             "tắt video/loa và nói lại gần mic rồi test lại")

    detected = voice._contains_wake_word(text) if text else False

    assert_ok(bool(text),
              f"Nghe được: \"{text}\"",
              "Không nghe được gì")

    assert_ok(detected,
              f"Wake-word phát hiện đúng trong: \"{text}\"",
              f"Không phát hiện wake-word trong: \"{text}\" — thử nói rõ hơn")


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST 5: Pipeline đầy đủ (Voice → LLM → TTS)
# ═══════════════════════════════════════════════════════════════════════════════

def test_full_pipeline():
    section("TEST 5 — Pipeline đầy đủ: Voice → LLM → TTS")
    from server import voice, llm, tts

    if not all([voice.groq_client, voice.sd, llm._client, tts.fish_client]):
        warn("Bỏ qua — 1 hoặc nhiều module chưa sẵn sàng"); return

    voice._select_input_device()   # warm-up mic trước để probe không nuốt mất giọng bạn
    print()
    input(f"  {YELLOW}❓ Nhấn Enter rồi nói \"Panda, bạn tên là gì?\"...{RESET}")

    # Bước 1: STT
    info("⏳ Đang nghe...")
    audio = voice._record_until_silence()
    assert_ok(audio is not None, "Ghi âm OK", "Không thu được âm")
    if not audio: return

    text = voice._transcribe(audio)
    assert_ok(bool(text), f"STT: \"{text}\"", "STT thất bại")
    if not text: return

    # Bước 2: LLM
    info("⏳ Đang hỏi LLM...")
    done_ev = threading.Event()
    answer  = [""]

    def on_done(t): answer[0] = t; done_ev.set()

    llm.chat_async(question=text, on_done=on_done)
    finished = done_ev.wait(timeout=20)

    assert_ok(finished and bool(answer[0]),
              f"LLM OK: \"{answer[0][:80]}\"",
              "LLM timeout hoặc trả về rỗng")
    if not answer[0]: return

    # Bước 3: TTS
    info("⏳ Đang phát âm...")
    tts.speak(answer[0], blocking=True)

    print()
    result = input(f"  {YELLOW}❓ Pipeline hoạt động đúng không? (y/n): {RESET}").strip().lower()
    assert_ok(result == 'y',
              "🎉 Pipeline hoàn chỉnh hoạt động đúng!",
              "Pipeline có vấn đề — xem log phía trên")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary():
    total = PASS + FAIL
    print(f"\n{BOLD}{'═'*55}{RESET}")
    print(f"{BOLD}  KẾT QUẢ: {PASS}/{total} tests passed{RESET}")
    if FAIL == 0:
        print(f"{GREEN}{BOLD}  🎉 Tất cả tests PASSED! Pipeline sẵn sàng.{RESET}")
    else:
        print(f"{RED}{BOLD}  ⚠️  {FAIL} test(s) FAILED — xem chi tiết phía trên.{RESET}")
    print(f"{BOLD}{'═'*55}{RESET}\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    print(f"\n{BOLD}{CYAN}[PANDA] Pipeline Test Suite{RESET}")
    print(f"{CYAN}   Kiem tra: Voice (Groq) -> LLM (DeepSeek) -> TTS (Fish Audio){RESET}")

    try:
        if "--llm" in args:
            test_llm()
        elif "--tts" in args:
            test_tts()
        elif "--voice" in args:
            test_voice()
        elif "--wake" in args:
            test_wake_word()
        elif "--full" in args:
            test_full_pipeline()
        else:
            # Mặc định: chạy tất cả theo thứ tự
            test_llm()
            test_tts()
            test_voice()
            test_wake_word()
            test_full_pipeline()

    except KeyboardInterrupt:
        print(f"\n{YELLOW}⚠️  Bị ngắt bởi người dùng.{RESET}")

    print_summary()
