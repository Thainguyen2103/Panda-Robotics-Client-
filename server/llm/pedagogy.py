# -*- coding: utf-8 -*-
"""
=============================================================================
 MODULE SƯ PHẠM NÂNG CAO CHO ROBOT GIÁO DỤC (server/llm/pedagogy.py)
=============================================================================
Cung cấp 2 cơ chế chính:
1. Cơ chế Phản hồi lỗi sai tự động (Pedagogical Error Correction):
   - Nhận diện lỗi ngữ pháp tiếng Anh / tiếng Nhật phổ biến của trẻ em.
   - Cấu trúc phản hồi 3 bước: Khích lệ -> Câu chuẩn xác -> Giải thích ngắn tiếng Việt.
   - Tránh việc robot nói cộc lốc hoặc "Tôi không hiểu".

2. Quản lý tương tác Nhập vai (Role-play & Interactive Practice):
   - Điều phối kịch bản hội thoại ngắn gọn từng lượt (1-2 câu).
   - Khuyến khích trẻ phản xạ nói theo mà không gây quá tải kiến thức.
=============================================================================
"""

import re
import unicodedata
from typing import Dict, Any, Optional, Tuple, List

# ══════════════════════════════════════════════════════════════════════════════
#  1. CÁC MẪU LỖI NGỮ PHÁP TIẾNG ANH & TIẾNG NHẬT PHỔ BIẾN CỦA TRẺ EM
# ══════════════════════════════════════════════════════════════════════════════

# Danh sách mẫu lỗi ngữ pháp tiếng Anh phổ biến kèm cách sửa chuẩn và giải thích sư phạm
_EN_GRAMMAR_PATTERNS = [
    {
        "pattern": re.compile(r"\b(i\s+goes)\b", re.IGNORECASE),
        "target": "I go",
        "encouragement": "Bé giỏi lắm, đã rất tự tin nói tiếng Anh rồi nè!",
        "explanation": "Với chủ ngữ 'I', chúng mình dùng động từ nguyên mẫu 'go', không thêm '-es' bé nhé!",
        "example_correct": "I go to school.",
    },
    {
        "pattern": re.compile(r"\b(he\s+don'?t)\b", re.IGNORECASE),
        "target": "He doesn't",
        "encouragement": "Bé nói gần đúng rồi đó, cố gắng rất tuyệt vời!",
        "explanation": "Với chủ ngữ 'He' (số ít), câu phủ định chúng mình dùng 'doesn't' thay vì 'don't' nha!",
        "example_correct": "He doesn't like apples.",
    },
    {
        "pattern": re.compile(r"\b(she\s+don'?t)\b", re.IGNORECASE),
        "target": "She doesn't",
        "encouragement": "Wow, bé tự tin nói cả câu dài luôn! Moon khen bé nè!",
        "explanation": "Với bạn gái 'She', khi nói không thích hay không làm gì, chúng mình dùng 'doesn't' nha!",
        "example_correct": "She doesn't eat candy.",
    },
    {
        "pattern": re.compile(r"\b(she\s+have)\b", re.IGNORECASE),
        "target": "She has",
        "encouragement": "Bé phát âm rất tốt và rõ ràng nè!",
        "explanation": "Với chủ ngữ 'She', từ có là 'has' chứ không dùng 'have' bé nhé!",
        "example_correct": "She has a cute cat.",
    },
    {
        "pattern": re.compile(r"\b(he\s+have)\b", re.IGNORECASE),
        "target": "He has",
        "encouragement": "Bé nhớ từ vựng rất siêu, chỉ cần chỉnh một xíu là hoàn hảo!",
        "explanation": "Với chủ ngữ 'He', từ có là 'has' bé nha!",
        "example_correct": "He has a big ball.",
    },
    {
        "pattern": re.compile(r"\b(they\s+is)\b", re.IGNORECASE),
        "target": "They are",
        "encouragement": "Bé nói rất trôi chảy, tuyệt vời lắm!",
        "explanation": "'They' là số nhiều (các bạn ấy), nên chúng mình đi với 'are' chứ không dùng 'is' nhé!",
        "example_correct": "They are playing together.",
    },
    {
        "pattern": re.compile(r"\b(we\s+is)\b", re.IGNORECASE),
        "target": "We are",
        "encouragement": "Bé tự tin giao tiếp tiếng Anh thế này là rất đáng khen!",
        "explanation": "'We' nghĩa là chúng mình (nhiều người), nên mình đi cùng 'are' bé nha!",
        "example_correct": "We are happy friends.",
    },
    {
        "pattern": re.compile(r"\b(i\s+am\s+like)\b", re.IGNORECASE),
        "target": "I like",
        "encouragement": "Bé diễn đạt ý rất hay và rõ ràng!",
        "explanation": "Khi nói mình thích cái gì, bé chỉ cần nói 'I like...' là chuẩn rồi, không cần thêm 'am' nha!",
        "example_correct": "I like ice cream.",
    },
    {
        "pattern": re.compile(r"\b(i\s+like\s+play)\b", re.IGNORECASE),
        "target": "I like playing / I like to play",
        "encouragement": "Bé chọn từ rất đúng ngữ cảnh nè!",
        "explanation": "Sau từ 'like', bé nhớ dùng 'playing' hoặc 'to play' để câu nghe thật tự nhiên nhé!",
        "example_correct": "I like to play football.",
    },
    {
        "pattern": re.compile(r"\b(can\s+to\s+([a-z]+))\b", re.IGNORECASE),
        "target": "can \\2",
        "encouragement": "Bé dũng cảm nói câu phức tạp luôn, hoan hô bé!",
        "explanation": "Sau từ 'can' (có thể), động từ đi ngay đằng sau và không cần chữ 'to' bé nhé!",
        "example_correct": "I can swim very well.",
    },
    {
        "pattern": re.compile(r"\b(yesterday\s+i\s+go)\b", re.IGNORECASE),
        "target": "Yesterday I went",
        "encouragement": "Bé kể chuyện rất sinh động nè!",
        "explanation": "'Yesterday' là ngày hôm qua (chuyện đã qua rồi), nên từ 'go' đổi thành 'went' bé nha!",
        "example_correct": "Yesterday I went to the park.",
    },
]

