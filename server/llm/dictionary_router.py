import json
import os
from pathlib import Path
import unicodedata

# Đường dẫn tới file data.json
DATA_PATH = Path(__file__).parent / "data.json"

# Biến toàn cục lưu Hash Map
_VOCAB_DICT = {}

def _normalize(text: str) -> str:
    """Chuẩn hóa chuỗi (chuyển chữ thường, NFC)."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text)).casefold()

def load_dictionary():
    """Đọc file data.json và build Hash Map."""
    global _VOCAB_DICT
    if not DATA_PATH.exists():
        print(f"⚠️ [DICTIONARY] Không tìm thấy file {DATA_PATH}")
        return

    try:
        with open(DATA_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        
        for item in data:
            # Lấy tất cả các keyword của bài học
            keywords = item.get("keywords", [])
            # Thêm cả nghĩa tiếng Việt vào danh sách khóa tìm kiếm
            if item.get("vietnamese"):
                keywords.append(item.get("vietnamese"))
            
            # Map mỗi từ khóa (đã chuẩn hóa) vào item này
            for kw in keywords:
                norm_kw = _normalize(kw)
                if norm_kw:
                    _VOCAB_DICT[norm_kw] = item
                    
        print(f"✅ [DICTIONARY] Đã load {len(_VOCAB_DICT)} từ khóa từ Hash Map!")
    except Exception as e:
        print(f"⚠️ [DICTIONARY] Lỗi đọc JSON: {e}")

# Tự động nạp lúc khởi động
load_dictionary()

def lookup_vocab(question: str) -> dict | None:
    """
    Tra cứu siêu tốc O(1) hoặc O(N) chuỗi con:
    Tìm xem câu hỏi có chứa keyword nào trong Hash Map không.
    Ưu tiên từ khóa dài nhất để tránh nhận diện nhầm.
    """
    norm_q = _normalize(question)
    
    best_match = None
    best_kw_len = 0
    
    # Duyệt Hash Map tìm keyword xuất hiện trong câu hỏi
    for kw, item in _VOCAB_DICT.items():
        if kw in norm_q:
            # Chọn từ khóa dài nhất (VD: ưu tiên "con mèo" hơn là "mèo")
            if len(kw) > best_kw_len:
                best_kw_len = len(kw)
                best_match = item
                
    return best_match
