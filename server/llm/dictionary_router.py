import json
import os
from pathlib import Path
import unicodedata

# Đường dẫn tới file dữ liệu
DATA_PATH = Path(__file__).parent / "data.json"
ENTERTAIN_PATH = Path(__file__).parent / "entertainment_kids.json"

# Biến toàn cục
_VOCAB_DICT = {}
_ENTERTAIN_LIST = []

def _normalize(text: str) -> str:
    """Chuẩn hóa chuỗi (chuyển chữ thường, NFC)."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text)).casefold()

def load_dictionary():
    """Đọc file JSON và build Hash Map / List."""
    global _VOCAB_DICT, _ENTERTAIN_LIST
    
    # 1. Load data.json (Vocab)
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            for item in data:
                keywords = item.get("keywords", [])
                if item.get("vietnamese"):
                    keywords.append(item.get("vietnamese"))
                for kw in keywords:
                    norm_kw = _normalize(kw)
                    if norm_kw:
                        _VOCAB_DICT[norm_kw] = item
            print(f"✅ [DICTIONARY] Đã load {len(_VOCAB_DICT)} từ khóa từ Hash Map!")
        except Exception as e:
            print(f"⚠️ [DICTIONARY] Lỗi đọc {DATA_PATH}: {e}")
            
    # 2. Load entertainment_kids.json (Giải trí)
    if ENTERTAIN_PATH.exists():
        try:
            with open(ENTERTAIN_PATH, "r", encoding="utf-8-sig") as f:
                _ENTERTAIN_LIST = json.load(f)
            print(f"✅ [ENTERTAIN] Đã load {len(_ENTERTAIN_LIST)} câu đố/sự thật thú vị!")
        except Exception as e:
            print(f"⚠️ [ENTERTAIN] Lỗi đọc {ENTERTAIN_PATH}: {e}")

# Tự động nạp lúc khởi động
load_dictionary()

from functools import lru_cache

@lru_cache(maxsize=500)
def lookup_vocab(question: str) -> dict | None:
    """Tra cứu từ vựng siêu tốc O(N) và Caching siêu tốc O(1).
    Nếu cùng một câu hỏi lặp lại, trả kết quả thẳng từ RAM (không cần duyệt lặp).
    """
    norm_q = _normalize(question)
    best_match = None
    best_kw_len = 0
    for kw, item in _VOCAB_DICT.items():
        if kw in norm_q:
            if len(kw) > best_kw_len:
                best_kw_len = len(kw)
                best_match = item
    return best_match

import random

def get_entertainment(question: str) -> str | None:
    """Nhận diện ý định giải trí và bốc ngẫu nhiên câu đố / sự thật."""
    norm_q = _normalize(question)
    
    # Ý định 1: Đố vui
    quiz_markers = ["đố tôi", "đố bé", "đố moon", "câu đố", "đố vui"]
    if any(m in norm_q for m in quiz_markers):
        quizzes = [i for i in _ENTERTAIN_LIST if i.get("type") == "quiz"]
        if quizzes:
            item = random.choice(quizzes)
            return f"{item['question']} ... {item['answer']}"
            
    # Ý định 2: Kể chuyện / Sự thật thú vị
    fact_markers = ["kể chuyện", "sự thật", "thú vị", "có biết không", "kiến thức"]
    if any(m in norm_q for m in fact_markers):
        facts = [i for i in _ENTERTAIN_LIST if i.get("type") == "fact"]
        if facts:
            item = random.choice(facts)
            return item["content"]
            
    return None
