"""Literal and conservatively inferred matches for Moon's wake word."""
import re
import unicodedata

from server.voice.speech.validation import STT_HALLUCINATION_PHRASES


_MOON_NARROW_ALIASES = {
    'moon', 'mun', 'muun', 'moun', 'moom', 'moone', 'mon', 'muon', 'mune',
}
_MOON_DIRECT_CALL_ALIASES = _MOON_NARROW_ALIASES | {'mua'}
_MOON_EN_ALIASES = _MOON_NARROW_ALIASES | {
    'mom', 'mum', 'moan', 'morn', 'move', 'man', 'noon', 'mua',
}


def wake_tail(text):
    text = unicodedata.normalize("NFC", text)
    match = re.search(r"(?<!\w)moon(?!\w)", text, re.I)
    if match is None:
        return None
    tail = text[match.end():].lstrip(" ,.!?:;—-")
    return re.sub(r"^ơi\b[\s,.!?:;—-]*", "", tail, flags=re.I).strip()


def possible_moon_miss(text):
    normalized = unicodedata.normalize("NFC", text or "").lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return True
    return normalized in {
        "mun", "mun ơi", "hey mun", "mùn", "mùn ơi", "hey mùn",
        "muôn", "muôn ơi", "hey muôn", "muun", "muun ơi", "hey muun",
    }


def should_verify_wake(text, duration_ms, max_sec=3.0, max_words=3):
    if possible_moon_miss(text):
        return True
    normalized = unicodedata.normalize("NFC",text or "").casefold()
    words = re.findall(r"\w+",normalized,flags=re.UNICODE)
    return (0 < len(words) <= max_words and duration_ms <= max_sec*1000
            and not {"muốn","môn","món"}.intersection(words))


def _english_wake_token(text):
    normalized = unicodedata.normalize('NFC', text or '').casefold()
    if any(word in {'môn', 'món', 'muốn'} for word in re.findall(r'\w+', normalized)):
        return None, False
    ascii_text = ''.join(c for c in unicodedata.normalize('NFD', normalized)
                         if unicodedata.category(c) != 'Mn')
    words = re.findall(r'[a-z]+', ascii_text)
    called = bool(words and words[0] in {'hey', 'hi', 'hay', 'he'})
    if called:
        words = words[1:]
    if words and words[-1] == 'oi':
        words = words[:-1]
    return (words[0], called) if len(words) == 1 else (None, called)


def confirmed_wake_tail(primary, verification):
    primary_text = (primary or '').strip()
    verification_text = (verification or '').strip()
    if not verification_text:
        return None
    if not primary_text:
        verify_token, verify_called = _english_wake_token(verification)
        return '' if verify_called and verify_token in _MOON_DIRECT_CALL_ALIASES else None
    primary_exact = wake_tail(primary)
    verification_exact = wake_tail(verification)
    primary_token, primary_called = _english_wake_token(primary)
    verify_token, verify_called = _english_wake_token(verification)
    primary_narrow = (primary_exact is not None or
                      (possible_moon_miss(primary) and bool(primary_text)) or
                      primary_token in _MOON_NARROW_ALIASES)
    verify_narrow = (verification_exact is not None or
                     (possible_moon_miss(verification) and bool(verification_text)) or
                     verify_token in _MOON_NARROW_ALIASES)
    primary_wide = primary_token in _MOON_EN_ALIASES
    verify_wide = verify_token in _MOON_EN_ALIASES
    if not ((primary_narrow and verify_narrow) or
            (primary_wide and verify_wide and (primary_called or verify_called))):
        return None
    if primary_exact is not None:
        return primary_exact
    if verification_exact is not None:
        return verification_exact
    return ''


def confident_wake_tail(text):
    literal = wake_tail(text)
    if literal is not None:
        return literal
    original = unicodedata.normalize('NFC', text or '')
    normalized = original.casefold()
    word_matches = list(re.finditer(r'[^\W\d_]+', normalized, flags=re.UNICODE))
    raw_words = [match.group(0) for match in word_matches]
    folded = [
        ''.join(c for c in unicodedata.normalize('NFD', word)
                if unicodedata.category(c) != 'Mn')
        for word in raw_words
    ]
    call_prefixes = {'hey', 'hi', 'hay', 'he', 'e', 'nay', 'alo', 'goi', 'chao'}
    call_fillers = call_prefixes | {'oi'}
    ambiguous_vietnamese = {'môn', 'món'}
    name_indexes = [
        index for index, word in enumerate(folded)
        if word in _MOON_DIRECT_CALL_ALIASES and raw_words[index] != 'muốn'
    ]
    if name_indexes and all(
            word in _MOON_DIRECT_CALL_ALIASES or word in call_fillers
            for word in folded):
        return ''

    def tail_after(index, skip_oi=False):
        end = word_matches[index].end()
        if skip_oi and index + 1 < len(folded) and folded[index + 1] == 'oi':
            end = word_matches[index + 1].end()
        return original[end:].lstrip(" ,.!?:;—-").strip()

    if (len(folded) >= 2 and folded[0] in call_prefixes
            and folded[1] in _MOON_DIRECT_CALL_ALIASES and raw_words[1] != 'muốn'):
        return tail_after(1, skip_oi=True)
    if (len(folded) >= 2 and folded[0] in _MOON_DIRECT_CALL_ALIASES
            and folded[1] == 'oi' and raw_words[0] != 'muốn'):
        return tail_after(0, skip_oi=True)
    if len(folded) == 1 and folded[0] in _MOON_NARROW_ALIASES and raw_words[0] != 'muốn':
        return ''
    if (folded and folded[0] in _MOON_DIRECT_CALL_ALIASES
            and raw_words[0] not in ambiguous_vietnamese | {'muốn'}):
        return tail_after(0, skip_oi=True)
    return None


def wake_transcript(result):
    text = (result.get('text') or '').strip()
    normalized = text.casefold()
    if any(phrase in normalized for phrase in STT_HALLUCINATION_PHRASES):
        return ''
    segments = result.get('segments') or []
    if segments and all(
        segment.get('no_speech_prob', 0) > .82
        or segment.get('avg_logprob', 0) < -1.5
        or segment.get('compression_ratio', 0) > 2.8
        for segment in segments
    ):
        return ''
    return text
