"""Fast, deterministic intent routing for the Moon tutoring chat pipeline.

This module deliberately makes no model or network calls. Ambiguous input is
sent through the knowledge path so existing RAG grounding remains the safe
default; explicit social chat bypasses retrieval.
"""
from dataclasses import dataclass
from enum import Enum
import re
import unicodedata


class Intent(str, Enum):
    KNOWLEDGE_QNA = "KNOWLEDGE_QNA"
    CHITCHAT = "CHITCHAT"
    GRAMMAR_FIX = "GRAMMAR_FIX"
    PRONUNCIATION = "PRONUNCIATION"
    CURRICULUM_NEXT = "CURRICULUM_NEXT"
    STUDY_HELP = "STUDY_HELP"


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    confidence: float
    use_rag: bool
    reason: str


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFC", str(text or "")).casefold()
    value = " ".join(value.split())
    # Accent-insensitive Vietnamese matching while preserving Japanese script.
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").replace("đ", "d")


STUDY_HELP_RESPONSE = "Robot rất sẵn lòng! Bé muốn học tiếng Anh hay tiếng Nhật nè? Bé đã học đến đâu rồi (như bảng chữ cái hay từ vựng chủ đề gì) để robot hỗ trợ bé tốt nhất nha!"

_STUDY_HELP_SESSIONS: dict[str, dict] = {}


def set_study_help_state(conversation_id: str, state: dict | None) -> None:
    conv_id = str(conversation_id or "default")
    if state is None:
        _STUDY_HELP_SESSIONS.pop(conv_id, None)
    else:
        _STUDY_HELP_SESSIONS[conv_id] = state


def get_study_help_state(conversation_id: str) -> dict | None:
    return _STUDY_HELP_SESSIONS.get(str(conversation_id or "default"))


def clear_study_help_state(conversation_id: str) -> None:
    _STUDY_HELP_SESSIONS.pop(str(conversation_id or "default"), None)


def is_study_help_query(text: str) -> bool:
    """Nhận diện các cụm từ nhờ học tập chung chung.
    Kết hợp các keyword như ['giúp', 'dạy', 'học', 'kèm'] và ['được không', 'với', 'nhé', 'không', 'giùm', 'hộ'].
    Ví dụ: 'Bạn có thể giúp tôi học không?', 'Dạy mình học tiếng Anh/tiếng Nhật với', 'Kèm bé học nhé'.
    """
    if not text:
        return False
    norm = _normalize(text)

    # Không cướp lời các câu hỏi tra cứu từ vựng cụ thể hoặc kiểm tra ngữ pháp cụ thể
    specific_lookup = any(m in norm for m in [
        "la gi", "nghia la gi", "doc la gi", "viet la gi", "dich cau", "dich sang",
        "doc the nao", "viet the nao", "sua giup", "sua cau", "kiem tra ngu phap", "dung chua"
    ])
    if specific_lookup:
        return False

    # 1. Các cụm từ mẫu cố định
    fixed_patterns = (
        "giup toi hoc", "giup minh hoc", "giup be hoc", "giup em hoc", "giup to hoc",
        "day minh hoc", "day to hoc", "day be hoc", "day em hoc", "day toi hoc",
        "kem minh hoc", "kem to hoc", "kem be hoc", "kem em hoc", "kem toi hoc",
        "hoc tieng anh voi", "hoc tieng nhat voi", "day tieng anh voi", "day tieng nhat voi",
        "day minh tieng", "day to tieng", "day be tieng",
        "hoc cung minh", "hoc cung be", "hoc voi minh", "hoc cung to",
        "can you teach me", "can you help me learn", "help me learn",
        "teach me english", "teach me japanese", "teach me",
        "勉強を教えて", "日本語を教えて", "英語を教えて",
    )
    if any(p in norm for p in fixed_patterns):
        return True

    # 2. Kết hợp từ hành động (action) và từ cầu khiến/nhờ vả (request)
    action_words = ("giup", "day", "hoc", "kem", "chi cho", "huong dan")
    request_endings = (
        "duoc khong", "duoc ko", "voi", "nhe", "khong", "ko", "nha", "di ma",
        "giup toi", "giup minh", "giup be", "giup to"
    )

    has_action = any(w in norm for w in action_words)
    # Match request phrases at the end of a token sequence. Substring matching
    # made "nha" match the start of "nhat" (Japanese), so a learner's answer
    # such as "muốn học về gia đình bằng tiếng Nhật" was mistaken for a new
    # generic request and got the same clarification again.
    request_text = norm.rstrip(" .?!,;:~")
    has_request = any(
        request_text == ending or request_text.endswith(f" {ending}")
        for ending in request_endings
    )

    if has_action and has_request:
        if any(w in norm for w in ("hoc", "day", "kem")):
            return True

    return False


