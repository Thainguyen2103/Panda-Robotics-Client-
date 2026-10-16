"""
TTS (Text-to-Speech) module — Microsoft Edge neural voices

Phát audio bằng sounddevice (không dùng pygame — tương thích Python 3.14).

Setup:
    Install requirements-voice.txt; Edge TTS uses an online service.
"""

import io
import asyncio
import os
import sys
import queue
import threading
import time
import tempfile
import subprocess
import re

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

# ─── Cấu hình ────────────────────────────────────────────────────────────────
try:
    from config import settings
except Exception:
    settings = None

# Edge voice mapping; Edge is the sole configured TTS provider.
EDGE_TTS_JA_VOICE = os.getenv("MOON_EDGE_TTS_JA_VOICE", "ja-JP-NanamiNeural")
EDGE_TTS_EN_VOICE = os.getenv("MOON_EDGE_TTS_EN_VOICE", "en-US-AnaNeural")
EDGE_TTS_VI_VOICE = os.getenv("MOON_EDGE_TTS_VI_VOICE", "vi-VN-HoaiMyNeural")
EDGE_TTS_TIMEOUT_SEC = float(os.getenv("MOON_EDGE_TTS_TIMEOUT_SEC", "15"))

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

# ─── Lock để tránh nói chồng nhau ────────────────────────────────────────────
_tts_lock = threading.Lock()

# ─── Text normalization: số → chữ Việt trước khi tổng hợp ───────────────────
# Chuẩn hóa số tiếng Việt trước khi phát âm, ví dụ giờ và ngày.
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
# voice.py dùng cờ này để KHÔNG thu âm thanh loa của chính Moon
# (tránh vòng lặp tự kích hoạt: Moon nghe thấy chữ "Moon" trong câu chào của mình).
_speaking_event = threading.Event()
_speech_end_t = 0.0   # mốc thời gian lần phát cuối kết thúc (echo guard cho clip browser)
_activity_callback = None


def register_activity_callback(callback):
    """Notify the owner whenever Moon's speaker starts/stops producing TTS."""
    global _activity_callback
    _activity_callback = callback


def _set_speaking(active: bool):
    changed = _speaking_event.is_set() != active
    if active:
        _speaking_event.set()
    else:
        _speaking_event.clear()
    if changed and _activity_callback:
        try:
            _activity_callback(active)
        except Exception:
            pass


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
    """Bíp kép tăng dần khi nhận wake-word — 'Moon nghe thấy bạn!'."""
    _play_blips([(880, 0.09), (1320, 0.12)])


def play_tick():
    """Tick ngắn ngay trước khi Moon bắt đầu nói."""
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
        open_cmd  = f'open "{tmp_path}" type mpegvideo alias moontts'
        play_cmd  = 'play moontts wait'       # wait = đồng bộ, chờ xong
        close_cmd = 'close moontts'

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
        ctypes.windll.winmm.mciSendStringW("stop moontts", None, 0, None)
    except Exception:
        pass


def _contains_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text or ""))


def _edge_voice_for_text(text: str) -> str | None:
    """Choose a matching Edge voice for Japanese, English, or Vietnamese."""
    try:
        from llm.language import response_language_matches
        if response_language_matches(text, "vi"):
            return EDGE_TTS_VI_VOICE
        if response_language_matches(text, "en"):
            return EDGE_TTS_EN_VOICE
        if response_language_matches(text, "ja"):
            return EDGE_TTS_JA_VOICE
    except Exception:
        pass
    if _contains_japanese(text):
        return EDGE_TTS_JA_VOICE
    return EDGE_TTS_EN_VOICE


async def _synth_edge_async(text: str, voice: str) -> bytes:
    """Generate MP3 bytes with edge-tts without writing a temporary audio file."""
    import edge_tts

    communicator = edge_tts.Communicate(text, voice)
    chunks = bytearray()
    async for item in communicator.stream():
        if item.get("type") == "audio":
            chunks.extend(item.get("data", b""))
    if not chunks:
        raise RuntimeError("Edge TTS returned no audio")
    return bytes(chunks)


def _synth_edge(text: str, voice: str | None = None) -> bytes | None:
    """Bound Edge's async request while preserving the synchronous TTS API."""
    voice = voice or _edge_voice_for_text(text)
    if not voice:
        return None
    timeout = max(0.1, EDGE_TTS_TIMEOUT_SEC)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(asyncio.wait_for(
                _synth_edge_async(text, voice), timeout=timeout
            ))
        except Exception as exc:
            print(f"⚠️ [TTS] Edge TTS unavailable ({type(exc).__name__}).")
            return None

    result = queue.Queue(maxsize=1)

    def run():
        try:
            audio = asyncio.run(asyncio.wait_for(
                _synth_edge_async(text, voice),
                timeout=timeout,
            ))
            result.put((audio, None), block=False)
        except Exception as exc:
            try:
                result.put((None, type(exc).__name__), block=False)
            except queue.Full:
                pass

    threading.Thread(target=run, daemon=True, name="moon-edge-tts").start()
    try:
        audio, error = result.get(timeout=timeout + 0.5)
    except queue.Empty:
        print("⚠️ [TTS] Edge TTS timeout.")
        return None
    if error:
        # Do not include utterance text or provider details in diagnostic output.
        print(f"⚠️ [TTS] Edge TTS unavailable ({error}).")
    return audio


