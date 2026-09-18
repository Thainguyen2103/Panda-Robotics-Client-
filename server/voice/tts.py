"""
tts.py — Text-to-Speech via Fish Audio
========================================
Phát âm văn bản với Fish Audio Neural TTS.
Fallback: pyttsx3 (offline) nếu Fish Audio không khả dụng.

Tính năng:
  - SentencePlayer: phát streaming từng câu, tổng hợp câu N+1 trong khi câu N đang phát
  - stop_speaking(): ngắt phát ngay (dùng cho barge-in)
  - Chuẩn hóa số → chữ Việt trước khi TTS (tránh "zero three zero seven")
  - Âm thanh phản hồi: play_beep() (nhận wake), play_tick() (bắt đầu nói)

Setup:
    pip install fish-audio-sdk sounddevice numpy
    Điền config/settings.py:
        FISH_AUDIO_API_KEY = "your_key"
        FISH_VOICE_ID      = "your_voice_id"   # None = giọng mặc định
    Lấy key : https://fish.audio/app/api-keys/
    Chọn giọng: https://fish.audio/ (copy Reference ID)
"""

import os
import re
import sys
import queue
import threading
import time
import tempfile
import subprocess

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
FISH_API_KEY   = getattr(settings, "FISH_AUDIO_API_KEY", None)
FISH_VOICE_ID  = getattr(settings, "FISH_VOICE_ID",      None)
FISH_TTS_MODEL = getattr(settings, "FISH_TTS_MODEL",     "s2.1-pro-free")

# ─── Fish Audio SDK ───────────────────────────────────────────────────────────
fish_client = None
try:
    from fish_audio_sdk import Session, TTSRequest
    if FISH_API_KEY:
        fish_client = Session(apikey=FISH_API_KEY)
        print("✅ [TTS] Fish Audio sẵn sàng.")
    else:
        print("⚠️  [TTS] Chưa có FISH_AUDIO_API_KEY — dùng fallback pyttsx3.")
except ImportError:
    print("⚠️  [TTS] fish-audio-sdk chưa cài. pip install fish-audio-sdk")
except Exception as e:
    print(f"⚠️  [TTS] Lỗi Fish Audio: {e}")

# ─── sounddevice (dùng cho blip) ──────────────────────────────────────────────
try:
    import sounddevice as _sd
    import numpy as _np
except ImportError:
    _sd = _np = None

# ─── pyttsx3 fallback ─────────────────────────────────────────────────────────
pyttsx3_engine = None
try:
    import pyttsx3
    pyttsx3_engine = pyttsx3.init()
    for _v in pyttsx3_engine.getProperty("voices"):
        if "vietnam" in _v.name.lower() or "vi" in _v.id.lower():
            pyttsx3_engine.setProperty("voice", _v.id)
            break
    pyttsx3_engine.setProperty("rate", 150)
    print("✅ [TTS] pyttsx3 sẵn sàng (fallback).")
except Exception:
    pass

# ─── Lock & events ────────────────────────────────────────────────────────────
_tts_lock       = threading.Lock()
_speaking_event = threading.Event()
_speech_end_t   = 0.0
_stop_requested = threading.Event()   # Barge-in: yêu cầu dừng MCI ngay


# ══════════════════════════════════════════════════════════════════════════════
#  CHUẨN HÓA VĂN BẢN (số → chữ Việt)
# ══════════════════════════════════════════════════════════════════════════════

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _num2vi(n: int) -> str:
    """Đọc số nguyên theo kiểu tiếng Việt (đến tỷ)."""
    if n == 0:
        return "không"

    def under1000(x: int) -> str:
        parts = []
        if x >= 100:
            parts.append(f"{_DIGITS[x // 100]} trăm")
            x %= 100
            if 0 < x < 10:
                parts.append("lẻ")
        if x >= 10:
            tens, unit = x // 10, x % 10
            parts.append("mười" if tens == 1 else f"{_DIGITS[tens]} mươi")
            if unit == 1 and tens >= 2:
                parts.append("mốt")
            elif unit == 5:
                parts.append("lăm")
            elif unit > 0:
                parts.append(_DIGITS[unit])
        elif x > 0:
            parts.append(_DIGITS[x])
        return " ".join(parts)

    scales = ["", " nghìn", " triệu", " tỷ"]
    groups = []
    i = 0
    while n > 0 and i < len(scales):
        groups.append((n % 1000, scales[i]))
        n //= 1000
        i += 1
    return " ".join(under1000(v) + s for v, s in reversed(groups) if v)