# Danh sách mẫu lỗi tiếng Nhật phổ biến
_JA_GRAMMAR_PATTERNS = [
    {
        "pattern": re.compile(r"(taberu\s*desu|食べるです|たべるです)", re.IGNORECASE),
        "correct": "食べます (Tabemasu)",
        "encouragement": "惜しい！(Oshii - Gần đúng rồi!) Bé phát âm tiếng Nhật rất dễ thương!",
        "explanation": "Động từ 'taberu' khi nói lịch sự chúng mình đổi thành 'tabemasu', không ghép thẳng với 'desu' nha!",
        "example_correct": "りんごを食べます (Ringo o tabemasu - Cháu ăn táo).",
    },
    {
        "pattern": re.compile(r"(nomu\s*desu|飲むです|のむです)", re.IGNORECASE),
        "correct": "飲みます (Nomimasu)",
        "encouragement": "Bé nhớ từ vựng tiếng Nhật giỏi quá!",
        "explanation": "Khi nói lịch sự 'uống', bé hãy dùng 'nomimasu' thay vì 'nomu desu' nhé!",
        "example_correct": "みずを飲みます (Mizu o nomimasu - Cháu uống nước).",
    },
    {
        "pattern": re.compile(r"(kore\s*wa\s*ringo\s*da\s*desu)", re.IGNORECASE),
        "correct": "これは林檎です (Kore wa ringo desu)",
        "encouragement": "Bé nói một câu tiếng Nhật dài thế này là siêu lắm rồi!",
        "explanation": "Trong câu tiếng Nhật lịch sự, mình chỉ dùng 'desu' ở cuối câu thôi, không cần chữ 'da' bé nha!",
        "example_correct": "これは林檎です (Kore wa ringo desu - Đây là quả táo).",
    },
    {
        "pattern": re.compile(r"(watashi\s*no\s*namae\s*desu)", re.IGNORECASE),
        "correct": "私の名前は (Watashi no namae wa... desu)",
        "encouragement": "Bé giới thiệu bản thân rất tự tin và đáng yêu!",
        "explanation": "Câu chuẩn để nói tên là: 'Watashi no namae wa [Tên bé] desu' bé nha!",
        "example_correct": "私の名前はナムです (Watashi no namae wa Namu desu).",
    },
]

# Từ khóa trẻ em hay hỏi để kiểm tra câu nói của mình
_VERIFY_INTENT_MARKERS = [
    "đúng không", "dung khong", "đúng ngữ pháp không", "sửa giúp con", "sửa cho con",
    "con nói thế", "nói thế này", "câu này đúng chưa", "how do you say", "is it correct",
    "correct my", "sửa lỗi", "luyện nói", "thầy sửa", "moon sửa"
]