def _synth_speech(text: str) -> bytes | None:
    """Synthesize with the matching Edge neural voice; no provider fallback."""
    voice = _edge_voice_for_text(text)
    return _synth_edge(_normalize_tts_text(text), voice)


def _speak_preferred(text: str) -> bool:
    audio = _synth_speech(text)
    if not audio:
        return False
    return _play_mp3_bytes(audio)


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
            _set_speaking(True)
            try:
                success = _speak_preferred(text)
                if not success:
                    print("⚠️ [TTS] Edge TTS không khả dụng; câu này chưa được phát.")
            finally:
                _set_speaking(False)
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
      - Thread tổng hợp: gọi Edge TTS cho câu N+1 trong khi câu N đang phát
        → audio đầu tiên vang lên ngay khi LLM vừa xong câu đầu.
      - Thread phát: phát tuần tự, giữ _tts_lock để không chồng với speak().

    Cách dùng:
        player = SentencePlayer(on_play_start=cb)   # cb chạy khi audio đầu tiên bắt đầu
        player.push("Câu 1.")
        player.push("Câu 2.")
        player.finish()
        player.wait(timeout=60)
    """

    def __init__(self, on_play_start=None, on_fallback=None, synth_timeout=None):
        self._synth_q = queue.Queue()
        self._audio_q = queue.Queue()
        self._on_play_start = on_play_start
        self._on_fallback = on_fallback
        self._synth_timeout = float(
            synth_timeout if synth_timeout is not None
            else getattr(settings, "EDGE_TTS_TIMEOUT_SEC", EDGE_TTS_TIMEOUT_SEC)
        )
        self._edge_disabled = False
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
            audio, reason = self._synth_with_timeout(item)
            if self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            self._audio_q.put((item, audio, reason))

    def _synth_with_timeout(self, text):
        """Bound provider synthesis; one timeout disables remote synthesis this turn."""
        if self._edge_disabled:
            return None, "Edge TTS đã bị bỏ qua sau lần quá thời gian trước"
        result = queue.Queue(maxsize=1)

        def run():
            try:
                result.put((_synth_speech(text), None), block=False)
            except Exception as exc:
                try:
                    result.put((None, str(exc)), block=False)
                except queue.Full:
                    pass

        threading.Thread(target=run, daemon=True).start()
        try:
            audio, reason = result.get(timeout=max(.1, self._synth_timeout))
        except queue.Empty:
            self._edge_disabled = True
            return None, f"TTS quá {self._synth_timeout:g} giây"
        return audio, reason or (None if audio else "Edge TTS không trả về âm thanh")

    def _play_worker(self):
        """Phát tuần tự các câu đã tổng hợp."""
        global _speech_end_t
        first = True
        try:
            with _tts_lock:
                while True:
                    item = self._audio_q.get()
                    if item is _SENTINEL:
                        break
                    if self._stopped:
                        continue   # xả hàng đợi, không phát nữa
                    text, audio, reason = item
                    if not audio:
                        print(f"⚠️ [TTS] {reason or 'Edge TTS lỗi'} — câu này không được phát.")
                        if self._on_fallback:
                            try:
                                self._on_fallback(text, reason or "Edge TTS lỗi")
                            except Exception:
                                pass
                        continue
                    if first:
                        first = False
                        _set_speaking(True)   # báo mọi nguồn mic: loa đang bật
                        if self._on_play_start:
                            try:
                                self._on_play_start()
                            except Exception:
                                pass
                    if not _play_mp3_bytes(audio) and self._on_fallback:
                        try:
                            self._on_fallback(text, "Không phát được audio Edge TTS")
                        except Exception:
                            pass
        finally:
            _set_speaking(False)
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
        # The synth thread may be blocked inside the third-party SDK. Unblock
        # playback immediately; the blocked daemon can finish harmlessly later.
        self._audio_q.put(_SENTINEL)
        self._synth_q.put(_SENTINEL)

    def wait(self, timeout: float = None) -> bool:
        """Chờ phát xong. Trả về True nếu đã kết thúc trước timeout."""
        self._play_thread.join(timeout)
        return not self._play_thread.is_alive()


# ─── Test ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test TTS Module ===")
    speak("Xin chào! Mình là Moon, rất vui được gặp bạn!")
    time.sleep(0.5)
    speak("Bạn có khỏe không?")
