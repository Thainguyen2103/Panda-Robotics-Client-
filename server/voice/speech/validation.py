"""Conservative validation for STT text."""
import math
import re
import unicodedata


STT_HALLUCINATION_PHRASES = (
    "subscribe", "subtitles by", "amara.org", "thank you for watching",
    "thanks for watching", "like and subscribe", "see you next time",
    "đăng ký kênh", "không bỏ lỡ", "video hấp dẫn", "hẹn gặp lại",
    "ủng hộ kênh", "kênh ghiền",
)


def _correction_tokens(text):
    normalized = unicodedata.normalize("NFC", text or "")
    return re.findall(r"[\w%+.-]+", normalized, flags=re.UNICODE)


def safe_asr_correction(original, candidate):
    """Accept spelling repair only when meaning-bearing tokens are preserved."""
    source = re.sub(r"\s+", " ", str(original or "")).strip()
    fixed = re.sub(r"\s+", " ", str(candidate or "")).strip().strip('"').strip()
    if not source or not fixed:
        return source
    source_words = _correction_tokens(source)
    fixed_words = _correction_tokens(fixed)
    if not source_words or not fixed_words:
        return source
    allowed_word_delta = max(1, math.ceil(len(source_words) * .3))
    if abs(len(source_words) - len(fixed_words)) > allowed_word_delta:
        return source
    ratio = len(fixed) / max(1, len(source))
    if ratio < .55 or ratio > 1.65:
        return source
    protected = {
        token.casefold() for token in source_words
        if any(char.isdigit() for char in token) or (len(token) >= 2 and token.isupper())
    }
    if not protected.issubset({token.casefold() for token in fixed_words}):
        return source
    if re.search(r"(?<!\w)moon(?!\w)", source, re.I) and not re.search(
            r"(?<!\w)moon(?!\w)", fixed, re.I):
        return source
    return fixed


def reliable_transcript(result):
    """Keep raw STT text; confidence rejects noise but never rewrites words."""
    text = (result.get('text') or '').strip()
    normalized = text.casefold()
    if any(phrase in normalized for phrase in STT_HALLUCINATION_PHRASES):
        return ''
    segments = result.get('segments') or []
    if segments and any(s.get('no_speech_prob', 0) > .45 or
                        s.get('avg_logprob', 0) < -1.0 or
                        s.get('compression_ratio', 0) > 2.4 for s in segments):
        return ''
    return text
