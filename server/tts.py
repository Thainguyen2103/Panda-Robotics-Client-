"""
TTS (Text-to-Speech) module — Fish Audio API
Fallback: pyttsx3 (offline) nếu Fish Audio không khả dụng

Phát audio bằng sounddevice (không dùng pygame — tương thích Python 3.14).

Setup:
    pip install fish-audio-sdk sounddevice numpy

    Đặt API key vào config/settings.py:
        FISH_AUDIO_API_KEY = "your_key_here"
        FISH_VOICE_ID = "your_voice_id"   # Tùy chọn, None = giọng mặc định

    Lấy API key : https://fish.audio/app/api-keys/
    Chọn giọng   : https://fish.audio/  (copy Reference ID)
"""

import io
import os
import sys
import queue
import threading
import time
import tempfile
import subprocess

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
    FISH_API_KEY  = getattr(settings, "FISH_AUDIO_API_KEY", None)
    FISH_VOICE_ID = getattr(settings, "FISH_VOICE_ID", None)
    FISH_TTS_MODEL = getattr(settings, "FISH_TTS_MODEL", "s2.1-pro-free")
except Exception:
    FISH_API_KEY  = None
    FISH_VOICE_ID = None
    FISH_TTS_MODEL = "s2.1-pro-free"

# ─── Load Fish Audio SDK ──────────────────────────────────────────────────────
fish_client = None
try:
    from fish_audio_sdk import Session, TTSRequest
    if FISH_API_KEY:
        fish_client = Session(apikey=FISH_API_KEY)
        print("✅ [TTS] Fish Audio SDK sẵn sàng.")
    else:
        print("⚠️ [TTS] Chưa có FISH_AUDIO_API_KEY trong settings.py — dùng fallback.")
except ImportError:
    print("⚠️ [TTS] fish-audio-sdk chưa cài. Chạy: pip install fish-audio-sdk")
except Exception as e:
    print(f"⚠️ [TTS] Lỗi khởi tạo Fish Audio: {e}")

# ─── Phát audio — dùng sounddevice + scipy (không cần pygame) ────────────────
_sd  = None
_sp  = None
try:
    import sounddevice as _sd_lib
    import numpy as _np
    _sd = _sd_lib
    print("✅ [TTS] sounddevice sẵn sàng để phát audio.")
except ImportError:
    pass

try:
    from scipy.io import wavfile as _wavfile
    _sp = _wavfile
except ImportError:
    pass

# ─── Fallback: pyttsx3 (offline) ─────────────────────────────────────────────
pyttsx3_engine = None
try:
    import pyttsx3
    pyttsx3_engine = pyttsx3.init()
    _voices = pyttsx3_engine.getProperty('voices')
    for _v in _voices:
        if 'vietnam' in _v.name.lower() or 'vi' in _v.id.lower():
            pyttsx3_engine.setProperty('voice', _v.id)
            break
    pyttsx3_engine.setProperty('rate', 150)
    print("✅ [TTS] pyttsx3 sẵn sàng (fallback).")
except Exception:
    pass

# ─── Lock để tránh nói chồng nhau ────────────────────────────────────────────
_tts_lock = threading.Lock()

# ─── Text normalization: số → chữ Việt trước khi tổng hợp ───────────────────
# Fish Audio (giọng tham chiếu có prior tiếng Anh) đọc "03:07" thành
# "zero three zero seven". Chuẩn ngành TTS: quy đổi số → chữ trước.
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


def _normalize_tts_text(text: str) -> str:
    """03:07 → 'ba giờ bảy phút'; 23/08/2026 → 'hai mươi ba tháng tám...'.
    Chỉ áp dụng cho câu TIẾNG VIỆT (có chữ đặc trưng); câu tiếng Anh giữ nguyên
    để giọng Anh tự đọc số kiểu Anh."""
    import re as _re
    if not _re.search(r"[ăâđêôơưẠ-ỹ]", text):
        return text   # không phải tiếng Việt → giữ nguyên

    def _time(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return m.group(0)
        return f"{_num2vi(h)} giờ {_num2vi(mi)} phút" if mi else f"{_num2vi(h)} giờ"

    text = _re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, text)

    def _date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{_num2vi(d)} tháng {_num2vi(mo)} năm {_num2vi(y)}"

    text = _re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", _date, text)
    # Các nhóm số còn lại → chữ Việt
    return _re.sub(r"\d+", lambda m: _num2vi(int(m.group(0))), text)

# Cờ toàn cục: True trong lúc loa đang phát TTS.
# voice.py dùng cờ này để KHÔNG thu âm thanh loa của chính Panda
# (tránh vòng lặp tự kích hoạt: Panda nghe thấy chữ "Panda" trong câu chào của mình).
_speaking_event = threading.Event()
_speech_end_t = 0.0   # mốc thời gian lần phát cuối kết thúc (echo guard cho clip browser)


