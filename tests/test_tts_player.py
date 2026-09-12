import unittest
from unittest.mock import patch

from server import tts


class SentencePlayerTests(unittest.TestCase):
    def test_streaming_player_updates_echo_guard_when_playback_finishes(self):
        tts._speech_end_t = 0.0

        with patch.object(tts, "_synth_fish", return_value=b"audio"), \
                patch.object(tts, "_play_mp3_bytes", return_value=True):
            player = tts.SentencePlayer()
            player.push("Xin chào.")
            player.finish()
            self.assertTrue(player.wait(timeout=2))

        self.assertGreater(tts.speech_end_time(), 0.0)
        self.assertFalse(tts.is_speaking())


if __name__ == "__main__":
    unittest.main()
