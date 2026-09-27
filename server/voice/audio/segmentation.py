"""Pure PCM segmentation with an injected VAD implementation."""
import collections
import math
import struct


RATE = 16000
FRAME_MS = 30
FRAME_BYTES = 960


class Segmenter:
    """30ms PCM frames with pre-roll, confirmed onset and bounded utterances."""
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
            result = b''.join(self.frames) if self.speech_count >= 6 else None
            self.reset()
            return result, rms, speech
        return None, rms, speech
