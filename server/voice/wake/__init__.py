"""Wake-word matching and optional acoustic detection."""
from .matcher import (
    confirmed_wake_tail,
    confident_wake_tail,
    possible_moon_miss,
    should_verify_wake,
    wake_tail,
    wake_transcript,
)

__all__ = [
    "confirmed_wake_tail", "confident_wake_tail", "possible_moon_miss",
    "should_verify_wake", "wake_tail", "wake_transcript",
]