def is_speaking() -> bool:
    """True nếu TTS đang phát ra loa."""
    return _speaking_event.is_set()


def speech_end_time() -> float:
    """Thời điểm (time.time()) lần phát TTS gần nhất kết thúc."""
    return _speech_end_t


# ─── Sound effects kiểu Anki Vector (bíp nhận lệnh / tick trước trả lời) ──────
def _play_blips(seq):
    """Phát chuỗi blip sine tắt dần (non-blocking) qua sounddevice."""
    if _sd is None or _np is None:
        return
    sr = 16000
    parts = []
    for freq, dur in seq:
        n = int(sr * dur)
        t = _np.arange(n) / sr
        parts.append((0.3 * _np.exp(-t * 30) * _np.sin(2 * _np.pi * freq * t)).astype(_np.float32))
        parts.append(_np.zeros(int(sr * 0.03), dtype=_np.float32))   # khoảng hở 30ms
    try:
        _sd.play(_np.concatenate(parts), sr)
    except Exception:
        pass


def play_beep():
    """Bíp kép tăng dần khi nhận wake-word — 'Panda nghe thấy bạn!'."""
    _play_blips([(880, 0.09), (1320, 0.12)])


def play_tick():
    """Tick ngắn ngay trước khi Panda bắt đầu nói."""
    _play_blips([(2000, 0.045)])


def _play_mp3_bytes(mp3_bytes: bytes) -> bool:
    """
    Phát MP3 bytes bằng Windows MCI (winmm.dll) — built-in, không cần cài thêm.
    Đồng bộ: chờ phát xong mới trả về True.
    """
    import ctypes
    import ctypes.wintypes

    tmp_path = None
    try:
        # Ghi ra file tạm
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_bytes)
            tmp_path = tmp.name

        winmm = ctypes.windll.winmm

        # Mở file bằng MCI
        open_cmd  = f'open "{tmp_path}" type mpegvideo alias pandatts'
        play_cmd  = 'play pandatts wait'       # wait = đồng bộ, chờ xong
        close_cmd = 'close pandatts'

        ret = winmm.mciSendStringW(open_cmd,  None, 0, None)
        if ret != 0:
            print(f"⚠️ [TTS] MCI open lỗi: {ret}. Thử ffplay...")
            return _play_with_ffplay(tmp_path)

        winmm.mciSendStringW(play_cmd,  None, 0, None)
        winmm.mciSendStringW(close_cmd, None, 0, None)
        return True

    except Exception as e:
        print(f"⚠️ [TTS] Lỗi MCI: {e}")
        if tmp_path:
            return _play_with_ffplay(tmp_path)
        return False
    finally:
        # Xóa file TẠM sau khi MCI đã đóng xong
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _play_with_ffplay(filepath: str) -> bool:
    """Fallback: dùng ffplay (nếu có ffmpeg cài)."""
    try:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath],
            timeout=60,
            check=True,
        )
        return True
    except FileNotFoundError:
        print("⚠️ [TTS] ffplay không có. Cài ffmpeg: https://ffmpeg.org/download.html")
        return False
    except Exception as e:
        print(f"⚠️ [TTS] ffplay lỗi: {e}")
        return False




def _stop_mci_playback():
    """Ngắt phát MCI đang chạy (dùng cho barge-in / stop pipeline)."""
    try:
        import ctypes
        ctypes.windll.winmm.mciSendStringW("stop pandatts", None, 0, None)
    except Exception:
        pass


def _synth_fish(text: str) -> bytes | None:
    """
    Tổng hợp text → MP3 bytes bằng Fish Audio.
    Trả về bytes nếu thành công, None nếu lỗi (caller tự fallback).
    """
    if not fish_client:
        return None

    text = _normalize_tts_text(text)   # số → chữ Việt (tránh 'zero three zero seven')
    try:
        print(f"🐟 [TTS] Fish Audio đang tổng hợp: \"{text}\"")

        tts_request = TTSRequest(
            text=text,
            reference_id=FISH_VOICE_ID,
        )

        # Stream audio bytes về memory
        # backend: 's2.1-pro-free' = gói miễn phí (S2.1 Pro Free tier)
        audio_bytes = b""
        for chunk in fish_client.tts(tts_request, backend=FISH_TTS_MODEL):
            audio_bytes += chunk

        if not audio_bytes:
            print("⚠️ [TTS] Fish Audio trả về rỗng.")
            return None
        return audio_bytes

    except Exception as e:
        print(f"❌ [TTS] Lỗi Fish Audio: {e}")
        return None