def get_fast_chitchat(text: str) -> str | None:
    """Trả về câu phản hồi chào hỏi, cảm ơn, tạm biệt nhanh chuẩn xác tại Fast-Path (0ms)."""
    norm = _normalize(text)
    if not norm:
        return None
    # Xóa dấu câu thừa để so khớp chính xác (vd: "Chào Moon!" -> "chao moon")
    norm = re.sub(r"[!?,.:;~]+", " ", norm).strip()
    norm = " ".join(norm.split())

    # Chào hỏi
    greetings = (
        "chao moon", "xin chao", "chao ban", "chao cau", "chao robot",
        "hello moon", "hi moon", "hello", "hi robot", "konnichiwa", "こんにちは",
    )
    if any(norm == g or norm.startswith(f"{g} ") or norm.endswith(f" {g}") for g in greetings):
        return "Xin chào bé yêu! Moon rất vui được gặp bé, hôm nay chúng mình cùng học gì nào?"

    # Cảm ơn
    thanks = ("cam on", "cam on nhe", "cam on moon", "thank you", "thanks", "arigatou", "ありがとう")
    if any(norm == t or norm.startswith(f"{t} ") or norm.endswith(f" {t}") for t in thanks):
        return "Không có chi nè! Moon luôn ở đây để đồng hành và học tập cùng bé nha!"

    # Hỏi thăm sức khỏe
    health = ("ban khoe khong", "khoe khong", "ban the nao", "hom nay the nao", "how are you", "genki", "元気ですか")
    if any(h in norm for h in health):
        return "Moon khỏe lắm và tràn đầy năng lượng để cùng bé khám phá bài học mới nè! Còn bé thì sao?"

    # Tạm biệt
    goodbyes = ("tam biet", "bye bye", "goodbye", "good night", "chuc ngu ngon", "hen gap lai", "sayonara", "さようなら")
    if any(g in norm for g in goodbyes):
        return "Tạm biệt bé nhé! Chúc bé học thật giỏi và hẹn sớm gặp lại bé nha!"

    return None


_RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (Intent.STUDY_HELP, (
        "giup toi hoc", "giup minh hoc", "giup be hoc", "day minh hoc", "day to hoc",
        "day be hoc", "day em hoc", "kem minh hoc", "kem to hoc", "kem be hoc",
        "hoc tieng anh voi", "hoc tieng nhat voi", "day tieng anh voi", "day tieng nhat voi",
        "day minh tieng", "day to tieng", "day be tieng", "can you teach me", "help me learn",
        "teach me", "勉強を教えて", "日本語を教えて", "英語を教えて",
    )),
    (Intent.CURRICULUM_NEXT, (
        "bai tiep theo", "hoc bai gi tiep", "tien do hoc", "hoan thanh n5",
        "hoan thanh n4", "lesson next", "learning progress", "finished n5",
        "次のレッスン", "学習の進捗", "n5を終わった",
    )),
    (Intent.GRAMMAR_FIX, (
        "sua giup", "sua cau", "kiem tra ngu phap", "cau nay dung chua",
        "dung ngu phap khong", "dung ngu phap chua", "correct my sentence", "fix my grammar",
        "is this sentence correct", "文法を直して", "この文は正しい",
    )),
    (Intent.PRONUNCIATION, (
        "kiem tra phat am", "moon nghe to doc", "doc mau", "phat am tu",
        "how do i pronounce", "check my pronunciation", "say it aloud",
        "発音をチェック", "発音して", "読んでみて",
    )),
    (Intent.CHITCHAT, (
        "chao moon", "xin chao", "cam on", "cam on nhe", "ban the nao",
        "hom nay ban the nao", "khen ban", "ban khoe khong", "tam biet",
        "hello moon", "hi moon", "how are you", "thank you", "thanks",
        "good morning", "good night", "こんにちは", "ありがとう", "元気ですか",
    )),
)

