"""Run: python -m server.voice_lab. No Brain, MQTT, LLM or TTS imports."""
import asyncio
import contextlib
import io
import json
import struct
import time
import wave
from pathlib import Path

from aiohttp import web, WSMsgType
from groq import AsyncGroq
import webrtcvad

from config import settings
from server.voice_core import (Segmenter, wake_tail, should_verify_wake,
                               confirmed_wake_tail, reliable_transcript,
                               RATE, FRAME_BYTES, FRAME_MS)


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
        self.paused = False
        self.audio_epoch = 0
        self.standby_rejects = 0
        # Porcupine bắt keyword khi từ "Moon" chưa kết thúc hẳn. Không cho
        # phần đuôi keyword rơi vào clip câu hỏi.
        self.waiting_for_wake_quiet = False
        self.wake_quiet_frames = 0

    async def emit(self, event, **data):
        await self.ws.send_json(dict(event=event, **data))

    async def wake(self):
        self.listening = True
        self.deadline = time.monotonic() + settings.VOICE_WAIT_SEC
        await self.emit('wake', engine='porcupine' if self.engine else 'whisper')

    def pause(self):
        """Invalidate buffered/in-flight audio when Moon's own speaker starts."""
        self.paused = True
        self.audio_epoch += 1
        self.listening = False
        self.waiting_for_wake_quiet = False
        self.wake_quiet_frames = 0
        self.segmenter.reset()
        while True:
            try:
                self.clips.get_nowait()
                self.clips.task_done()
            except asyncio.QueueEmpty:
                break

    async def resume(self):
        self.paused = False
        self.segmenter.reset()
        await self.emit('resumed')

    def discard_pending_clips(self):
        """Drop audio captured before a newly confirmed wake can be armed."""
        while True:
            try:
                self.clips.get_nowait()
                self.clips.task_done()
            except asyncio.QueueEmpty:
                break

    def gate_question_after_wake(self):
        # Cloud wake verification takes time. Audio queued during that wait may
        # be TV/music/background and must never become the new question.
        self.discard_pending_clips()
        self.segmenter.reset()
        self.waiting_for_wake_quiet = True
        self.wake_quiet_frames = 0
        self.deadline = time.monotonic() + settings.VOICE_WAIT_SEC

    async def feed(self, pcm):
        if len(pcm) != FRAME_BYTES:
            raise ValueError('Audio frame must be 30ms PCM16 mono / 16kHz')
        if self.paused:
            return
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
                    self.waiting_for_wake_quiet = True
                    self.wake_quiet_frames = 0
                    await self.wake()

        if self.waiting_for_wake_quiet:
            values = struct.unpack('<480h', pcm)
            rms = (sum(v*v for v in values) / 480) ** .5 / 32768
            voiced = self.segmenter.vad.is_speech(pcm, RATE)
            speech = voiced and rms >= self.segmenter.threshold
            self.wake_quiet_frames = 0 if speech else self.wake_quiet_frames + 1
            # 120 ms im lặng xác nhận keyword đã kết thúc. Sau mốc này
            # người dùng có trọn VOICE_WAIT_SEC để bắt đầu câu hỏi.
            if self.wake_quiet_frames >= 4:
                self.waiting_for_wake_quiet = False
                self.wake_quiet_frames = 0
                self.segmenter.reset()
                self.deadline = time.monotonic() + settings.VOICE_WAIT_SEC
                await self.emit('armed')
            now = time.monotonic()
            if now - self.last_meter > .1:
                self.last_meter = now
                await self.emit('meter', rms=round(rms, 4), speech=speech,
                                threshold=round(self.segmenter.threshold, 4))
            return
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
            # Ghi lại state TẠI THỜI ĐIỂM THU. Worker có thể xử lý muộn
            # sau khi wake đã bật; nếu chỉ nhìn self.listening lúc đó, clip
            # nhiễu cũ sẽ bị nhận nhầm thành câu hỏi.
            self.clips.put_nowait((clip, self.listening, self.audio_epoch))

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

    async def verify_wake(self, pcm):
        """English pass only for a likely missed Moon; never used for questions."""
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes(pcm)
        result = await self.client.audio.transcriptions.create(
            file=('moon-wake.wav', wav.getvalue()), model=settings.STT_MODEL,
            language='en', temperature=0, response_format='verbose_json')
        return reliable_transcript(result.model_dump())

    async def worker(self):
        while True:
            clip, captured_while_listening, audio_epoch = await self.clips.get()
            self.busy = True
            publish_state = True
            start = time.monotonic()
            try:
                if self.paused or audio_epoch != self.audio_epoch:
                    publish_state = False
                    continue
                # State is captured with the clip. Never reinterpret an older
                # standby/background clip as a question merely because a prior
                # network request has since recognized Moon.
                question_context = captured_while_listening
                await self.emit('processing',phase='question' if question_context else 'wake')
                text = await self.transcribe(clip)
                if self.paused or audio_epoch != self.audio_epoch:
                    publish_state = False
                    continue
                # Whisper vi often writes the English name as Mun/Mùn/Muôn or
                # returns blank. Verify only those narrow cases with an English
                # pass; common Vietnamese words muốn/môn/món never enter here.
                if (not self.engine and not captured_while_listening
                        and not question_context
                        and should_verify_wake(text,len(clip)/32,
                            settings.VOICE_WAKE_VERIFY_MAX_SEC,
                            settings.VOICE_WAKE_VERIFY_MAX_WORDS)):
                    await self.emit('verifying_wake', text=text)
                    verified = await self.verify_wake(clip)
                    confirmed_tail = confirmed_wake_tail(text, verified)
                    if confirmed_tail is not None:
                        text = 'Moon' + (f', {confirmed_tail}' if confirmed_tail else '')
                    else:
                        # Even a literal Moon from one pass is not enough: loud
                        # noise occasionally produces a confident single-pass
                        # hallucination. Keep OLED in standby and ignore it.
                        text = ''
                if self.paused or audio_epoch != self.audio_epoch:
                    publish_state = False
                    continue
                self.sequence += 1
                # Unrelated standby ASR is diagnostic, not a user's question.
                tail = wake_tail(text) if not self.engine else None
                question_clip = captured_while_listening or question_context
                accepted = ((question_clip and self.listening)
                            or (tail is not None and not self.listening))
                await self.emit('transcript' if accepted else 'ignored', text=text, sequence=self.sequence,
                                latency_ms=round((time.monotonic()-start)*1000),
                                duration_ms=round(len(clip)/32))
                if not text and question_clip and self.listening:
                    await self.emit('rejected', text='Chưa nghe rõ câu hỏi — Moon vẫn đang nghe.')
                elif not text:
                    # Nhiễu nền bị VAD xem là giọng có thể tạo clip rỗng liên
                    # tục. Không spam UI; sau ba lần thì tự đo nền lại.
                    self.standby_rejects += 1
                    if self.standby_rejects >= 3:
                        self.standby_rejects = 0
                        self.segmenter.reset()
                        self.segmenter.calibration = []
                        self.segmenter.calibration_frames = round(1200 / FRAME_MS)
                        await self.emit('recalibrating')
                elif question_clip and self.listening:
                    self.standby_rejects = 0
                    await self.emit('question', text=tail if tail else text)
                    self.listening = False
                elif tail is not None and not self.listening:
                    self.standby_rejects = 0
                    await self.wake()
                    if tail:
                        await self.emit('question', text=tail)
                        self.listening = False
                    else:
                        self.gate_question_after_wake()
                else:
                    self.standby_rejects = 0
            except Exception as exc:
                # Do not expose SDK response bodies or credentials to the browser.
                await self.emit('error', text=f'STT lỗi ({type(exc).__name__}). Kiểm tra key, mạng hoặc quota; thử lại.')
                self.listening = False
            finally:
                self.busy = False
                self.clips.task_done()
                if publish_state and not self.paused and audio_epoch == self.audio_epoch:
                    await self.emit('state', state='listening' if self.listening else 'standby')

    async def watchdog(self):
        while True:
            await asyncio.sleep(.25)
            if self.listening and not self.busy and self.clips.empty() and time.monotonic() > self.deadline:
                self.listening = False
                self.waiting_for_wake_quiet = False
                self.wake_quiet_frames = 0
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
                elif msg.type == WSMsgType.TEXT:
                    try:
                        command = json.loads(msg.data).get('command')
                    except Exception:
                        command = None
                    if command == 'pause':
                        session.pause()
                    elif command == 'resume':
                        await session.resume()
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