def normalize_tts_text(text: str) -> str:
    """03:07 → 'ba giờ bảy phút'; 23/08/2026 → 'hai mươi ba tháng tám...'.
    Chỉ áp dụng cho câu tiếng Việt (có ký tự đặc trưng)."""
    if not re.search(r"[ăâđêôơưẠ-ỹ]", text):
        return text  # không phải tiếng Việt → giữ nguyên

    def _time(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return m.group(0)
        return f"{_num2vi(h)} giờ {_num2vi(mi)} phút" if mi else f"{_num2vi(h)} giờ"

    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, text)

    def _date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{_num2vi(d)} tháng {_num2vi(mo)} năm {_num2vi(y)}"

    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", _date, text)
    text = re.sub(r"\d+", lambda m: _num2vi(int(m.group(0))), text)

    # ── Phiên âm thủ công (Phonetic Replacement) ───────────────────────────
    # Sửa cách đọc cho các từ chuyên ngành, từ viết tắt tiếng Anh
    phonetics = {
        "C#": "xi sáp",
        "SQL": "ét quy eo",
        "Java": "gia va",
        "AI": "ây ai",
        "RAG": "rác",
        "API": "ây pi ai",
        "UI": "diu ai",
        "UX": "diu ếch",
        "Python": "pai thon",
        "Groq": "rốc",
    }
    
    # Replace whole words case-insensitively
    for word, phonetic in phonetics.items():
        text = re.sub(rf"(?i)\b{re.escape(word)}\b", phonetic, text)
        
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  ÂM THANH PHẢN HỒI (BLIP)
# ══════════════════════════════════════════════════════════════════════════════

def _play_blips(seq):
    """Chuỗi blip sine tắt dần (non-blocking) qua sounddevice."""
    if _sd is None or _np is None:
        return
    sr = 16_000
    parts = []
    for freq, dur in seq:
        n = int(sr * dur)
        t = _np.arange(n) / sr
        parts.append((0.3 * _np.exp(-t * 30) * _np.sin(2 * _np.pi * freq * t)).astype(_np.float32))
        parts.append(_np.zeros(int(sr * 0.03), dtype=_np.float32))
    try:
        _sd.play(_np.concatenate(parts), sr)
    except Exception:
        pass


def play_beep():
    """Bíp kép tăng dần — báo 'Panda đang nghe bạn!'."""
    _play_blips([(880, 0.09), (1320, 0.12)])


def play_tick():
    """Tick ngắn ngay trước khi Panda bắt đầu nói."""
    _play_blips([(2000, 0.045)])


# ══════════════════════════════════════════════════════════════════════════════
#  PHÁT MP3 QUA WINDOWS MCI
# ══════════════════════════════════════════════════════════════════════════════

def _play_mp3_bytes(mp3_bytes: bytes) -> bool:
    """Phát MP3 bytes bằng Windows MCI. Đồng bộ — chờ phát xong."""
    import ctypes
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_bytes)
            tmp_path = tmp.name

        winmm = ctypes.windll.winmm
        ret = winmm.mciSendStringW(f'open "{tmp_path}" type mpegvideo alias pandatts', None, 0, None)
        if ret != 0:
            return _play_with_ffplay(tmp_path)

        winmm.mciSendStringW("play pandatts wait", None, 0, None)
        winmm.mciSendStringW("close pandatts", None, 0, None)
        return True

    except Exception as e:
        print(f"⚠️  [TTS] Lỗi MCI: {e}")
        if tmp_path:
            return _play_with_ffplay(tmp_path)
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _play_with_ffplay(filepath: str) -> bool:
    """Fallback phát file âm thanh bằng ffplay."""
    try:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath],
            timeout=60, check=True,
        )
        return True
    except FileNotFoundError:
        print("⚠️  [TTS] ffplay không có. Cài ffmpeg: https://ffmpeg.org/download.html")
        return False
    except Exception as e:
        print(f"⚠️  [TTS] ffplay lỗi: {e}")
        return False


def _stop_mci():
    """Ngắt MCI đang phát — dùng cho barge-in."""
    try:
        import ctypes
        ctypes.windll.winmm.mciSendStringW("stop pandatts", None, 0, None)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  TỔNG HỢP FISH AUDIO
# ══════════════════════════════════════════════════════════════════════════════

def _synth_fish(text: str) -> bytes | None:
    """Text → MP3 bytes qua Fish Audio. None nếu lỗi."""
    if not fish_client:
        return None
    text = normalize_tts_text(text)
    try:
        print(f"🐟 [TTS] Fish Audio: \"{text[:60]}\"")
        tts_req = TTSRequest(text=text, reference_id=FISH_VOICE_ID)
        audio = b""
        for chunk in fish_client.tts(tts_req, backend=FISH_TTS_MODEL):
            audio += chunk
        return audio if audio else None
    except Exception as e:
        print(f"❌ [TTS] Fish Audio lỗi: {e}")
        return None