def _speak_fish(text: str) -> bool:
    """Tổng hợp + phát 1 câu. Trả về True nếu thành công."""
    audio_bytes = _synth_fish(text)
    if not audio_bytes:
        return False
    print(f"🔊 [TTS] Phát audio ({len(audio_bytes)//1024} KB)...")
    return _play_mp3_bytes(audio_bytes)


def _speak_fallback(text: str):
    """Phát âm bằng pyttsx3 (offline fallback)."""
    text = _normalize_tts_text(text)
    if pyttsx3_engine:
        try:
            pyttsx3_engine.say(text)
            pyttsx3_engine.runAndWait()
            return
        except Exception as e:
            print(f"❌ [TTS] Lỗi pyttsx3: {e}")

    # Không có engine nào — chỉ log
    print(f"🔇 [TTS] Không có engine TTS khả dụng. Text: \"{text}\"")
    time.sleep(1)


def speak(text: str, blocking: bool = True):
    """
    API chính — phát âm văn bản.

    Args:
        text:     Văn bản cần đọc.
        blocking: True  = chờ đọc xong mới trả về (mặc định).
                  False = chạy ngầm, không chờ.
    """
    print(f"🔊 [TTS] Đang nói: \"{text}\"")

    def _run():
        with _tts_lock:
            _speaking_event.set()
            try:
                success = _speak_fish(text)
                if not success:
                    print("⚠️ [TTS] Chuyển sang pyttsx3 fallback...")
                    _speak_fallback(text)
            finally:
                _speaking_event.clear()
                global _speech_end_t
                _speech_end_t = time.time()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()


# ─── SentencePlayer — phát câu trả lời theo kiểu streaming (Vector-like) ────
_SENTINEL = object()


class SentencePlayer:
    """
    Phát câu trả lời theo TỪNG CÂU thay vì chờ toàn bộ text:
      - Thread tổng hợp: gọi Fish Audio cho câu N+1 trong khi câu N đang phát
        → audio đầu tiên vang lên ngay khi LLM vừa xong câu đầu.
      - Thread phát: phát tuần tự, giữ _tts_lock để không chồng với speak().

    Cách dùng:
        player = SentencePlayer(on_play_start=cb)   # cb chạy khi audio đầu tiên bắt đầu
        player.push("Câu 1.")
        player.push("Câu 2.")
        player.finish()
        player.wait(timeout=60)
    """

    def __init__(self, on_play_start=None):
        self._synth_q = queue.Queue()
        self._audio_q = queue.Queue()
        self._on_play_start = on_play_start
        self._stopped = False
        self._synth_thread = threading.Thread(target=self._synth_worker, daemon=True)
        self._play_thread  = threading.Thread(target=self._play_worker, daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def _synth_worker(self):
        """Tổng hợp trước từng câu, đẩy sang hàng đợi phát."""
        while True:
            item = self._synth_q.get()
            if item is _SENTINEL or self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            audio = _synth_fish(item)
            if self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            self._audio_q.put((item, audio))   # (text, bytes|None) — None = fallback

    def _play_worker(self):
        """Phát tuần tự các câu đã tổng hợp."""
        first = True
        try:
            with _tts_lock:
                while True:
                    item = self._audio_q.get()
                    if item is _SENTINEL:
                        break
                    if self._stopped:
                        continue   # xả hàng đợi, không phát nữa
                    text, audio = item
                    if first:
                        first = False
                        _speaking_event.set()   # báo voice.py: loa đang bật
                        if self._on_play_start:
                            try:
                                self._on_play_start()
                            except Exception:
                                pass
                    if audio:
                        _play_mp3_bytes(audio)
                    else:
                        print("⚠️ [TTS] Câu này Fish Audio lỗi — dùng pyttsx3 fallback.")
                        _speak_fallback(text)
        finally:
            _speaking_event.clear()
            _speech_end_t = time.time()

    def push(self, sentence: str):
        """Đẩy 1 câu vào hàng đợi tổng hợp."""
        if sentence and sentence.strip():
            self._synth_q.put(sentence.strip())

    def finish(self):
        """Báo hiệu không còn câu nào nữa."""
        self._synth_q.put(_SENTINEL)

    def stop(self):
        """Ngắt phát sớm (pipeline lỗi/timeout). An toàn gọi nhiều lần."""
        if self._stopped:
            return
        self._stopped = True
        _stop_mci_playback()
        try:
            while True:
                self._synth_q.get_nowait()
        except queue.Empty:
            pass
        self._synth_q.put(_SENTINEL)

    def wait(self, timeout: float = None) -> bool:
        """Chờ phát xong. Trả về True nếu đã kết thúc trước timeout."""
        self._play_thread.join(timeout)
        return not self._play_thread.is_alive()


# ─── Test ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test TTS Module ===")
    speak("Xin chào! Mình là Panda, rất vui được gặp bạn!")
    time.sleep(0.5)
    speak("Bạn có khỏe không?")
