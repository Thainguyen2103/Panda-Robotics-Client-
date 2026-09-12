import sys
import threading
import types
import unittest
from unittest.mock import patch

from server import wakeword


class FakeEngine:
    sample_rate = 16000
    frame_length = 4

    def process(self, pcm):
        return 0


class FakeInputStream:
    active = False

    def __init__(self, callback, **kwargs):
        self.callback = callback

    def __enter__(self):
        type(self).active = True
        self.callback(bytes(8), 4, None, None)
        return self

    def __exit__(self, *args):
        type(self).active = False


class WakewordStreamTests(unittest.TestCase):
    def test_stream_is_closed_before_wake_callback_claims_microphone(self):
        stopped = threading.Event()
        callback_stream_states = []
        fake_sd = types.SimpleNamespace(InputStream=FakeInputStream)
        fake_np = types.SimpleNamespace(int16=object(), frombuffer=lambda data, dtype: data)

        def on_wake():
            callback_stream_states.append(FakeInputStream.active)
            stopped.set()

        with patch.object(wakeword, "_porcupine", FakeEngine()), \
                patch.object(wakeword, "_init_tried", True), \
                patch.dict(sys.modules, {"sounddevice": fake_sd, "numpy": fake_np}):
            wakeword.run_loop(on_wake, stop_event=stopped)

        self.assertEqual(callback_stream_states, [False])


if __name__ == "__main__":
    unittest.main()