# ══════════════════════════════════════════════════════════════════════════════
#  2. HÀM KIỂM TRA LỖI SƯ PHẠM TỨC THÌ (FAST PEDAGOGICAL CORRECTION)
# ══════════════════════════════════════════════════════════════════════════════

def fast_pedagogical_correction(question: str) -> Optional[str]:
    """
    Kiểm tra nhanh các lỗi sai ngữ pháp tiếng Anh / tiếng Nhật phổ biến.
    Nếu phát hiện, trả về ngay phản hồi chuẩn 3 bước:
      1. Khích lệ
      2. Câu chuẩn xác
      3. Giải thích ngắn gọn bằng tiếng Việt
    Trả về None nếu không phát hiện mẫu lỗi cụ thể.
    """
    if not question:
        return None

    norm = unicodedata.normalize("NFC", question)

    # 1. Quét mẫu lỗi tiếng Anh
    for item in _EN_GRAMMAR_PATTERNS:
        match = item["pattern"].search(norm)
        if match:
            # Nếu người dùng có ý hỏi kiểm tra hoặc trực tiếp nói câu chứa lỗi
            encouragement = item["encouragement"]
            correct_sample = item["example_correct"]
            explanation = item["explanation"]
            return f"{encouragement} Câu chuẩn xác là: \"{correct_sample}\". {explanation}"

    # 2. Quét mẫu lỗi tiếng Nhật
    for item in _JA_GRAMMAR_PATTERNS:
        match = item["pattern"].search(norm)
        if match:
            encouragement = item["encouragement"]
            correct_sample = item["example_correct"]
            explanation = item["explanation"]
            return f"{encouragement} Câu chuẩn xác là: \"{correct_sample}\". {explanation}"

    return None


def detect_pedagogical_context(question: str) -> Tuple[bool, Optional[str]]:
    """
    Xác định xem câu nói của bé có phải là một lượt luyện nói ngoại ngữ / nhờ sửa câu không.
    Trả về: (is_pedagogical_context, language)
    """
    norm = unicodedata.normalize("NFC", question or "").casefold()

    is_asking_verify = any(m in norm for m in _VERIFY_INTENT_MARKERS)

    # Nhận diện nếu câu thuần tiếng Anh
    words = [w for w in re.findall(r"[a-zA-Z]+", norm) if len(w) > 1]
    is_pure_english = len(words) >= 3 and norm.isascii() and not any(c in "ăâđêôơư" for c in norm)

    # Nhận diện nếu câu thuần tiếng Nhật
    has_japanese = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", norm))

    if is_asking_verify:
        if has_japanese:
            return True, "ja"
        return True, "en"

    if is_pure_english:
        return True, "en"

    if has_japanese and len(norm) >= 6:
        return True, "ja"

    return False, None


# ══════════════════════════════════════════════════════════════════════════════
#  3. MODULE NHẬP VAI & LUYỆN TẬP TƯƠNG TÁC (ROLE-PLAY)
# ══════════════════════════════════════════════════════════════════════════════

# Các từ khóa kích hoạt trò chơi nhập vai
ROLE_PLAY_TRIGGER_MARKERS = [
    "đóng vai", "chơi đóng vai", "nhập vai", "chơi bán hàng", "bán đồ hàng",
    "tiệm bánh", "mua bánh", "cửa hàng tiện lợi", "làm quen", "kết bạn",
    "bác sĩ", "khám bệnh", "nhà hàng", "gọi món", "sở thú", "vườn thú",
    "hỏi đường", "role play", "roleplay", "chơi trò chơi đóng kịch", "tập hội thoại"
]

# Các từ khóa kết thúc / thoát vai
ROLE_PLAY_EXIT_MARKERS = [
    "dừng chơi", "nghỉ chơi", "hết chơi", "không chơi nữa", "thôi không chơi",
    "kết thúc", "dừng lại", "stop playing", "stop game", "ra khỏi vai"
]


def is_role_play_request(question: str) -> bool:
    """Kiểm tra câu nói có mang ý định muốn bắt đầu chơi nhập vai hay không."""
    norm = unicodedata.normalize("NFC", question or "").casefold()
    return any(m in norm for m in ROLE_PLAY_TRIGGER_MARKERS)


