"""Audio segmentation and literal wake matching, without network or device imports."""
import collections
import math
import re
import struct
import unicodedata

RATE = 16000
FRAME_MS = 30
FRAME_BYTES = 960

_STT_HALLUCINATION_PHRASES = (
    "subscribe", "subtitles by", "amara.org", "thank you for watching",
    "thanks for watching", "like and subscribe", "see you next time",
    "đăng ký kênh", "không bỏ lỡ", "video hấp dẫn", "hẹn gặp lại",
    "ủng hộ kênh", "kênh ghiền",
)


def _correction_tokens(text):
    """Words used by the conservative ASR post-editing gate."""
    normalized = unicodedata.normalize("NFC", text or "")
    return re.findall(r"[\w%+.-]+", normalized, flags=re.UNICODE)


def safe_asr_correction(original, candidate):
    """Return a safe spelling repair, or the untouched STT transcript.

    The LLM is allowed to repair Vietnamese homophones and punctuation, but it
    may not add/remove numbers, identifiers or rewrite the sentence at length.
    This keeps the user's meaning in control even when the repair model guesses.
    """
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

    # Dates, quantities, model names and other identifiers must survive exactly.
    protected = {
        token.casefold() for token in source_words
        if any(char.isdigit() for char in token)
        or (len(token) >= 2 and token.isupper())
    }
    fixed_folded = {token.casefold() for token in fixed_words}
    if not protected.issubset(fixed_folded):
        return source

    # Moon is the robot's name, never a word for the repair model to reinterpret.
    if re.search(r"(?<!\w)moon(?!\w)", source, re.I) and not re.search(
            r"(?<!\w)moon(?!\w)", fixed, re.I):
        return source
    return fixed


def wake_tail(text):
    """Return original text after the complete token Moon; None means no wake.

    Do not strip Vietnamese accents: 'muốn', 'môn', 'món' are not Moon.
    """
    text = unicodedata.normalize("NFC", text)
    match = re.search(r"(?<!\w)moon(?!\w)", text, re.I)
    if match is None:
        return None
    tail = text[match.end():].lstrip(" ,.!?:;—-")
    return re.sub(r"^ơi\b[\s,.!?:;—-]*", "", tail, flags=re.I).strip()


def possible_moon_miss(text):
    """True only for short Vietnamese/ASCII spellings commonly produced for Moon.

    This is merely a gate for a second English STT verification. It never wakes
    by itself, and deliberately excludes real Vietnamese words muốn/môn/món.
    """
    normalized = unicodedata.normalize("NFC", text or "").lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return True
    return normalized in {
        "mun", "mun ơi", "hey mun",
        "mùn", "mùn ơi", "hey mùn",
        "muôn", "muôn ơi", "hey muôn",
        "muun", "muun ơi", "hey muun",
    }


def should_verify_wake(text, duration_ms, max_sec=3.0, max_words=3):
    """Request English confirmation for a short possible wake utterance.

    Confirmation still requires the complete token Moon. Common Vietnamese
    near-homophones are protected from the extra network request.
    """
    if possible_moon_miss(text):
        return True
    normalized = unicodedata.normalize("NFC",text or "").casefold()
    words = re.findall(r"\w+",normalized,flags=re.UNICODE)
    protected = {"muốn","môn","món"}
    return (0 < len(words) <= max_words and duration_ms <= max_sec*1000
            and not protected.intersection(words))


def confirmed_wake_tail(primary, verification):
    """Confirm Moon using the independent Vietnamese and English STT passes.

    A targeted English pass must agree with Moon-like evidence in the primary
    pass. Blank or unrelated audio never wakes from one pass guessing Moon.
    """
    # A loud non-verbal sound can make one Whisper pass hallucinate "Moon".
    # Require Moon-like evidence from BOTH language passes; a blank/unrelated
    # primary transcript can no longer be rescued by one English guess.
    primary_text = (primary or '').strip()
    verification_text = (verification or '').strip()
    if not verification_text:
        return None

    # A short Vietnamese pass can be blank even though the independent English
    # pass clearly hears the complete vocative "Hey Moon". Accept only an
    # explicit call in this fallback; a bare hallucinated "Moon" is not enough.
    if not primary_text:
        verify_token, verify_called = _english_wake_token(verification)
        return '' if verify_called and verify_token in _MOON_DIRECT_CALL_ALIASES else None

    primary_exact = wake_tail(primary)
    verification_exact = wake_tail(verification)
    primary_token, primary_called = _english_wake_token(primary)
    verify_token, verify_called = _english_wake_token(verification)

    primary_narrow = (primary_exact is not None
                      or (possible_moon_miss(primary) and bool(primary_text))
                      or primary_token in _MOON_NARROW_ALIASES)
    verify_narrow = (verification_exact is not None
                     or (possible_moon_miss(verification) and bool(verification_text))
                     or verify_token in _MOON_NARROW_ALIASES)
    primary_wide = primary_token in _MOON_EN_ALIASES
    verify_wide = verify_token in _MOON_EN_ALIASES

    if not ((primary_narrow and verify_narrow)
            or (primary_wide and verify_wide and (primary_called or verify_called))):
        return None
    if primary_exact is not None:
        return primary_exact
    if verification_exact is not None:
        return verification_exact
    return ''


