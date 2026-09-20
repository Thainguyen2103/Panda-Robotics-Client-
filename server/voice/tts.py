"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: tts.py (Phát âm thanh - Text to Speech)
--------------------------------------------------------------------------------
Nhiệm vụ: Dùng Fish Audio để tạo giọng AI tự nhiên, hoặc pyttsx3 offline nếu rớt mạng.

[CẤU TRÚC CHÍNH]
1. normalize_tts_text(): Chỉnh sửa text trước khi đọc (đọc số thành chữ, loại bỏ emoji).
2. SentencePlayer: Class quan trọng giúp Streaming. Không chờ tải hết cả đoạn dài, mà chia ra đọc từng câu. Câu 1 đang đọc thì tải ngầm câu 2, giúp robot trả lời lập tức.
3. _play_mp3_bytes() / _play_with_ffplay(): Tích hợp Windows MCI và FFPlay để phát nhạc nền.
"""
# ==============================================================================
# tts.py — Text-to-Speech (Chuyển Văn Bản Thành Giọng Nói)
# Sử dụng Fish Audio Neural TTS để có giọng siêu mượt như người thật
# ==============================================================================

import os
import re
import sys
import queue
import threading
import time
import tempfile
import subprocess

# Cấu hình UTF-8 để không bị lỗi font khi in chữ Tiếng Việt ra màn hình Console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Trỏ đường dẫn gốc để import file cấu hình settings.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import settings

# ─── Cấu hình tài khoản Fish Audio ───────────────────────────────────────────
# Đọc API Key từ file settings (hoặc file secrets.py)
FISH_API_KEY   = getattr(settings, "FISH_AUDIO_API_KEY", None)
# ID giọng đọc (Nếu để None nó sẽ tự chọn giọng ngẫu nhiên)
FISH_VOICE_ID  = getattr(settings, "FISH_VOICE_ID",      None)
# Model phát âm (Bản pro-free cho chất lượng tốt và miễn phí)
FISH_TTS_MODEL = getattr(settings, "FISH_TTS_MODEL",     "s2.1-pro-free")

# ─── Khởi tạo Thư viện Fish Audio ─────────────────────────────────────────────
fish_client = None
try:
    from fish_audio_sdk import Session, TTSRequest
    if FISH_API_KEY:
        # Bật kết nối với máy chủ Fish Audio
        fish_client = Session(apikey=FISH_API_KEY)
        print("✅ [TTS] Fish Audio sẵn sàng.")
    else:
        print("⚠️  [TTS] Chưa có FISH_AUDIO_API_KEY — dùng fallback pyttsx3.")
except ImportError:
    print("⚠️  [TTS] fish-audio-sdk chưa cài. pip install fish-audio-sdk")
except Exception as e:
    print(f"⚠️  [TTS] Lỗi Fish Audio: {e}")

# ─── Khởi tạo thư viện Phát tiếng Bíp ────────────────────────────────────────
try:
    import sounddevice as _sd
    import numpy as _np
except ImportError:
    # Nếu máy không cài sounddevice thì bỏ qua tiếng Bíp
    _sd = _np = None

# ─── Khởi tạo bộ đọc chữ Offline (pyttsx3) ───────────────────────────────────
# Đây là lốp dự phòng. Nếu rớt mạng, Robot sẽ lấy giọng của Windows (hơi robot một tí) ra đọc
pyttsx3_engine = None
try:
    import pyttsx3
    pyttsx3_engine = pyttsx3.init()
    # Tìm giọng tiếng Việt trong máy tính
    for _v in pyttsx3_engine.getProperty("voices"):
        if "vietnam" in _v.name.lower() or "vi" in _v.id.lower():
            pyttsx3_engine.setProperty("voice", _v.id)
            break
    # Chỉnh tốc độ đọc chậm lại xíu (150 từ/phút)
    pyttsx3_engine.setProperty("rate", 150)
    print("✅ [TTS] pyttsx3 sẵn sàng (fallback).")
except Exception:
    pass

# ─── Cờ (Flags) và Khóa (Locks) an toàn ──────────────────────────────────────
# Tránh trường hợp đang đọc câu này chưa xong đã nhét câu kia vào miệng robot
_tts_lock       = threading.Lock()
# Cờ báo hiệu Robot có đang mở miệng nói hay không
_speaking_event = threading.Event()
# Lịch sử ghi nhận thời gian đọc xong câu cuối cùng
_speech_end_t   = 0.0
# Cờ yêu cầu Robot ngậm miệng ngay lập tức (dùng khi bạn xen ngang - Barge-in)
_stop_requested = threading.Event()


# ══════════════════════════════════════════════════════════════════════════════
#  DỌN DẸP CHỮ VÀ DỊCH SỐ THÀNH CHỮ (NUMBER TO WORDS)
# ══════════════════════════════════════════════════════════════════════════════
_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]

def _num2vi(n: int) -> str:
    """Thuật toán quy đổi số tự nhiên (123) thành chữ tiếng Việt (một trăm hai ba)."""
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
    """
    Chuẩn hóa văn bản trước khi ném cho loa.
    Ví dụ: '03:07' thành 'ba giờ bảy phút' để loa không đọc là 'không ba hai chấm không bảy'.
    """
    # Chỉ làm khi câu này là tiếng Việt
    if not re.search(r"[ăâđêôơưẠ-ỹ]", text):
        return text

    # Xử lý riêng định dạng Giờ:Phút (HH:MM)
    def _time(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return m.group(0)
        return f"{_num2vi(h)} giờ {_num2vi(mi)} phút" if mi else f"{_num2vi(h)} giờ"

    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time, text)

    # Xử lý định dạng Ngày/Tháng/Năm (DD/MM/YYYY)
    def _date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{_num2vi(d)} tháng {_num2vi(mo)} năm {_num2vi(y)}"

    text = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", _date, text)
    
    # Cuối cùng, dịch tất cả các chữ số còn sót lại thành chữ
    text = re.sub(r"\d+", lambda m: _num2vi(int(m.group(0))), text)

    # ── Mẹo Vietsub (Phonetic Replacement) ─────────────────────────
    # Ép loa đọc đúng các thuật ngữ IT (Tránh trường hợp loa đọc 'Python' thành 'Pý Thòn')
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
    
    for word, phonetic in phonetics.items():
        text = re.sub(rf"(?i)\b{re.escape(word)}\b", phonetic, text)
        
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  PHÁT TIẾNG BÍP BÁO HIỆU (BLIP)
# ══════════════════════════════════════════════════════════════════════════════
def _play_blips(seq):
    """Hàm tạo sóng âm thanh hình Sine để tạo tiếng 'Bíp' nhân tạo không cần file mp3."""
    if _sd is None or _np is None:
        return
    sr = 16_000
    parts = []
    for freq, dur in seq:
        n = int(sr * dur)
        t = _np.arange(n) / sr
        # Công thức tính sóng Sine giảm dần (nghe mượt tai hơn)
        parts.append((0.3 * _np.exp(-t * 30) * _np.sin(2 * _np.pi * freq * t)).astype(_np.float32))
        parts.append(_np.zeros(int(sr * 0.03), dtype=_np.float32))
    try:
        # Bắn ra loa
        _sd.play(_np.concatenate(parts), sr)
    except Exception:
        pass


def play_beep():
    """Phát tiếng bíp kép tăng dần (Tít tít) -> Báo hiệu 'Moon đã nghe thấy'."""
    _play_blips([(880, 0.09), (1320, 0.12)])


def play_tick():
    """Phát tiếng tick ngắn gọn nhẹ -> Báo hiệu Moon chuẩn bị mở miệng nói."""
    _play_blips([(2000, 0.045)])


# ══════════════════════════════════════════════════════════════════════════════
#  CƠ CHẾ PHÁT NHẠC MP3 (THÔNG QUA WINDOWS MCI)
# ══════════════════════════════════════════════════════════════════════════════
def _play_mp3_bytes(mp3_bytes: bytes) -> bool:
    """
    Fish Audio trả về kết quả là một cục byte dữ liệu nhạc MP3.
    Hàm này mượn hệ thống của Windows để phát file nhạc đó lên.
    """
    import ctypes
    tmp_path = None
    try:
        # Ghi file tạm mp3 xuống ổ cứng
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_bytes)
            tmp_path = tmp.name

        # Dùng thư viện winmm của Windows để mở nhạc
        winmm = ctypes.windll.winmm
        ret = winmm.mciSendStringW(f'open "{tmp_path}" type mpegvideo alias moontts', None, 0, None)
        
        # Nếu Windows lỗi, gọi lốp dự phòng FFPlay
        if ret != 0:
            return _play_with_ffplay(tmp_path)

        # Ra lệnh cho Windows PHÁT nhạc và CHỜ cho đến khi bài nhạc hát xong
        winmm.mciSendStringW("play moontts wait", None, 0, None)
        # Hát xong thì đóng lại
        winmm.mciSendStringW("close moontts", None, 0, None)
        return True

    except Exception as e:
        print(f"⚠️  [TTS] Lỗi MCI: {e}")
        # Hư nữa thì lại nhờ FFPlay
        if tmp_path:
            return _play_with_ffplay(tmp_path)
        return False
    finally:
        # Hát xong nhớ phải xóa file rác đi
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _play_with_ffplay(filepath: str) -> bool:
    """Lốp dự phòng: Bật phần mềm FFPlay (nếu máy có cài ffmpeg) để phát nhạc."""
    try:
        # Chạy ẩn ffplay, không mở giao diện, tự động tắt khi hát xong
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
    """Tắt nhạc đột ngột. Dùng khi bạn đang nghe robot nói mà bạn xen ngang (Barge-in)."""
    try:
        import ctypes
        ctypes.windll.winmm.mciSendStringW("stop moontts", None, 0, None)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  LẤY GIỌNG NÓI TỪ MÁY CHỦ FISH AUDIO
# ══════════════════════════════════════════════════════════════════════════════
def _synth_fish(text: str) -> bytes | None:
    """Gửi chữ lên Fish Audio, lấy file MP3 mang về."""
    if not fish_client:
        return None
    # Dọn chữ sạch sẽ
    text = normalize_tts_text(text)
    try:
        print(f"🐟 [TTS] Đang tạo giọng Fish Audio cho: \"{text[:60]}\"")
        tts_req = TTSRequest(text=text, reference_id=FISH_VOICE_ID)
        audio = b""
        # Tải nhạc về thành từng khúc (chunk)
        for chunk in fish_client.tts(tts_req, backend=FISH_TTS_MODEL):
            audio += chunk
        return audio if audio else None
    except Exception as e:
        print(f"❌ [TTS] Fish Audio lỗi: {e}")
        return None


def _speak_fallback(text: str):
    """Robot tắt mạng -> Tự móc giọng chị Google offline của máy tính ra đọc đỡ."""
    text = normalize_tts_text(text)
    if pyttsx3_engine:
        try:
            pyttsx3_engine.say(text)
            pyttsx3_engine.runAndWait()
            return
        except Exception as e:
            print(f"❌ [TTS] pyttsx3 lỗi: {e}")
    print(f"🔇 [TTS] Mất mạng mà máy cũng không có giọng Offline. Câu trả lời là: \"{text}\"")
    time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
#  CÁC HÀM CÔNG KHAI (PUBLIC API) ĐỂ BÊN NGOÀI GỌI VÀO
# ══════════════════════════════════════════════════════════════════════════════
def is_speaking() -> bool:
    """Kiểm tra xem robot có đang mở miệng nói không."""
    return _speaking_event.is_set()


def speech_end_time() -> float:
    """Trả về mốc thời gian vừa đóng miệng xong."""
    return _speech_end_t


def stop_speaking():
    """Tát vô mỏ robot để nó nín ngay (Dừng loa)."""
    # Kéo cờ đỏ yêu cầu dừng
    _stop_requested.set()
    # Tắt mạch loa
    _stop_mci()


def speak(text: str, blocking: bool = True):
    """
    Hàm đọc nhanh 1 câu đơn giản (Dùng để chào hỏi).
    - Nếu blocking = True: Code sẽ đứng im đợi đọc xong mới chạy dòng tiếp theo.
    """
    print(f"🔊 [TTS] Nói: \"{text[:80]}\"")

    def _run():
        global _speech_end_t
        # Khóa miệng lại không cho đứa khác xen vào
        with _tts_lock:
            # Kéo cờ báo hiệu đang nói
            _speaking_event.set()
            _stop_requested.clear()
            try:
                # Tải nhạc
                audio = _synth_fish(text)
                if audio:
                    # Bật nhạc
                    _play_mp3_bytes(audio)
                else:
                    # Lốp dự phòng
                    _speak_fallback(text)
            finally:
                # Hạ cờ xuống, ghi nhận thời gian đọc xong
                _speaking_event.clear()
                _speech_end_t = time.time()

    if blocking:
        _run()
    else:
        # Nếu không cần đợi thì ném vào 1 luồng ngầm cho nó tự hát
        threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  MÁY PHÁT CÂU (SENTENCE PLAYER) — Đọc luân phiên (Streaming)
# ══════════════════════════════════════════════════════════════════════════════
_SENTINEL = object()

class SentencePlayer:
    """
    Bảo bối thần kỳ chống lag của Robot!
    Cách cũ: Chờ LLM viết ra 1 đoạn dài 10 câu -> Đợi Fish tạo giọng cho 10 câu -> Phát loa. -> Người dùng phải chờ quá lâu.
    Cách này (Streaming Player):
      - Cắt đoạn văn ra thành từng câu lẻ.
      - Luồng 1: Gửi câu 1 đi tạo giọng. Nhận về nhét vô loa phát liền.
      - Luồng 2: TRONG KHI loa đang phát câu 1, luồng 1 tiếp tục gửi câu 2, câu 3 đi tạo giọng và xếp hàng chờ sẵn.
      -> Nhờ vậy, chỉ sau 1s là robot mở miệng hát ngay, không trễ nhịp nào!
    """

    def __init__(self, on_play_start=None):
        global _speech_end_t
        # Hàng đợi chứa Chữ (Đợi tải)
        self._synth_q     = queue.Queue()
        # Hàng đợi chứa Nhạc MP3 (Đợi hát)
        self._audio_q     = queue.Queue()
        # Hàm callback gọi lúc bắt đầu hát
        self._on_start    = on_play_start
        self._stopped     = False
        
        # Bật luồng Tải Nhạc
        self._synth_thread = threading.Thread(target=self._synth_worker, daemon=True)
        # Bật luồng Hát Nhạc
        self._play_thread  = threading.Thread(target=self._play_worker,  daemon=True)
        
        self._synth_thread.start()
        self._play_thread.start()

    def _synth_worker(self):
        """Công nhân tải nhạc: Thấy có chữ là gửi mạng đi tạo file mp3 ngay."""
        while True:
            item = self._synth_q.get()
            # _SENTINEL là dấu hiệu "Hết bài văn rồi nghỉ thôi"
            if item is _SENTINEL or self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            
            # Tải MP3
            audio = _synth_fish(item)
            
            if self._stopped:
                self._audio_q.put(_SENTINEL)
                break
            # Tải xong ném vào giỏ cho công nhân thứ 2 hát
            self._audio_q.put((item, audio))

    def _play_worker(self):
        """Công nhân Hát nhạc: Lấy Mp3 trong giỏ ra mở."""
        global _speech_end_t
        first = True
        try:
            with _tts_lock:
                while True:
                    # Rút 1 file mp3 từ giỏ ra
                    item = self._audio_q.get()
                    if item is _SENTINEL:
                        break
                    # Nếu bị tát vỡ mồm (barge-in) thì ngưng hát
                    if self._stopped or _stop_requested.is_set():
                        continue 
                        
                    text, audio = item
                    # Nếu đây là câu đầu tiên của bài, thì kéo cờ Đang Hát lên
                    if first:
                        first = False
                        _speaking_event.set()
                        _stop_requested.clear()
                        if self._on_start:
                            try:
                                self._on_start()
                            except Exception:
                                pass
                                
                    # Bật loa
                    if audio:
                        _play_mp3_bytes(audio)
                    else:
                        _speak_fallback(text)
                        
                    # Nếu đang hát mà bị yêu cầu dừng (Cướp lời)
                    if _stop_requested.is_set():
                        break
        finally:
            # Hát xong hết rồi thì hạ cờ, chốt giờ
            _speaking_event.clear()
            _speech_end_t = time.time()

    def push(self, sentence: str):
        """Người ngoài muốn robot đọc câu nào thì dùng hàm này nhét câu đó vào giỏ."""
        if sentence and sentence.strip():
            self._synth_q.put(sentence.strip())

    def finish(self):
        """Kêu gọi 2 anh công nhân nghỉ làm vì bài văn đã đọc xong."""
        self._synth_q.put(_SENTINEL)

    def stop(self):
        """Yêu cầu dừng gấp (Barge-in). Dọn sạch cả 2 giỏ hàng đợi."""
        if self._stopped:
            return
        self._stopped = True
        _stop_mci()
        _stop_requested.set()
        try:
            # Rút sạch chữ thừa trong giỏ quăng đi
            while True:
                self._synth_q.get_nowait()
        except queue.Empty:
            pass
        self._synth_q.put(_SENTINEL)

    def wait(self, timeout: float = None) -> bool:
        """Đợi công nhân hát nhạc kết thúc."""
        self._play_thread.join(timeout)
        return not self._play_thread.is_alive()


# ─── File này có thể chạy độc lập để test cài đặt Loa ────────────────────────
if __name__ == "__main__":
    print("=== Test Khả năng Phát âm thanh (TTS) ===")
    speak("Xin chào! Mình là Moon, rất vui được gặp bạn!")
    time.sleep(0.5)
    speak("Bé có khỏe không?")
