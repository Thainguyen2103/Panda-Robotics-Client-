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
        await session.feed(bytes(960))
        self.assertFalse(session.listening)
        await session.feed(bytes(960))
        await session.feed(bytes(960))
        self.assertTrue(session.listening)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(sum(m['event'] == 'wake' for m in socket.messages), 1)
        self.assertTrue(session.clips.empty())

    async def run_clips(self, texts):
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
        for _ in texts:
            session.clips.put_nowait(b'audio')
        await asyncio.wait_for(session.clips.join(), 2)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        return session, socket.messages

    async def test_wake_and_following_clip_while_stt_pending(self):
        session, messages = await self.run_clips(['Moon ơi', 'Tôi muốn học tiếng Anh.'])
        self.assertEqual([m['text'] for m in messages if m['event'] == 'question'], ['Tôi muốn học tiếng Anh.'])
        self.assertEqual(sum(m['event'] == 'wake' for m in messages), 1)
        self.assertFalse(session.listening)

    async def test_same_utterance(self):
        _, messages = await self.run_clips(['Moon, Hôm nay Thứ Ba.'])
        self.assertEqual([m['text'] for m in messages if m['event'] == 'question'], ['Hôm nay Thứ Ba.'])

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
            for path in ['/', '/voice-test.js', '/voice-worklet.js']:
                response = await client.get(path)
                self.assertEqual(response.status, 200)
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
