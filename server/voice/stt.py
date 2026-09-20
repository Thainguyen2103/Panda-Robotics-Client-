"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: stt.py (Biến Giọng nói thành Văn bản)
--------------------------------------------------------------------------------
Nhiệm vụ: Sử dụng API của Groq (model Whisper) để dịch file ghi âm thành text siêu tốc.

[CẤU TRÚC CHÍNH]
1. transcribe_dual(): Kỹ thuật nhận diện 2 vòng. Ưu tiên nghe bằng tiếng Việt trước. Nếu thất bại, nghe lại bằng tiếng Anh.
2. is_hallucination(): Bộ lọc ảo giác. Cắt bỏ các câu Whisper hay tự bịa ra khi có tiếng ồn (vd: 'Xin chào', 'Cảm ơn các bạn').
3. WAKE_STT_PROMPT: Ngữ cảnh 'mớm' trước cho AI để không nghe sai các thuật ngữ kỹ thuật (như SQL, Moon).
"""
# ==============================================================================
# stt.py — Speech-to-Text thông qua Groq Whisper
# Gửi file âm thanh lên máy chủ Groq, dịch thành chữ và trả về siêu nhanh
# ==============================================================================

import os
import re
import sys
import time
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor

# Cấu hình UTF-8 cho Windows Terminal để in tiếng Việt không lỗi font
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Trỏ đường dẫn để import được file cấu hình chung (settings.py)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import settings
from server.voice.vad import wrap_wav

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
# Lấy API Key của Groq từ file cài đặt
GROQ_API_KEY      = getattr(settings, "GROQ_API_KEY",      None)
# Tên Model dùng để nghe lén từ khóa (Dùng bản turbo cho nhanh)
STT_MODEL         = getattr(settings, "STT_MODEL",         "whisper-large-v3-turbo")
# Tên Model dùng để dịch câu hỏi dài (Dùng bản v3 thường cho chính xác)
STT_MODEL_QUESTION= getattr(settings, "STT_MODEL_QUESTION","whisper-large-v3")
# Ngôn ngữ mặc định là Tiếng Việt. Tránh auto-detect vì AI dễ bị nhầm lẫn
STT_LANGUAGE      = getattr(settings, "STT_LANGUAGE",      "vi")
# Prompt 'mớm' trước từ khóa cho AI. Nếu AI nghe lùng bùng, nó sẽ ưu tiên đoán thành các từ này
WAKE_STT_PROMPT   = getattr(settings, "WAKE_STT_PROMPT",   "Đây là hội thoại có các từ: Moon, SQL, Java, Swing, AI, RAG, Python, API, Thắng, Ánh, Nanh.")

# Lấy danh sách các từ gọi robot (VD: Moon, Moon ơi)
WAKE_WORDS = sorted(
    getattr(settings, "MOON_WAKE_WORDS", ["moon"]),
    key=len, reverse=True,
)

# ─── Khởi tạo Thư viện Groq ───────────────────────────────────────────────────
groq_client = None
try:
    from groq import Groq
    if GROQ_API_KEY:
        # Bật kết nối với máy chủ Groq
        groq_client = Groq(api_key=GROQ_API_KEY)
        print(f"✅ [STT] Groq sẵn sàng. STT model: {STT_MODEL}")
    else:
        print("⚠️  [STT] Chưa có GROQ_API_KEY trong settings.py.")
except ImportError:
    print("⚠️  [STT] groq chưa cài. pip install groq")
except Exception as e:
    print(f"❌ [STT] Lỗi khởi tạo Groq: {e}")

# Tạo luồng xử lý song song để nghe tiếng Anh / Việt cùng lúc
_wake_exec = ThreadPoolExecutor(max_workers=2)


# ══════════════════════════════════════════════════════════════════════════════
#  CHUẨN HÓA VĂN BẢN ĐỂ TÌM KIẾM
# ══════════════════════════════════════════════════════════════════════════════
def strip_diacritics(s: str) -> str:
    """
    Hàm xóa dấu thanh tiếng Việt, xóa ký tự đặc biệt và ép thành chữ thường.
    Mục đích: Nếu AI nghe ra 'Pán đà' hay 'Pan da' thì xóa dấu đi đều quy về 'moon'
    """
    # Tách chữ cái và dấu (NFD)
    s = unicodedata.normalize("NFD", s.lower())
    # Loại bỏ tất cả các dấu (category Mn)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    # Đổi chữ đ thành d
    s = s.replace("đ", "d")
    # Xóa toàn bộ dấu câu chấm, phẩy...
    s = re.sub(r"[^\w\s]", " ", s)
    # Dọn dẹp khoảng trống thừa
    return re.sub(r"\s+", " ", s).strip()


# ══════════════════════════════════════════════════════════════════════════════
#  PHÁT HIỆN TỪ KHÓA ĐÁNH THỨC (WAKE-WORD DETECTION)
# ══════════════════════════════════════════════════════════════════════════════
# Đây là danh sách các lỗi nghe nhầm kinh điển mà Whisper hay bị khi nghe chữ "Moon"
_EXTRA_WAKE_VARIANTS = [
    "bạn nàng", "ban nang", "bạn nàng ơi",
    "pang da", "pang đa",
]

# Chuẩn hóa (xóa dấu) toàn bộ danh sách từ khóa và từ nghe nhầm
WAKE_WORDS_NORM = sorted(
    {strip_diacritics(w) for w in WAKE_WORDS}
    | {strip_diacritics(w) for w in _EXTRA_WAKE_VARIANTS},
    key=len, reverse=True,
)


def _levenshtein(a: str, b: str) -> int:
    """
    Toán học: Tính khoảng cách Levenshtein (Số phép biến đổi ít nhất để chuỗi A thành chuỗi B)
    Dùng để tìm kiếm mờ (Fuzzy matching).
    """
    # Chênh lệch độ dài quá lớn thì bỏ qua luôn
    if abs(len(a) - len(b)) > 2:
        return 3
    # Lập ma trận tính khoảng cách
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def contains_wake_word(text: str) -> bool:
    """
    Kiểm tra xem câu do STT dịch ra có chứa chữ "Moon" không.
    Trả về True nếu thấy, False nếu không thấy.
    """
    if not text:
        return False
    # Ép chuỗi về dạng không dấu, chữ thường
    norm = strip_diacritics(text)
    
    # Cách 1: Khớp chữ chính xác (Ví dụ: "pang da", "moon")
    if any(wake in norm for wake in WAKE_WORDS_NORM):
        return True
        
    # Cách 2: Khớp mờ (Fuzzy). Ví dụ STT nghe ra "panna", "Anna", "Amanda"
    # Nếu chữ giống "moon" và sai khác ≤ 2 ký tự thì vẫn chấp nhận
    return any(len(tok) >= 4 and _levenshtein(tok, "moon") <= 2
               for tok in norm.split())


# ══════════════════════════════════════════════════════════════════════════════
#  CHỐNG ẢO GIÁC (HALLUCINATION FILTER)
# ══════════════════════════════════════════════════════════════════════════════
# Khi phòng quá ồn nhưng không có tiếng người, AI Whisper thường tự bịa ra
# các câu cảm ơn khán giả (vì nó được học trên YouTube). Danh sách này để lọc chúng.
_HALLUCINATION_BLACKLIST = {
    "hello", "hello.", "hi", "hey", "you", "you.", "thank you", "thanks",
    "thank you for watching", "thanks for watching", "subscribe",
    "like and subscribe", "please subscribe", "see you next time",
    "bye", "goodbye", "vâng", "dạ", "ừ", "oh", "uh", "hmm", "the", "a",
    "subtitles by", "amara.org",
    "okay", "ok", "okay.", "i know", "okay, i know", "you know", "i see",
    "oh well", "right", "yes", "no", "good", "really", "really?",
}

# Các cụm từ bịa đặt kinh điển bằng tiếng Việt
_HALLUCINATION_TOKENS = (
    "subscribe", "subtitles by", "amara.org", "thank you for watching",
    "thanks for watching", "like and subscribe", "see you next time",
    "đăng ký kênh", "cho kênh", "kênh ghiền",
    "theo dõi", "hẹn gặp lại", "ủng hộ kênh", "cảm ơn các bạn",
)

# Nếu dịch ra chữ tiếng Nhật, tiếng Trung, tiếng Ả Rập... khi mình đang dùng mô hình tiếng Việt
# thì chắc chắn 100% đó là ảo giác do tiếng quạt máy gây ra
_NON_LATIN_RE = re.compile(
    r"[\u3040-\u30ff\u4e00-\u9fff\u0400-\u04ff\u0600-\u06ff\uac00-\ud7af]"
)


def is_hallucination(text: str) -> bool:
    """Trả về True nếu phát hiện câu văn có dấu hiệu ảo giác (bịa đặt)."""
    if not text:
        return True
    t = text.strip()
    # Nếu câu chỉ có 2 chữ cái (Ví dụ: "a.", "ờ") -> Thường là tiếng ho, tiếng thở
    if len(t) <= 2:
        return True
    low = t.lower()
    
    # Nằm trong sổ đen
    if low.strip(".!? ") in _HALLUCINATION_BLACKLIST:
        return True
    if any(tok in low for tok in _HALLUCINATION_TOKENS):
        return True
    # Chứa ký tự ngoại lai lạ
    if _NON_LATIN_RE.search(t):
        return True
        
    # Câu an toàn
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  DỊCH ÂM THANH SANG CHỮ (TRANSCRIBE)
# ══════════════════════════════════════════════════════════════════════════════
_UNSET = object()

def transcribe_bytes(
    data: bytes,
    filename: str = "clip.wav",
    language=_UNSET,
    prompt: str = None,
    model: str = None,
) -> str:
    """
    Hàm cốt lõi: Đẩy file âm thanh lên Groq.
    Lưu ý: Luôn để temperature=0.0 để AI không sáng tạo bậy bạ.
    """
    if not groq_client or not data:
        return ""

    t0 = time.time()
    tmp_path = None
    try:
        # Tạo file tạm trên máy để ghi mảng byte âm thanh vào
        suffix = os.path.splitext(filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        # Đóng gói dữ liệu chuẩn bị gửi HTTP
        kwargs = {
            "model": model or STT_MODEL,
            "file": (filename, open(tmp_path, "rb")),
            "temperature": 0.0,
            "response_format": "text",
        }
        # Chỉ định ép buộc ngôn ngữ nếu có
        lang = STT_LANGUAGE if language is _UNSET else language
        if lang:
            kwargs["language"] = lang
        # Mớm từ khóa cho AI nếu có
        if prompt:
            kwargs["prompt"] = prompt

        # Gửi Request lên Groq và nhận kết quả
        text = groq_client.audio.transcriptions.create(**kwargs)
        if hasattr(text, "text"):
            text = text.text
        text = (text or "").strip()

        # In thời gian dịch (Groq thường mất <0.3 giây)
        if text:
            print(f"📝 [STT] ({time.time()-t0:.2f}s): \"{text}\"")
        return text

    except Exception as e:
        print(f"❌ [STT] Lỗi Groq: {e}")
        return ""
    finally:
        # Xong việc thì xóa file tạm đi cho nhẹ máy
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def transcribe_pcm(pcm: bytes, model: str = None) -> str:
    """Đóng gói dữ liệu âm thanh dạng thô (PCM) thành định dạng chuẩn (WAV) rồi gửi đi."""
    if not pcm:
        return ""
    return transcribe_bytes(wrap_wav(pcm), "clip.wav", model=model)


def transcribe_dual(pcm: bytes) -> str:
    """
    Kỹ thuật nhận diện Kép (Dual-pass):
    Whisper rất hay nghe sai tiếng Việt khi có pha trộn từ tiếng Anh (như "Moon").
    Giải pháp:
      - Vòng 1: Ép nghe bằng Tiếng Việt. 
      - Nếu tìm thấy chữ Moon -> Dừng lại và trả về ngay.
      - Nếu KHÔNG tìm thấy -> Bật song song 2 luồng: Một luồng ép nghe Tiếng Anh, Một luồng ép tiếng Việt + Mớm từ.
    """
    wav = wrap_wav(pcm)
    # Vòng 1: Ép Tiếng Việt
    t_vi = transcribe_bytes(wav, "clip_vi.wav", "vi")
    if contains_wake_word(t_vi):
        return t_vi

    # Vòng 2: Phóng lao song song bằng 2 luồng (Thread)
    with ThreadPoolExecutor(max_workers=2) as ex:
        # Nghe bằng tiếng Anh xem có phải đọc chữ Moon theo accent Mỹ không
        f_en = ex.submit(transcribe_bytes, wav, "clip_en.wav", "en")
        # Nghe tiếng Việt nhưng nhét 'Mớm từ' vào 
        f_vp = ex.submit(transcribe_bytes, wav, "clip_vp.wav", "vi", WAKE_STT_PROMPT)
        
        # Đợi 2 luồng chạy xong
        t_en = f_en.result()
        t_vp = f_vp.result()

    # Quét qua kết quả của cả 2 thằng, thằng nào trúng "Moon" thì lấy
    for t in (t_vp, t_en):
        if contains_wake_word(t):
            print(f"🌐 [STT] Wake từ pass dự phòng: \"{t}\"")
            return t
            
    # Nếu xui xẻo cả 3 thằng đều không ra Moon, thì cứ trả về kết quả tiếng Việt
    return t_vi or t_vp or t_en
