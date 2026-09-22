"""Compatibility facade for pure voice processing helpers."""
from server.voice.audio.segmentation import FRAME_BYTES, FRAME_MS, RATE, Segmenter
from server.voice.speech.validation import reliable_transcript, safe_asr_correction
from server.voice.wake.matcher import (
    confirmed_wake_tail,
    confident_wake_tail,
    possible_moon_miss,
    should_verify_wake,
    wake_tail,
    wake_transcript,
)

__all__ = [
    "FRAME_BYTES", "FRAME_MS", "RATE", "Segmenter", "confirmed_wake_tail",
    "confident_wake_tail", "possible_moon_miss", "reliable_transcript",
    "safe_asr_correction", "should_verify_wake", "wake_tail", "wake_transcript",
]
