"""Small binary-safe CLI used by the Node WebSocket bridge for Edge TTS."""

import asyncio
import json
import sys


VOICES = {
    "ja-JP-NanamiNeural",
    "en-US-AnaNeural",
    "vi-VN-HoaiMyNeural",
}


async def synthesize(text: str, voice: str) -> bytes:
    import edge_tts

    communicator = edge_tts.Communicate(text, voice)
    audio = bytearray()
    async for event in communicator.stream():
        if event.get("type") == "audio":
            audio.extend(event.get("data", b""))
    if not audio:
        raise RuntimeError("empty audio response")
    return bytes(audio)


def main() -> int:
    try:
        request = json.load(sys.stdin)
        text = request.get("text")
        voice = request.get("voice")
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ValueError("invalid text")
        if voice not in VOICES:
            raise ValueError("unsupported voice")
        sys.stdout.buffer.write(asyncio.run(synthesize(text, voice)))
        sys.stdout.buffer.flush()
        return 0
    except Exception as exc:
        # Keep stdout binary-only and never echo the spoken text or credentials.
        sys.stderr.write(type(exc).__name__)
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
