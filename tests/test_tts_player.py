import unittest
from unittest.mock import patch

from server import tts


class SentencePlayerTests(unittest.TestCase):
    def tearDown(self):
        tts.register_activity_callback(None)

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

    def test_streaming_player_reports_speaker_activity(self):
        activity = []
        tts.register_activity_callback(activity.append)
        with patch.object(tts, "_synth_fish", return_value=b"audio"), \
                patch.object(tts, "_play_mp3_bytes", return_value=True):
            player = tts.SentencePlayer()
            player.push("Mình là Moon.")
            player.finish()
            self.assertTrue(player.wait(timeout=2))
        self.assertEqual(activity, [True, False])

    def test_regular_greeting_reports_speaker_activity(self):
        activity = []
        tts.register_activity_callback(activity.append)
        with patch.object(tts, "_speak_fish", return_value=True):
            tts.speak("Xin chào, mình là Moon.")
        self.assertEqual(activity, [True, False])


if __name__ == "__main__":
    unittest.main()
