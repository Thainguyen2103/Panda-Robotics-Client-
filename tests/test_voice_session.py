import asyncio
import contextlib
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from server.voice_lab import Session, make_app


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_acoustic_wake_before_stt_and_frame_reblocking(self):
        class Engine:
            frame_length = 512
            calls = 0
            def process(self, pcm):
                self.calls += 1
                assert len(pcm) == 512
                return 0
        engine = Engine()
        socket = Socket()
        session = Session(socket, None, engine)
        session.segmenter.calibration_frames = 0
        await session.feed(bytes(960))
        self.assertFalse(session.listening)
        await session.feed(bytes(960))
        await session.feed(bytes(960))
        self.assertTrue(session.listening)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(sum(m['event'] == 'wake' for m in socket.messages), 1)
        self.assertTrue(session.clips.empty())

    async def test_acoustic_wake_tail_is_not_mistaken_for_question(self):
        class Engine:
            frame_length = 480
            calls = 0

            def process(self, pcm):
                self.calls += 1
                return 0 if self.calls == 1 else -1

        class Vad:
            def is_speech(self, pcm, rate):
                return pcm != bytes(960)

        socket = Socket()
        session = Session(socket, None, Engine())
        session.segmenter.calibration_frames = 0
        session.segmenter.vad = Vad()
        speech = b'\x88\x13' * 480  # int16 5000, trên ngưỡng RMS

        # Phần còn lại của chính wakeword không được tạo clip câu hỏi.
        for pcm in [speech] * 5 + [bytes(960)] * 4:
            await session.feed(pcm)

        self.assertTrue(session.listening)
        self.assertFalse(session.waiting_for_wake_quiet)
        self.assertTrue(session.clips.empty())
        self.assertEqual(sum(m['event'] == 'wake' for m in socket.messages), 1)
        self.assertEqual(sum(m['event'] == 'armed' for m in socket.messages), 1)

    async def test_paused_session_ignores_tts_audio_until_resumed(self):
        session=Session(Socket(),None)
        session.segmenter.calibration_frames=0
        session.segmenter.vad=type('Vad',(),{'is_speech':lambda self,pcm,rate: pcm != bytes(960)})()
        session.paused=True
        for _ in range(20):
            await session.feed(b'\x88\x13'*480)
        self.assertTrue(session.clips.empty())
        self.assertFalse(session.segmenter.active)
        session.paused=False
        for pcm in [b'\x88\x13'*480]*8+[bytes(960)]*45:
            await session.feed(pcm)
        self.assertFalse(session.clips.empty())

    async def test_tts_pause_invalidates_transcript_already_in_flight(self):
        socket = Socket()
        session = Session(socket, None)
        started = asyncio.Event()
        release = asyncio.Event()

        async def transcribe(clip):
            started.set()
            await release.wait()
            return 'Hey Moon'

        session.transcribe = transcribe
        worker = asyncio.create_task(session.worker())
        session.clips.put_nowait((b'audio', False, session.audio_epoch))
        await asyncio.wait_for(started.wait(), 1)
        session.pause()
        release.set()
        await asyncio.wait_for(session.clips.join(), 1)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        self.assertFalse(any(m['event'] == 'wake' for m in socket.messages))
        self.assertFalse(session.listening)

    async def run_clips(self, texts, captured_states=None):
        socket = Socket()
        session = Session(socket, None)
        iterator = iter(texts)
        async def transcribe(clip):
            await asyncio.sleep(.01)  # Audio continues to queue while STT is busy.
            result = next(iterator)
            if isinstance(result, Exception):
                raise result
            return result
        session.transcribe = transcribe
        worker = asyncio.create_task(session.worker())
        states = captured_states or [False] * len(texts)
        for captured_while_listening in states:
            session.clips.put_nowait((b'audio', captured_while_listening, session.audio_epoch))
        await asyncio.wait_for(session.clips.join(), 2)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        return session, socket.messages

    async def test_question_spoken_while_wake_stt_is_pending_is_preserved(self):
        session, messages = await self.run_clips(['Moon ơi', 'Tôi muốn học tiếng Anh.'])
        self.assertEqual([m['text'] for m in messages if m['event'] == 'question'],
                         ['Tôi muốn học tiếng Anh.'])
        self.assertEqual(sum(m['event'] == 'wake' for m in messages), 1)
        self.assertFalse(session.listening)
        phases=[m.get('phase') for m in messages if m['event']=='processing']
        self.assertEqual(phases,['wake','question'])

    async def test_clip_captured_after_wake_is_the_question(self):
        session, messages = await self.run_clips(
            ['Moon ơi', 'Tôi muốn học tiếng Anh.'],
            captured_states=[False, True],
        )
        self.assertEqual(
            [m['text'] for m in messages if m['event'] == 'question'],
            ['Tôi muốn học tiếng Anh.'],
        )
        self.assertFalse(session.listening)

    async def test_same_utterance(self):
        _, messages = await self.run_clips(['Moon, Hôm nay Thứ Ba.'])
        self.assertEqual([m['text'] for m in messages if m['event'] == 'question'], ['Hôm nay Thứ Ba.'])

    async def test_likely_vietnamese_miss_requires_english_confirmation(self):
        socket = Socket()
        session = Session(socket, None)
        session.transcribe = lambda clip: asyncio.sleep(0, result='Mun')
        session.verify_wake = lambda clip: asyncio.sleep(0, result='Moon')
        worker = asyncio.create_task(session.worker())
        session.clips.put_nowait((b'audio', False, session.audio_epoch))
        await asyncio.wait_for(session.clips.join(), 2)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        self.assertTrue(session.listening)
        self.assertTrue(any(m['event'] == 'verifying_wake' for m in socket.messages))
        self.assertEqual(sum(m['event'] == 'wake' for m in socket.messages), 1)

    async def test_blank_primary_can_be_recovered_by_english_wake_pass(self):
        socket = Socket()
        session = Session(socket, None)
        session.transcribe = lambda clip: asyncio.sleep(0, result='')
        session.verify_wake = lambda clip: asyncio.sleep(0, result='Hey Moon')
        worker = asyncio.create_task(session.worker())
        session.clips.put_nowait((b'audio', False, session.audio_epoch))
        await asyncio.wait_for(session.clips.join(), 2)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        self.assertTrue(session.listening)
        self.assertEqual(sum(m['event'] == 'wake' for m in socket.messages), 1)

    async def test_repeated_blank_standby_noise_recalibrates_without_log_spam(self):
        socket = Socket()
        session = Session(socket, None)
        session.transcribe = lambda clip: asyncio.sleep(0, result='')
        session.verify_wake = lambda clip: asyncio.sleep(0, result='')
        worker = asyncio.create_task(session.worker())
        for _ in range(3):
            session.clips.put_nowait((b'audio', False, session.audio_epoch))
        await asyncio.wait_for(session.clips.join(), 2)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        self.assertFalse(any(m['event'] == 'rejected' for m in socket.messages))
        self.assertEqual(sum(m['event'] == 'recalibrating' for m in socket.messages), 1)
        self.assertEqual(session.segmenter.calibration_frames, 40)

    async def test_real_vietnamese_words_do_not_enter_wake_verification(self):
        socket = Socket()
        session = Session(socket, None)
        session.transcribe = lambda clip: asyncio.sleep(0, result='môn')
        verification_calls = []

        async def verify(clip):
            verification_calls.append(clip)
            return 'Moon'

        session.verify_wake = verify
        worker = asyncio.create_task(session.worker())
        session.clips.put_nowait((b'audio', False, session.audio_epoch))
        await asyncio.wait_for(session.clips.join(), 2)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        self.assertFalse(verification_calls)
        self.assertFalse(session.listening)

    async def test_no_wake_no_question(self):
        _, messages = await self.run_clips(['Tôi muốn ăn món ngon.'])
        self.assertFalse(any(m['event'] in ('wake', 'question') for m in messages))

    async def test_api_failure_recovers_without_exposing_exception(self):
        _, messages = await self.run_clips([RuntimeError('secret-value'), 'Moon, Xin chào'])
        self.assertNotIn('secret-value', str(messages))
        self.assertTrue(any(m['event'] == 'question' for m in messages))

    async def test_timeout(self):
        session = Session(Socket(), None)
        await session.wake()
        session.deadline = 0
        task = asyncio.create_task(session.watchdog())
        await asyncio.sleep(.3)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.assertFalse(session.listening)
        self.assertEqual(session.ws.messages[-1]['event'], 'timeout')

    async def test_http_assets_origin_and_missing_key(self):
        async with TestClient(TestServer(make_app())) as client:
            response = await client.get('/', allow_redirects=False)
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers['Location'], 'http://localhost:3000/')
            response = await client.get('/ws', headers={'Origin': 'https://unrelated.example'})
            self.assertEqual(response.status, 403)
            with patch('server.voice_lab.settings.GROQ_API_KEY', ''):
                origin = str(client.make_url('/')).rstrip('/')
                ws = await client.ws_connect('/ws', headers={'Origin': origin})
                message = await ws.receive_json()
                self.assertEqual(message['event'], 'error')
                await ws.close()


if __name__ == '__main__':
    unittest.main()
