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

    Exact ``Moon`` always wins. A targeted English pass returning a Moon-like
    short result (for example ``Mun`` / ``Hey Mun``) also confirms a primary
    result that was blank or another narrowly allowed Moon miss.
    """
    exact = wake_tail(verification)
    if exact is not None:
        return exact
    if ((verification or '').strip()
            and possible_moon_miss(primary)
            and possible_moon_miss(verification)):
        return ''
    primary_token, primary_called = _english_wake_token(primary)
    verify_token, verify_called = _english_wake_token(verification)
    # Whisper often writes the proper name Moon as Mom/Mum/Moan/Move. Only
    # accept a small allowlist of wider English spellings when the user used a
    # calling prefix (Hey/Hi) and both independent passes remain Moon-like.
    if (not (primary or '').strip() and verify_token and verify_called
            and verify_token in _MOON_EN_ALIASES):
        return ''
    if (primary_token and verify_token and (primary_called or verify_called)
            and primary_token in _MOON_EN_ALIASES
            and verify_token in _MOON_EN_ALIASES):
        return ''
    return None


def _english_wake_token(text):
    normalized = unicodedata.normalize('NFC', text or '').casefold()
    if any(word in {'môn', 'món', 'muốn'} for word in re.findall(r'\w+', normalized)):
        return None, False
    ascii_text = ''.join(c for c in unicodedata.normalize('NFD', normalized)
                         if unicodedata.category(c) != 'Mn')
    words = re.findall(r'[a-z]+', ascii_text)
    called = bool(words and words[0] in {'hey', 'hi', 'hay'})
    if called:
        words = words[1:]
    if words and words[-1] == 'oi':
        words = words[:-1]
    return (words[0], called) if len(words) == 1 else (None, called)


_MOON_EN_ALIASES = {
    'moon', 'mun', 'muun', 'moun', 'moom', 'moone',
    'mom', 'mum', 'moan', 'morn', 'move', 'man', 'noon',
}


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
