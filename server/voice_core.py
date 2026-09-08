"""Audio segmentation and literal wake matching, without network or device imports."""
import collections
import math
import re
import struct
import unicodedata

RATE = 16000
FRAME_MS = 30
FRAME_BYTES = 960


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


class Segmenter:
    """30ms PCM frames; short pre-roll, confirmed onset, bounded utterances.

    VAD is injected so timing/noise behavior can be tested without a microphone.
    Noise estimation only uses non-speech frames and is capped to avoid deafening
    the detector in a noisy room. No peak-relative gate that cuts quiet syllables.
    """
    def __init__(self, vad, min_rms=0.003, max_sec=15):
        self.vad = vad
        self.min_rms = min_rms
        self.max_frames = math.ceil(max_sec * 1000 / FRAME_MS)
        self.noise = min_rms / 3
        self.reset()

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
        voiced = self.vad.is_speech(pcm, RATE)
        speech = voiced and rms >= max(self.min_rms, min(self.noise * 1.8, 0.012))
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
    segments = result.get('segments') or []
    if segments and all(s.get('no_speech_prob', 0) > .6 or
                        s.get('avg_logprob', 0) < -1.2 or
                        s.get('compression_ratio', 0) > 2.4 for s in segments):
        return ''
    return text
