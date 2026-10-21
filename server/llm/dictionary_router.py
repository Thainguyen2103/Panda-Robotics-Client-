import json
import os
from pathlib import Path
import re
import unicodedata

# Production vocabulary is served only from the curated V2 corpus.
DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "data_v2.json"
ENTERTAIN_PATH = Path(__file__).parent / "entertainment_kids.json"

# Biến toàn cục
_VOCAB_DICT = {}
_VOCAB_PATTERNS = []  # Danh sách (regex_pattern, item) sắp xếp theo độ dài từ khóa giảm dần
_ENTERTAIN_LIST = []

def _normalize(text: str) -> str:
    """Chuẩn hóa chuỗi (chuyển chữ thường, NFC)."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text)).casefold()

def load_dictionary():
    """Đọc file JSON và build Hash Map / List."""
    global _VOCAB_DICT, _VOCAB_PATTERNS, _ENTERTAIN_LIST
    
    # 1. Load data.json (Vocab)
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            _VOCAB_DICT.clear()
            _VOCAB_PATTERNS.clear()
            for item in data:
                keywords = list(item.get("keywords", []))
                for key in ("vi", "vietnamese", "ja_kanji", "kanji", "ja_kana", "japanese_hiragana", "en", "english"):
                    val = item.get(key)
                    if val and isinstance(val, str) and val not in keywords:
                        keywords.append(val)
                for kw in keywords:
                    norm_kw = _normalize(kw)
                    if norm_kw:
                        _VOCAB_DICT[norm_kw] = item

            # Sắp xếp từ khóa theo độ dài giảm dần (ưu tiên từ dài, nhiều từ trước)
            # Khớp theo ranh giới từ (?<!\w)...(?!\w) để loại bỏ hiện tượng 'ao' khớp nhầm trong 'sao', 'tại sao', 'chào'.
            sorted_items = sorted(_VOCAB_DICT.items(), key=lambda x: len(x[0]), reverse=True)
            for kw, item in sorted_items:
                if any('\u3040' <= c <= '\u9fff' for c in kw):
                    pattern = re.compile(re.escape(kw))
                else:
                    pattern = re.compile(rf'(?<!\w){re.escape(kw)}(?!\w)')
                _VOCAB_PATTERNS.append((pattern, item))

            try:
                print(f"✅ [DICTIONARY] Đã load {len(_VOCAB_DICT)} từ khóa từ Hash Map!")
            except Exception:
                pass
        except Exception as e:
            try:
                print(f"⚠️ [DICTIONARY] Lỗi đọc {DATA_PATH}: {e}")
            except Exception:
                pass
            
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

def lookup_vocab(question: str) -> dict | None:
    """Return only a lesson accepted by the shared semantic-gated RAG path."""
    try:
        from server.llm.rag_engine import get_learning_record
        return get_learning_record(question)
    except Exception as exc:
        print(f"⚠️ [DICTIONARY] RAG lookup failed closed: {exc}")
        return None


def extract_display_text(question: str, item: dict) -> tuple[str, str]:
    """
    Trích xuất đúng trường dữ liệu hiển thị (OLED/LED qua MQTT) theo câu hỏi của bé:
    - Nếu bé hỏi tiếng Nhật / Chữ Hán: Lấy ja_kanji (hoặc ja)
    - Nếu bé hỏi tiếng Anh: Lấy trường en
    - Nếu bé hỏi tiếng Việt: Lấy trường vi
    - Mặc định: Ưu tiên ja_kanji (chữ Hán) để hiện lên màn hình OLED của Robot Moon.
    Trả về: (field_name, display_text)
    """
    if not item:
        return "ja_kanji", ""

    norm_q = _normalize(question)

    # 1. Bé hỏi tiếng Anh
    en_markers = ["tiếng anh", "tieng anh", "english", "in english", "bằng tiếng anh", "bang tieng anh"]
    if any(m in norm_q for m in en_markers):
        display_text = str(item.get("en") or item.get("english") or "").strip()
        return "en", display_text

    # 2. Bé hỏi tiếng Việt / nghĩa là gì
    vi_markers = ["tiếng việt", "tieng viet", "vietnamese", "in vietnamese", "nghĩa là gì", "nghia la gi", "nghĩa gì", "dịch sang tiếng việt"]
    if any(m in norm_q for m in vi_markers):
        display_text = str(item.get("vi") or item.get("vietnamese") or "").strip()
        return "vi", display_text

    # 3. Bé hỏi tiếng Nhật / Chữ Hán hoặc mặc định (Robot Moon dạy chữ Hán OLED)
    kanji = str(item.get("ja_kanji") or item.get("kanji") or "").strip()
    if kanji:
        return "ja_kanji", kanji

    ja_text = str(item.get("ja") or item.get("ja_kana") or item.get("japanese_hiragana") or "").strip()
    return "ja", ja_text

import random
from server.llm.pedagogy import is_role_play_request, match_role_play_scenario

def get_role_play(question: str) -> dict | None:
    """Nhận diện ý định nhập vai và bốc kịch bản phù hợp từ entertainment_kids.json."""
    if not is_role_play_request(question):
        return None
    scenarios = [i for i in _ENTERTAIN_LIST if i.get("type") == "role_play"]
    if not scenarios:
        return None
    return match_role_play_scenario(question, scenarios)

def get_entertainment(question: str) -> str | None:
    """Nhận diện ý định giải trí: Đố vui, Sự thật thú vị, hoặc Kịch bản nhập vai."""
    norm_q = _normalize(question)

    # Ý định 1: Nhập vai & Luyện tương tác (Role-play)
    if is_role_play_request(norm_q):
        scenario = get_role_play(question)
        if scenario:
            intro = scenario.get("intro", "")
            first_turn = scenario.get("first_turn", "")
            return f"{intro} {first_turn}".strip()
    
    # Ý định 2: Đố vui
    quiz_markers = ["đố tôi", "đố bé", "đố moon", "câu đố", "đố vui"]
    if any(m in norm_q for m in quiz_markers):
        quizzes = [i for i in _ENTERTAIN_LIST if i.get("type") == "quiz"]
        if quizzes:
            item = random.choice(quizzes)
            return f"{item['question']} ... {item['answer']}"
            
    # Ý định 3: Kể chuyện / Sự thật thú vị
    fact_markers = ["kể chuyện", "sự thật", "thú vị", "có biết không", "kiến thức"]
    if any(m in norm_q for m in fact_markers):
        facts = [i for i in _ENTERTAIN_LIST if i.get("type") == "fact"]
        if facts:
            item = random.choice(facts)
            return item["content"]
            
    return None