def is_role_play_exit(question: str) -> bool:
    """Kiểm tra xem bé có muốn dừng trò chơi đóng vai không."""
    norm = unicodedata.normalize("NFC", question or "").casefold()
    return any(m in norm for m in ROLE_PLAY_EXIT_MARKERS)


def match_role_play_scenario(question: str, scenarios: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Tìm kịch bản nhập vai phù hợp nhất từ danh sách kịch bản trong entertainment_kids.json.
    Nếu không chỉ rõ chủ đề cụ thể, chọn kịch bản đầu tiên hoặc ngẫu nhiên.
    """
    if not scenarios:
        return None

    norm = unicodedata.normalize("NFC", question or "").casefold()

    # 1. So khớp theo từ khóa cụ thể của kịch bản
    best_match = None
    max_matches = 0

    for sc in scenarios:
        kws = sc.get("keywords", [])
        matched = sum(1 for kw in kws if kw.lower() in norm)
        if matched > max_matches:
            max_matches = matched
            best_match = sc

    if best_match:
        return best_match

    # 2. Nếu người dùng chỉ nói chung chung ("chơi đóng vai đi", "chúng mình chơi nhập vai nhé")
    # Ưu tiên kịch bản Tiệm bánh ngọt quen thuộc nhất với trẻ nhỏ
    for sc in scenarios:
        if sc.get("id") == "roleplay_bakery_en":
            return sc

    return scenarios[0]


def format_role_play_system_instruction(scenario: Dict[str, Any]) -> str:
    """
    Tạo chỉ thị hệ thống chuyên biệt (Prompt Injection) khi robot đang trong phiên nhập vai.
    """
    title = scenario.get("title", "Kịch bản nhập vai")
    robot_role = scenario.get("robot_role", "Bạn gấu Moon")
    child_role = scenario.get("child_role", "Bé")
    language = scenario.get("language", "en")
    pedagogical_goal = scenario.get("pedagogical_goal", "Luyện phản xạ giao tiếp tự nhiên")
    suggested = " / ".join(scenario.get("suggested_prompts", [])[:2])

    lang_desc = "tiếng Anh" if language == "en" else ("tiếng Nhật" if language == "ja" else "song ngữ Anh - Nhật")

    return f"""[ROLE-PLAY & INTERACTIVE PRACTICE MODE ACTIVE]
Bạn và bé đang chơi kịch bản: "{title}".
- Vai của bạn (Moon): {robot_role}
- Vai của bé: {child_role}
- Mục tiêu học tập: {pedagogical_goal}
- Gợi ý câu bé có thể nói: {suggested}

QUY TẮC DẪN DẮT TỪNG LƯỢT:
1. Tiếp tục đóng đúng vai nhân vật của bạn, nói CỰC KỲ NGẮN GỌN (1-2 câu).
2. Nói câu tiếng {lang_desc} đơn giản, kèm lời dịch/gợi ý tiếng Việt trong ngoặc nếu cần.
3. Luôn kết thúc bằng một câu hỏi gợi mở hoặc mời bé nói theo (ví dụ: "Bé thử nói '...' xem nào!").
4. NGUYÊN TẮC SƯ PHẠM: Nếu bé nói sai hoặc lúng túng, áp dụng 3 bước: Khích lệ -> Đưa câu chuẩn -> Giải thích 1 câu tiếng Việt ngắn, rồi tiếp tục kịch bản."""


def format_pedagogical_error_instruction() -> str:
    """
    Chỉ thị bổ sung khi phát hiện trẻ đang luyện tập ngoại ngữ cần sửa lỗi kiên nhẫn.
    """
    return """[PEDAGOGICAL COACHING INSTRUCTION]:
Bé đang luyện giao tiếp ngoại ngữ. Nếu câu của bé có lỗi ngữ pháp hoặc diễn đạt chưa tự nhiên:
1. TUYỆT ĐỐI KHÔNG nói "Tôi không hiểu" hay trả lời cộc lốc.
2. Hãy phản hồi theo đúng cấu trúc 3 bước sư phạm:
   - Bước 1: Khích lệ nỗ lực của bé thật chân thành, vui vẻ.
   - Bước 2: Đưa ra câu chuẩn xác tự nhiên để bé đọc theo.
   - Bước 3: Giải thích ngắn gọn 1 câu bằng tiếng Việt dễ hiểu cho trẻ em."""