def confident_wake_tail(text):
    """Return a wake tail that is safe to accept without a second API call.

    Literal Moon is accepted directly. Vietnamese STT renderings are accepted
    when the utterance is clearly a name call (bare, repeated, or with a vocative
    marker), while ordinary phrases such as "môn học" remain protected.
    """
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

    # Whisper tiếng Việt thường ghi tên Moon thành “Môn”. Nếu cả câu chỉ gồm
    # tên gọi và các hô ngữ ("Môn", "Môn ơi", "Môn, này Môn") thì đó là lời
    # đánh thức rõ ràng. Những cụm mang nghĩa thật như "môn học", "món ngon"
    # vẫn không lọt qua nhánh này.
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
        tail = original[end:].lstrip(" ,.!?:;—-")
        return tail.strip()

    if (len(folded) >= 2 and folded[0] in call_prefixes
            and folded[1] in _MOON_DIRECT_CALL_ALIASES
            and raw_words[1] != 'muốn'):
        return tail_after(1, skip_oi=True)
    if (len(folded) >= 2 and folded[0] in _MOON_DIRECT_CALL_ALIASES
            and folded[1] == 'oi' and raw_words[0] != 'muốn'):
        return tail_after(0, skip_oi=True)
    if (len(folded) == 1 and folded[0] in _MOON_NARROW_ALIASES
            and raw_words[0] != 'muốn'):
        return ''
    # Các cách ghi không mang nghĩa tiếng Việt như Mun/Muun có thể kèm luôn
    # câu hỏi. Riêng Môn/Món cần hô ngữ rõ ràng để tránh bật vì "môn học".
    if (folded and folded[0] in _MOON_DIRECT_CALL_ALIASES
            and raw_words[0] not in ambiguous_vietnamese | {'muốn'}):
        return tail_after(0, skip_oi=True)
    return None


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


_MOON_NARROW_ALIASES = {
    'moon', 'mun', 'muun', 'moun', 'moom', 'moone', 'mon', 'muon', 'mune',
}

_MOON_DIRECT_CALL_ALIASES = _MOON_NARROW_ALIASES | {'mua'}

_MOON_EN_ALIASES = _MOON_NARROW_ALIASES | {
    # Whisper forced to Vietnamese often writes the English sound Moon as
    # "múa" or "mưa"; accent folding turns both into "mua". This wide alias is
    # accepted only when one pass includes a call prefix and both STT passes
    # independently hear a Moon-like word.
    'mom', 'mum', 'moan', 'morn', 'move', 'man', 'noon', 'mua',
}


def wake_transcript(result):
    """Transcript a very short wake phrase without question-level filtering.

    Wake clips are often below one second, so Whisper may assign moderate
    no-speech/log-probability values even when the spelling is usable. The
    strict wake-intent matcher remains the safety gate after this function.
    """
    text = (result.get('text') or '').strip()
    normalized = text.casefold()
    if any(phrase in normalized for phrase in _STT_HALLUCINATION_PHRASES):
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


class Segmenter:
    """30ms PCM frames; short pre-roll, confirmed onset, bounded utterances.

    VAD is injected so timing/noise behavior can be tested without a microphone.
    Calibrate ambient noise before accepting speech, including noise misclassified
    by VAD. No peak-relative gate that cuts quiet syllables.
    """
    def __init__(self, vad, min_rms=0.003, max_sec=15, calibration_frames=0):
        self.vad = vad
        self.min_rms = min_rms
        self.max_frames = math.ceil(max_sec * 1000 / FRAME_MS)
        self.noise = min_rms / 3
        self.calibration_frames = calibration_frames
        self.calibration = []
        self.reset()

    @property
    def threshold(self):
        return max(self.min_rms, self.noise * 2.2)

    def reset(self):
        self.pre = collections.deque(maxlen=10)
        self.votes = collections.deque(maxlen=5)
        self.frames = []
        self.speech_count = 0
        self.silence = 0
        self.active = False

    def feed(self, pcm, silence_sec):
        if len(pcm) != FRAME_BYTES:
            raise ValueError("Expected 480 mono int16 samples at 16kHz")
        values = struct.unpack('<480h', pcm)
        rms = math.sqrt(sum(v*v for v in values) / 480) / 32768
        if self.calibration_frames:
            self.calibration.append(rms)
            self.calibration_frames -= 1
            if not self.calibration_frames:
                ordered = sorted(self.calibration)
                self.noise = ordered[int((len(ordered)-1) * .8)]
                self.calibration.clear()
            return None, rms, False
        voiced = self.vad.is_speech(pcm, RATE)
        speech = voiced and rms >= self.threshold
        if not voiced and not self.active:
            self.noise = .98 * self.noise + .02 * rms
        if not self.active:
            self.pre.append(pcm)
            self.votes.append(speech)
            if sum(self.votes) >= 3:
                self.active = True
                self.frames = list(self.pre)
                self.speech_count = sum(self.votes)
                self.silence = 0
            return None, rms, speech
        self.frames.append(pcm)
        self.speech_count += int(speech)
        self.silence = 0 if speech else self.silence + 1
        if self.silence * FRAME_MS >= silence_sec * 1000 or len(self.frames) >= self.max_frames:
            # Six voiced frames (180ms) admit a short name while rejecting clicks.
            result = b''.join(self.frames) if self.speech_count >= 6 else None
            self.reset()
            return result, rms, speech
        return None, rms, speech


def reliable_transcript(result):
    """Keep the raw STT text; confidence rejects noise, never rewrites words."""
    text = (result.get('text') or '').strip()
    normalized = text.casefold()
    if any(phrase in normalized for phrase in _STT_HALLUCINATION_PHRASES):
        return ''
    segments = result.get('segments') or []
    if segments and any(s.get('no_speech_prob', 0) > .45 or
                        s.get('avg_logprob', 0) < -1.0 or
                        s.get('compression_ratio', 0) > 2.4 for s in segments):
        return ''
    return text