_KNOWLEDGE_MARKERS = (
    "la gi", "nghia la gi", "tieng nhat", "tieng anh", "tu vung", "ngu phap",
    "giai thich", "dich cau", "dich sang", "con meo", "mat troi", "kanji",
    "hiragana", "romaji", "what is", "what does", "meaning", "translate",
    "in japanese", "in english", "explain", "vocabulary", "grammar", "which word",
    "日本語", "英語", "意味", "翻訳", "文法", "漢字", "ひらがな", "ローマ字",
)


class IntentRouter:
    """Classify learner text in-process without invoking an LLM."""

    def classify(self, text: str) -> IntentDecision:
        normalized = _normalize(text)
        if not normalized:
            return IntentDecision(Intent.KNOWLEDGE_QNA, 0.0, True, "empty_or_uncertain_fallback")

        if is_study_help_query(text):
            return IntentDecision(Intent.STUDY_HELP, 0.95, False, "matched_study_help_rule")

        for intent, markers in _RULES:
            if any(marker in normalized for marker in markers):
                return IntentDecision(intent, 0.95, intent is Intent.KNOWLEDGE_QNA,
                                      f"matched_{intent.value.lower()}_rule")

        if any(marker in normalized for marker in _KNOWLEDGE_MARKERS):
            return IntentDecision(Intent.KNOWLEDGE_QNA, 0.85, True, "matched_knowledge_rule")

        # Conservative fallback keeps ambiguous learning questions grounded.
        return IntentDecision(Intent.KNOWLEDGE_QNA, 0.35, True, "uncertain_default_to_knowledge")


PROMPT_OVERRIDES = {
    Intent.STUDY_HELP: (
        "Bé đang nhờ hỗ trợ học tập hoặc trả lời về trình độ học. "
        "Hãy động viên bé ấm áp và đưa ra hướng dẫn học tập vừa sức trong 1-2 câu ngắn."
    ),
    Intent.CHITCHAT: (
        "Đây là trò chuyện xã giao. Hãy đáp lại tự nhiên, ngắn gọn, thân thiện như Moon; "
        "không biến câu chào hỏi thành bài giảng và không bịa thông tin thời gian thực."
    ),
    Intent.GRAMMAR_FIX: (
        "Đây là yêu cầu sửa câu. Nhẹ nhàng khích lệ, đưa câu đã sửa, rồi giải thích "
        "một quy tắc ngắn. Nếu câu thiếu ngữ cảnh, hỏi lại thay vì đoán."
    ),
    Intent.PRONUNCIATION: (
        "Đây là luyện phát âm. Nếu chỉ nhận được văn bản, không khẳng định đã nghe hoặc "
        "đánh giá âm thanh; hãy hướng dẫn cách đọc hoặc yêu cầu người học gửi audio qua "
        "chế độ phân tích phát âm khi tính năng đó khả dụng."
    ),
    Intent.CURRICULUM_NEXT: (
        "Đây là câu hỏi về lộ trình học. Chỉ nêu tiến độ đã có trong hội thoại hiện tại; "
        "Moon chưa có bộ theo dõi tiến độ bền vững, vì vậy hãy hỏi bài gần nhất nếu cần."
    ),
}

