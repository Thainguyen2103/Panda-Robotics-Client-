"""Language routing and output checks for Moon's multilingual conversations.

The language being discussed is not always the language the user expects Moon
to answer in.  For example, ``こんにちは nghĩa là gì?`` contains Japanese text,
but its conversational frame is Vietnamese.  This module keeps that policy
separate from the LLM/RAG implementation so it can be tested independently.
"""

from __future__ import annotations

import re
import unicodedata


_VIETNAMESE_MARKERS = {
    "ai", "bao", "bạn", "biết", "bây", "bằng", "cho", "chào", "chưa",
    "có", "của", "dịch", "đang", "đâu", "đọc", "được", "gì", "giờ",
    "hãy", "hôm", "không", "là", "mình", "muốn", "nghĩa", "nào", "nay",
    "nhiêu", "ơi", "sao", "thế", "tiếng", "trong", "tại", "tôi", "và",
    "vậy", "viết", "việt", "với", "xin",
}
_ENGLISH_MARKERS = {
    "am", "answer", "are", "can", "could", "did", "do", "does", "english",
    "hello", "hey", "how", "i", "in", "is", "japanese", "know", "mean",
    "means", "me", "my", "please", "should", "tell", "the", "today",
    "translate", "vietnamese", "what", "when", "where", "who", "why",
    "would", "you", "your",
}
_VIETNAMESE_DISTINCTIVE = set(
    "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
)
_JAPANESE_ANY = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff]"
)
_JAPANESE_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_WORD_PATTERN = re.compile(r"[^\W\d_]+", flags=re.UNICODE)

_EXPLICIT_LANGUAGE_PATTERNS = {
    "vi": (
        r"trả\s+lời.{0,24}(?:bằng|tiếng)\s+việt",
        r"answer.{0,24}(?:in\s+)?vietnamese",
        r"ベトナム語で(?:答えて|話して)",
    ),
    "en": (
        r"trả\s+lời.{0,24}(?:bằng|tiếng)\s+anh",
        r"answer.{0,24}(?:in\s+)?english",
        r"英語で(?:答えて|話して)",
    ),
    "ja": (
        r"trả\s+lời.{0,24}(?:bằng|tiếng)\s+nhật",
        r"answer.{0,24}(?:in\s+)?japanese",
        r"日本語で(?:答えて|話して)",
    ),
}

# High-confidence, meaning-preserving repairs seen in multilingual STT/input.
# Keep this deliberately small: broad rewriting belongs to the ASR correction
# stage, while these forms are safe enough to normalize before every provider.
_SAFE_TEXT_REPAIRS = {
    "こんいちは": "こんにちは",
    "こんにちわ": "こんにちは",
}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").casefold()


def normalize_user_question(question: str) -> str:
    """Apply only unambiguous multilingual spelling/STT repairs."""
    fixed = unicodedata.normalize("NFC", question or "")
    for wrong, correct in _SAFE_TEXT_REPAIRS.items():
        fixed = fixed.replace(wrong, correct)
    return fixed


def _scores(text: str) -> tuple[int, int, list[str]]:
    words = _WORD_PATTERN.findall(text)
    vi_score = sum(word in _VIETNAMESE_MARKERS for word in words)
    en_score = sum(word in _ENGLISH_MARKERS for word in words)
    if any(char in _VIETNAMESE_DISTINCTIVE for char in text):
        vi_score += 2
    return vi_score, en_score, words


def _explicit_language(text: str) -> str | None:
    for language, patterns in _EXPLICIT_LANGUAGE_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            return language
    return None


