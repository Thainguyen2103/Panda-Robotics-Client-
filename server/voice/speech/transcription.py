"""Groq Whisper request formatting without microphone/runtime state."""
import time


UNSET = object()


def transcribe_bytes(client, data: bytes, filename: str = "moon_clip.wav", *,
                     language=UNSET, prompt: str = None, model: str = None,
                     default_language=None, default_model="whisper-large-v3-turbo") -> str:
    if not client or not data:
        return ""
    started = time.time()
    try:
        kwargs = {
            "model": model or default_model,
            "file": (filename, data),
            "temperature": 0.0,
            "response_format": "text",
        }
        selected_language = default_language if language is UNSET else language
        if selected_language:
            kwargs["language"] = selected_language
        if prompt:
            kwargs["prompt"] = prompt
        text = client.audio.transcriptions.create(**kwargs)
        if hasattr(text, "text"):
            text = text.text
        text = (text or "").strip()
        if text:
            print(f"📝 [VOICE] STT ({time.time()-started:.2f}s): \"{text}\"")
        return text
    except Exception as exc:
        print(f"❌ [VOICE] Lỗi Groq STT: {exc}")
        return ""
