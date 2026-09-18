"""
server/voice — Voice AI Package
=================================
Export API công khai cho các module khác sử dụng.
"""

from .brain import start, stop, get_state, VoiceState, _handle_wake_word
from .tts   import speak, is_speaking, stop_speaking, speech_end_time, SentencePlayer
from .stt   import transcribe_bytes, transcribe_pcm, is_hallucination, contains_wake_word
from .vad   import record_until_silence, select_input_device, wrap_wav

__all__ = [
    # Brain
    "start", "stop", "get_state", "VoiceState",
    # TTS
    "speak", "is_speaking", "stop_speaking", "speech_end_time", "SentencePlayer",
    # STT
    "transcribe_bytes", "transcribe_pcm", "is_hallucination", "contains_wake_word",
    # VAD
    "record_until_silence", "select_input_device", "wrap_wav",
]