def response_language(question: str) -> str:
    """Infer the requested reply language from the latest spoken turn.

    Explicit requests win.  Otherwise the surrounding Vietnamese/English
    sentence wins over a quoted Japanese word.  Japanese is selected when the
    utterance itself is Japanese rather than merely mentioning Japanese text.
    """
    normalized = _normalize(question)
    explicit = _explicit_language(normalized)
    if explicit:
        return explicit

    vi_score, en_score, words = _scores(normalized)
    has_japanese = bool(_JAPANESE_ANY.search(normalized))

    if vi_score and en_score:
        # Preserve natural code-switching when both languages form the actual
        # sentence, e.g. "Bạn know who I am?". A single quoted foreign term is
        # not in either marker set, so it does not trigger this branch.
        if min(vi_score, en_score) >= 2 and abs(vi_score - en_score) <= 1:
            return "adaptive"

    # A clear Vietnamese or English question frame can contain a foreign term.
    if vi_score >= 2 and vi_score >= en_score:
        return "vi"
    if en_score >= 2 and en_score > vi_score:
        return "en"
    if has_japanese:
        return "ja"

    if vi_score >= 1 and vi_score > en_score:
        return "vi"
    if not vi_score and len(words) >= 2 and normalized.isascii():
        return "en"
    return "adaptive"


def response_language_instruction(question: str) -> str:
    language = response_language(question)
    if language == "en":
        return (
            "[Response language for the latest turn] Reply only in natural "
            "English. A foreign word quoted by the user is the topic, not a "
            "signal to switch the whole answer to that language."
        )
    if language == "vi":
        return (
            "[Ngôn ngữ trả lời cho lượt mới nhất] Chỉ trả lời bằng tiếng Việt "
            "tự nhiên. Từ nước ngoài trong câu có thể chỉ là đối tượng người "
            "dùng đang hỏi, không phải yêu cầu đổi ngôn ngữ trả lời."
        )
    if language == "ja":
        return (
            "[最新ターンの応答言語] 自然で分かりやすい日本語だけで答えてください。"
            "引用された外国語の単語は説明の対象として扱ってください。"
        )
    return (
        "[Response language for the latest turn] Infer the dominant language "
        "and reply naturally in that language. Code-switch only where it helps: "
        "keep familiar English technical terms, product names, and phrases when "
        "they are clearer than a forced translation. Do not duplicate the whole "
        "answer in two languages unless the user explicitly asks for translation."
    )


def response_language_matches(answer: str, expected: str) -> bool:
    """Return whether a generated answer uses the expected main language."""
    if expected == "adaptive":
        return True

    normalized = _normalize(answer)
    if not normalized.strip():
        return False
    vi_score, en_score, words = _scores(normalized)
    has_kana = bool(_JAPANESE_KANA.search(normalized))

    if expected == "ja":
        # Kana separates a Japanese sentence from an accidental Chinese answer.
        return has_kana
    if expected == "vi":
        # Japanese/English terms may legitimately be quoted inside a Vietnamese
        # explanation; judge the surrounding sentence instead of banning them.
        return vi_score >= 2 or any(
            char in _VIETNAMESE_DISTINCTIVE for char in normalized
        )
    if expected == "en":
        if any(char in _VIETNAMESE_DISTINCTIVE for char in normalized):
            return False
        if en_score >= 2:
            return True
        ascii_letters = sum(char.isascii() and char.isalpha() for char in normalized)
        letters = sum(char.isalpha() for char in normalized)
        return bool(words) and letters > 0 and ascii_letters / letters >= 0.85
    return True


def strict_retry_instruction(language: str) -> str:
    labels = {
        "vi": "Vietnamese (Tiếng Việt)",
        "en": "English",
        "ja": "Japanese (日本語)",
    }
    return (
        "[Language correction] Your draft used the wrong response language. "
        f"Regenerate the answer from scratch using only {labels[language]}. "
        "Keep quoted foreign terms only when they are necessary to answer the question."
    )


def language_failure_message(language: str) -> str:
    if language == "en":
        return "Moon could not answer in the right language. Please try again."
    if language == "ja":
        return "正しい言語で回答できませんでした。もう一度お願いします。"
    return "Moon chưa thể trả lời đúng ngôn ngữ. Bạn thử hỏi lại nhé!"
