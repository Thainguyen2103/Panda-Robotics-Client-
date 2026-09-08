"""Run: python -m server.voice_lab. No Brain, MQTT, LLM or TTS imports."""
import asyncio
import contextlib
import io
import struct
import time
import wave
from pathlib import Path

from aiohttp import web, WSMsgType
from groq import AsyncGroq
import webrtcvad

from config import settings
from server.voice_core import Segmenter, wake_tail, reliable_transcript, RATE, FRAME_BYTES


def acoustic_engine():
    key = settings.PICOVOICE_ACCESS_KEY
    ppn = settings.MOON_PPN_PATH or str(Path(__file__).with_name('moon.ppn'))
    if not key or not Path(ppn).is_file():
        return None, 'Whisper: wake sau khi ngắt câu + thời gian mạng. Chưa có key/model Moon .ppn.'
    import pvporcupine
    engine = pvporcupine.create(access_key=key, keyword_paths=[ppn],
                               sensitivities=[settings.WAKE_SENSITIVITY])
    if engine.sample_rate != RATE:
        engine.delete()
        raise ValueError('Moon model must accept 16kHz audio')
    return engine, 'Porcupine: wake âm học trực tiếp trên máy'


class Session:
    def __init__(self, ws, client, engine=None):
        self.ws, self.client, self.engine = ws, client, engine
        self.segmenter = Segmenter(webrtcvad.Vad(settings.VOICE_VAD_MODE),
                                   settings.VOICE_MIN_RMS, settings.VOICE_MAX_SEC,
                                   calibration_frames=60)
        self.clips = asyncio.Queue(maxsize=3)
        self.acoustic_buffer = bytearray()
        self.listening = False
        self.deadline = 0
        self.sequence = 0
        self.last_meter = 0
        self.busy = False

    async def emit(self, event, **data):
        await self.ws.send_json(dict(event=event, **data))

    async def wake(self):
        self.listening = True
        self.deadline = time.monotonic() + settings.VOICE_WAIT_SEC
        await self.emit('wake', engine='porcupine' if self.engine else 'whisper')

    async def feed(self, pcm):
        if len(pcm) != FRAME_BYTES:
            raise ValueError('Audio frame must be 30ms PCM16 mono / 16kHz')
        calibrating = self.segmenter.calibration_frames > 0
        if self.engine and not calibrating:
            self.acoustic_buffer.extend(pcm)
            size = self.engine.frame_length * 2
            while len(self.acoustic_buffer) >= size:
                frame = bytes(self.acoustic_buffer[:size])
                del self.acoustic_buffer[:size]
                detected = self.engine.process(struct.unpack(f'<{size//2}h', frame)) >= 0
                if detected and not self.listening and not self.busy and self.clips.empty():
                    self.segmenter.reset()
                    await self.wake()
        silence = (settings.VOICE_QUESTION_SILENCE_SEC if self.listening
                   else settings.VOICE_WAKE_SILENCE_SEC)
        clip, rms, speech = self.segmenter.feed(pcm, silence)
        if calibrating and not self.segmenter.calibration_frames:
            await self.emit('calibrated', noise=round(self.segmenter.noise, 4),
                            threshold=round(self.segmenter.threshold, 4))
        now = time.monotonic()
        if self.listening and self.segmenter.active:
            self.deadline = now + settings.VOICE_WAIT_SEC
        if now - self.last_meter > .1:
            self.last_meter = now
            await self.emit('meter', rms=round(rms, 4), speech=speech,
                            threshold=round(self.segmenter.threshold, 4))
        if clip and (not self.engine or self.listening):
            if self.clips.full():
                await self.emit('error', text='STT không theo kịp. Hãy dừng và bật mic lại để tránh kết quả cũ.')
                await self.ws.close(code=1013)
                return
            self.clips.put_nowait(clip)

    async def transcribe(self, pcm):
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes(pcm)
        result = await self.client.audio.transcriptions.create(
            file=('moon.wav', wav.getvalue()), model=settings.STT_MODEL,
            language=settings.STT_LANGUAGE or None, temperature=0,
            response_format='verbose_json')
        return reliable_transcript(result.model_dump())

    async def worker(self):
        while True:
            clip = await self.clips.get()
            self.busy = True
            start = time.monotonic()
            try:
                await self.emit('processing')
                text = await self.transcribe(clip)
                self.sequence += 1
                # Unrelated standby ASR is diagnostic, not a user's question.
                accepted = self.listening or wake_tail(text) is not None
                await self.emit('transcript' if accepted else 'ignored', text=text, sequence=self.sequence,
                                latency_ms=round((time.monotonic()-start)*1000),
                                duration_ms=round(len(clip)/32))
                if not text:
                    await self.emit('rejected', text='Không có lời nói đủ tin cậy trong đoạn âm thanh.')
                elif self.listening:
                    await self.emit('question', text=text)
                    self.listening = False
                elif not self.engine:
                    tail = wake_tail(text)
                    if tail is not None:
                        await self.wake()
                        if tail:
                            await self.emit('question', text=tail)
                            self.listening = False
            except Exception as exc:
                # Do not expose SDK response bodies or credentials to the browser.
                await self.emit('error', text=f'STT lỗi ({type(exc).__name__}). Kiểm tra key, mạng hoặc quota; thử lại.')
                self.listening = False
            finally:
                self.busy = False
                self.clips.task_done()
                await self.emit('state', state='listening' if self.listening else 'standby')

    async def watchdog(self):
        while True:
            await asyncio.sleep(.25)
            if self.listening and not self.busy and self.clips.empty() and time.monotonic() > self.deadline:
                self.listening = False
                self.segmenter.reset()
                await self.emit('timeout', text='Chưa nghe được câu nói. Hãy gọi Moon lại.')


async def socket_handler(request):
    # Browser microphone audio and API quota are only accessible from this origin.
    if request.headers.get('Origin') != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse(max_msg_size=4096, heartbeat=20)
    await ws.prepare(request)
    if not settings.GROQ_API_KEY:
        await ws.send_json(dict(event='error', text='Thiếu GROQ_API_KEY trong config/secrets.py hoặc môi trường.'))
        await ws.close()
        return ws
    engine = None
    tasks = []
    try:
        engine, description = acoustic_engine()
        async with AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=15, max_retries=0) as client:
            session = Session(ws, client, engine)
            await session.emit('ready', engine=description, calibrating=True)
            tasks = [asyncio.create_task(session.worker()), asyncio.create_task(session.watchdog())]
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    await session.feed(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
    except Exception as exc:
        if not ws.closed:
            await ws.send_json(dict(event='error', text=f'Voice lỗi ({type(exc).__name__}). Kiểm tra cấu hình model/mic.'))
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                await task
        if engine:
            engine.delete()
        await ws.close()
    return ws


def make_app():
    app = web.Application()
    app.router.add_get('/ws', socket_handler)
    async def dashboard(request):
        raise web.HTTPFound('http://localhost:3000/')
    app.router.add_get('/', dashboard)
    return app


if __name__ == '__main__':
    web.run_app(make_app(), host='127.0.0.1', port=8765)
