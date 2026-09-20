import unittest
import time
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

    def test_slow_fish_falls_back_without_sticking_player(self):
        activity = []
        fallback = []
        tts.register_activity_callback(activity.append)

        def slow_fish(_text):
            time.sleep(.2)
            return b"late"

        with patch.object(tts, "_synth_fish", side_effect=slow_fish), \
                patch.object(tts, "_speak_fallback") as speak_fallback:
            player = tts.SentencePlayer(
                on_fallback=lambda text, reason: fallback.append((text, reason)),
                synth_timeout=.02,
            )
            player.push("Moon nghe đây.")
            player.finish()
            self.assertTrue(player.wait(timeout=.5))

        speak_fallback.assert_called_once_with("Moon nghe đây.")
        self.assertRegex(fallback[0][1], r"quá .* giây")
        self.assertEqual(activity, [True, False])

    def test_stop_unblocks_playback_while_fish_sdk_is_hung(self):
        with patch.object(tts, "_synth_fish", side_effect=lambda _text: time.sleep(2)):
            player = tts.SentencePlayer(synth_timeout=5)
            player.push("Một câu đang treo.")
            time.sleep(.03)
            player.stop()
            self.assertTrue(player.wait(timeout=.3))


if __name__ == "__main__":
    unittest.main()
