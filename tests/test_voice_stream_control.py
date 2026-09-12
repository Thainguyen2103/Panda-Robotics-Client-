import unittest

from server import voice


class FakeStream:
    def __init__(self):
        self.active = True
        self.stops = 0
        self.starts = 0

    def stop(self):
        self.active = False
        self.stops += 1

    def start(self):
        self.active = True
        self.starts += 1


class StreamControlTests(unittest.TestCase):
    def tearDown(self):
        voice._external_mic.clear()
        with voice._standby_stream_lock:
            voice._standby_stream = None
        voice.resume_listening()

    def test_pause_releases_standby_mic_and_resume_reopens_it(self):
        stream = FakeStream()
        with voice._standby_stream_lock:
            voice._standby_stream = stream

        voice.pause_listening()
        self.assertTrue(voice._paused_event.is_set())
        self.assertFalse(stream.active)
        self.assertEqual(stream.stops, 1)

        voice.resume_listening()
        self.assertFalse(voice._paused_event.is_set())
        self.assertTrue(stream.active)
        self.assertEqual(stream.starts, 1)

    def test_external_mic_temporarily_releases_local_standby_stream(self):
        stream = FakeStream()
        with voice._standby_stream_lock:
            voice._standby_stream = stream

        voice.set_external_mic(True)
        self.assertFalse(stream.active)

        voice.set_external_mic(False)
        self.assertTrue(stream.active)


if __name__ == "__main__":
    unittest.main()
