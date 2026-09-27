"""Legacy transcript filters used by the local Brain pipeline."""
import re
import unicodedata


HALLUCINATION_BLACKLIST = {
    "hello", "hello.", "hi", "hey", "you", "you.", "thank you", "thanks",
    "thank you for watching", "thanks for watching", "subscribe",
    "like and subscribe", "please subscribe", "see you next time",
    "bye", "goodbye", "vâng", "dạ", "ừ", "oh", "uh", "hmm", "the", "a",
    "subtitles by", "amara.org", "okay", "ok", "okay.", "i know",
    "okay, i know", "you know", "i see", "oh well", "right", "yes", "no",
    "good", "really", "really?",
}
HALLUCINATION_TOKENS = (
    "subscribe", "subtitles by", "amara.org", "thank you for watching",
    "thanks for watching", "like and subscribe", "see you next time",
    "đăng ký kênh", "cho kênh", "kênh ghiền", "theo dõi", "hẹn gặp lại",
    "ủng hộ kênh", "cảm ơn các bạn",
)
NON_LATIN_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\u0400-\u04ff\u0600-\u06ff\uac00-\ud7af]")


def strip_diacritics(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_hallucination(text: str) -> bool:
    if not text:
        return True
    value = text.strip()
    if len(value) <= 2:
        return True
    lowered = value.lower()
    return (lowered.strip(".!? ") in HALLUCINATION_BLACKLIST
            or any(token in lowered for token in HALLUCINATION_TOKENS)
            or bool(NON_LATIN_RE.search(value)))


def levenshtein(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 3
    previous = list(range(len(b) + 1))
    for index, char_a in enumerate(a, 1):
        current = [index]
        for other_index, char_b in enumerate(b, 1):
            current.append(min(previous[other_index] + 1, current[other_index - 1] + 1,
                               previous[other_index - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def contains_wake_word(text: str) -> bool:
    from server.voice.wake.matcher import wake_tail
    return wake_tail(text or "") is not None
