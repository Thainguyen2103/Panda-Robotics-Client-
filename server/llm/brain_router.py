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


_RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
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

        for intent, markers in _RULES:
            if any(marker in normalized for marker in markers):
                return IntentDecision(intent, 0.95, intent is Intent.KNOWLEDGE_QNA,
                                      f"matched_{intent.value.lower()}_rule")

        if any(marker in normalized for marker in _KNOWLEDGE_MARKERS):
            return IntentDecision(Intent.KNOWLEDGE_QNA, 0.85, True, "matched_knowledge_rule")

        # Conservative fallback keeps ambiguous learning questions grounded.
        return IntentDecision(Intent.KNOWLEDGE_QNA, 0.35, True, "uncertain_default_to_knowledge")


PROMPT_OVERRIDES = {
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

