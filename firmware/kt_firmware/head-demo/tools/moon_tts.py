"""Tao giong noi cho robot — 2 lua chon, viet lai bang Python tu code co san cua nhom:

  fish   : Fish Audio, model s2.1-pro-free  (giong web/fish-tts.js + config/settings.py)
           giong Viet = FISH_VOICE_ID, giong Nhat = FISH_VOICE_ID_JP (Reference ID tren fish.audio)
  gemini : giong cua Gemini (Kore), cung model Live voi dashboard (web/gemini-live-bridge.js,
           che do "native"). Dung chung key voi phan nghe (Gemini Transcribe).

Ca 2 deu tra ve mang int16 PCM 16kHz 1 kenh — dung dinh dang board ESP32 phat.
"""
import asyncio
import json
import os
import re
import urllib.request

import numpy as np

SAMPLE_RATE = 16000

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
GEMINI_LIVE_MODEL = os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.8-live")
GEMINI_VOICE = os.environ.get("GEMINI_LIVE_VOICE", "Kore")

_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def _resample(samples: np.ndarray, src_rate: int) -> np.ndarray:
    """Doi tan so lay mau ve 16kHz (noi suy tuyen tinh — du tot cho giong noi)."""
    if src_rate == SAMPLE_RATE or len(samples) == 0:
        return samples.astype(np.int16)
    n = int(len(samples) * SAMPLE_RATE / src_rate)
    x = np.linspace(0, len(samples) - 1, n)
    return np.interp(x, np.arange(len(samples)), samples).astype(np.int16)


# ------------------------------ Fish Audio ------------------------------

def fish_synth(text: str, api_key: str, settings) -> np.ndarray:
    """Goi API Fish Audio y nhu web/fish-tts.js: POST /v1/tts, header 'model', body JSON."""
    import miniaudio

    if not api_key or any(c.isspace() for c in api_key):
        # Khong dua key vao thong bao loi (tranh lo key ra man hinh/log).
        raise RuntimeError("FISH key sai dinh dang (dong 1 cua fish-key.txt chi chua key)")
    voice = settings.FISH_VOICE_ID
    if _JAPANESE.search(text) and getattr(settings, "FISH_VOICE_ID_JP", ""):
        voice = settings.FISH_VOICE_ID_JP  # cau co chu Nhat -> giong Nhat cho dung phat am
    voice = os.environ.get("FISH_VOICE_ID") or voice
    body = {
        "text": text[:4000],
        "reference_id": voice,
        "format": "mp3",
        "latency": "balanced",
        "normalize": True,
        "prosody": {"speed": 0.94},
    }
    req = urllib.request.Request(
        FISH_TTS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": getattr(settings, "FISH_TTS_MODEL", "s2.1-pro-free"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            mp3 = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"Fish Audio tu choi ({e.code}): {detail}") from None
    if not mp3:
        raise RuntimeError("Fish Audio tra ve am thanh rong")
    decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=SAMPLE_RATE)
    return np.frombuffer(decoded.samples, np.int16)


# ------------------------------ Gemini voice ------------------------------

async def _gemini_synth(text: str, api_key: str) -> np.ndarray:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=GEMINI_VOICE))),
        # Gemini Live la mo hinh hoi thoai -> phai dan ky "chi doc, khong tra loi".
        system_instruction=(
            "Ban la giong doc cua robot Moon. Doc NGUYEN VAN doan van ban nguoi dung gui, "
            "giong vui ve, ro rang cho tre em. Khong them, bot, dich hay tra loi gi khac."),
    )
    pcm = bytearray()
    rate = 24000  # Gemini Live tra PCM 16-bit 24kHz
    async with client.aio.live.connect(model=GEMINI_LIVE_MODEL, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)
        async for msg in session.receive():
            content = msg.server_content
            for part in (getattr(getattr(content, "model_turn", None), "parts", None) or []):
                blob = part.inline_data
                if blob and blob.data and str(blob.mime_type or "").startswith("audio/"):
                    pcm += blob.data
                    m = re.search(r"rate=(\d+)", blob.mime_type)
                    if m:
                        rate = int(m.group(1))
            if content and content.turn_complete:
                break
    if not pcm:
        raise RuntimeError("Gemini khong tra am thanh")
    return _resample(np.frombuffer(bytes(pcm), np.int16), rate)


def gemini_synth(text: str, api_key: str, timeout: float = 25.0) -> np.ndarray:
    return asyncio.run(asyncio.wait_for(_gemini_synth(text, api_key), timeout))
