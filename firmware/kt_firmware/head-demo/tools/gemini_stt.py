"""Doi giong noi thanh chu bang Gemini Transcribe — CUNG model va cau hinh voi dashboard
cua nhom (Panda-Robotics-Client-/web/gemini-transcribe-bridge.js), chi viet lai bang Python:
  - model gemini-3.5-transcribe-live
  - nghe 3 thu tieng: Viet, Anh, Nhat (tu nhan ra, khong can chon truoc)
  - tu vung rieng: Moon, Kanji, Hiragana... de khong bi nghe nham
  - VERBATIM: chep dung tung chu nguoi noi, khong tu sua cau

Dau vao: PCM 16-bit 16kHz 1 kenh (dung dinh dang ghi am cua server/voice/runtime/local.py).
Dau ra: cau noi (chu) hoac chuoi rong neu khong nghe ra gi.
"""
import asyncio
import os

MODEL = os.environ.get("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe-live")
LANGUAGES = ["vi-VN", "en-US", "ja-JP"]
# + lenh di chuyen phan than (de Gemini khong nghe nham, vd "run" thanh "răn"/"rừng")
VOCABULARY = ["Moon", "ムーン", "Kanji", "Hiragana", "Katakana", "Romaji",
              "run", "stop", "left", "right", "trái", "phải", "thẳng"]
SAMPLE_RATE = 16000
CHUNK = SAMPLE_RATE * 2 // 10  # 100ms am thanh moi goi
STABLE_SEC = 1.5  # ban chep tam khong doi them 1,5 giay (sau khi gui het) -> coi la xong cau


def _config(types):
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=LANGUAGES,
            custom_vocabulary=VOCABULARY,
            mode=types.AudioTranscriptionConfigMode.VERBATIM,
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                prefix_padding_ms=300,
                silence_duration_ms=700,
            )
        ),
    )


async def _transcribe(pcm: bytes, api_key: str, timeout: float) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    async with client.aio.live.connect(model=MODEL, config=_config(types)) as session:
        async def send():
            # Gui ca doan da ghi + 1 giay im lang o cuoi: bo phat hien giong noi (VAD) cua
            # Gemini can thay khoang lang 0,7 giay moi chot "nguoi noi da noi xong".
            data = pcm + bytes(SAMPLE_RATE * 2)
            for i in range(0, len(data), CHUNK):
                await session.send_realtime_input(
                    audio=types.Blob(data=data[i : i + CHUNK], mime_type=f"audio/pcm;rate={SAMPLE_RATE}")
                )
                await asyncio.sleep(0.01)
            await session.send_realtime_input(audio_stream_end=True)

        # Gemini tra ve 2 loai ban chep:
        #   - interim_input_transcription: ban tam, toi gan nhu ngay (~1 giay), sua dan tung chu
        #   - input_transcription: ban CUOI, chi toi khi VAD phia Gemini chot "da noi xong".
        # Do that 19/11: ban tam da dung tu giay 1,5 nhung ban cuoi co lan toi giay 7,6, co lan
        # khong toi trong 15 giay -> code cu chi doi ban cuoi nen tra ve "" du nghe ro.
        # Gio: co ban cuoi thi lay ngay; khong thi ban tam dung yen STABLE_SEC (da gui xong am
        # thanh) la coi nhu xong cau va lay ban tam.
        best = {"final": "", "interim": "", "changed": 0.0}
        loop = asyncio.get_running_loop()

        async def receive():
            while True:
                async for msg in session.receive():
                    content = msg.server_content
                    final = getattr(getattr(content, "input_transcription", None), "text", None)
                    interim = getattr(getattr(content, "interim_input_transcription", None), "text", None)
                    if final and final.strip():
                        best["final"] = final.strip()
                    if interim and interim.strip() and interim.strip() != best["interim"]:
                        best["interim"] = interim.strip()
                        best["changed"] = loop.time()

        sender = asyncio.create_task(send())
        receiver = asyncio.create_task(receive())
        deadline = loop.time() + timeout
        try:
            while loop.time() < deadline:
                if best["final"]:
                    return best["final"]
                if (best["interim"] and sender.done()
                        and loop.time() - best["changed"] > STABLE_SEC):
                    print(f"[stt] Gemini chua chot ban cuoi, dung ban tam: {best['interim']!r}")
                    return best["interim"]
                if receiver.done():  # mat ket noi / loi tu Gemini -> dung ban tam neu co
                    receiver.result()  # nem loi ra ngoai neu receive() bi loi
                    break
                await asyncio.sleep(0.1)
            return best["final"] or best["interim"]
        finally:
            sender.cancel()
            receiver.cancel()


def transcribe(pcm: bytes, api_key: str, timeout: float = 15.0) -> str:
    if not pcm:
        return ""
    return asyncio.run(_transcribe(pcm, api_key, timeout))