def _speak_fallback(text: str):
    """pyttsx3 offline fallback."""
    text = normalize_tts_text(text)
    if pyttsx3_engine:
        try:
            pyttsx3_engine.say(text)
            pyttsx3_engine.runAndWait()
            return
        except Exception as e:
            print(f"❌ [TTS] pyttsx3 lỗi: {e}")
    print(f"🔇 [TTS] Không có engine TTS. Text: \"{text}\"")
    time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
#  API CÔNG KHAI
# ══════════════════════════════════════════════════════════════════════════════

def is_speaking() -> bool:
    """True nếu TTS đang phát ra loa."""
    return _speaking_event.is_set()


def speech_end_time() -> float:
    """Timestamp lần phát TTS gần nhất kết thúc."""
    return _speech_end_t


def stop_speaking():
    """
    Dừng phát TTS ngay lập tức (barge-in).
    An toàn gọi nhiều lần.
    """
    _stop_requested.set()
    _stop_mci()


def speak(text: str, blocking: bool = True):
    """
    Phát 1 đoạn văn bản.

    Args:
        text:     Văn bản cần đọc.
        blocking: True = chờ đọc xong (mặc định).
                  False = chạy ngầm.
    """
    print(f"🔊 [TTS] Nói: \"{text[:80]}\"")

    def _run():
        global _speech_end_t
        with _tts_lock:
            _speaking_event.set()
            _stop_requested.clear()
            try:
                audio = _synth_fish(text)
                if audio:
                    _play_mp3_bytes(audio)
                else:
                    _speak_fallback(text)
            finally:
                _speaking_event.clear()
                _speech_end_t = time.time()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  SENTENCE PLAYER — streaming từng câu (Vector-like)
# ══════════════════════════════════════════════════════════════════════════════

_SENTINEL = object()


class SentencePlayer:
    """
    Phát câu trả lời theo TỪNG CÂU thay vì chờ toàn bộ:
      - Thread tổng hợp: gọi Fish Audio cho câu N+1 khi câu N đang phát
        → audio đầu tiên vang lên ngay khi LLM vừa xong câu đầu.
      - Thread phát: phát tuần tự.

    Cách dùng:
        player = SentencePlayer(on_play_start=cb)
        player.push("Câu 1.")
        player.push("Câu 2.")
        player.finish()
        player.wait(timeout=60)
    """

    def __init__(self, on_play_start=None):
        global _speech_end_t
        self._synth_q     = queue.Queue()
        self._audio_q     = queue.Queue()
        self._on_start    = on_play_start
        self._stopped     = False
        self._synth_thread = threading.Thread(target=self._synth_worker, daemon=True)
        self._play_thread  = threading.Thread(target=self._play_worker,  daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def _synth_worker(self):
        while True:
            item = self._synth_q.get()
            if item is _SENTINEL or self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            audio = _synth_fish(item)
            if self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            self._audio_q.put((item, audio))

    def _play_worker(self):
        global _speech_end_t
        first = True
        try:
            with _tts_lock:
                while True:
                    item = self._audio_q.get()
                    if item is _SENTINEL:
                        break
                    if self._stopped or _stop_requested.is_set():
                        continue  # xả hàng đợi
                    text, audio = item
                    if first:
                        first = False
                        _speaking_event.set()
                        _stop_requested.clear()
                        if self._on_start:
                            try:
                                self._on_start()
                            except Exception:
                                pass
                    if audio:
                        _play_mp3_bytes(audio)
                    else:
                        _speak_fallback(text)
                    # Barge-in: dừng ngay nếu có yêu cầu
                    if _stop_requested.is_set():
                        break
        finally:
            _speaking_event.clear()
            _speech_end_t = time.time()

    def push(self, sentence: str):
        """Đẩy 1 câu vào hàng đợi tổng hợp."""
        if sentence and sentence.strip():
            self._synth_q.put(sentence.strip())

    def finish(self):
        """Báo không còn câu nào nữa."""
        self._synth_q.put(_SENTINEL)

    def stop(self):
        """Ngắt phát sớm (barge-in / timeout). An toàn gọi nhiều lần."""
        if self._stopped:
            return
        self._stopped = True
        _stop_mci()
        _stop_requested.set()
        try:
            while True:
                self._synth_q.get_nowait()
        except queue.Empty:
            pass
        self._synth_q.put(_SENTINEL)

    def wait(self, timeout: float = None) -> bool:
        """Chờ phát xong. True nếu kết thúc trước timeout."""
        self._play_thread.join(timeout)
        return not self._play_thread.is_alive()


# ─── Test ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test TTS ===")
    speak("Xin chào! Mình là Panda, rất vui được gặp bạn!")
    time.sleep(0.5)
    speak("Bạn có khỏe không?")
