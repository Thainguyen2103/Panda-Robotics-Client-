import sys
import types
import unittest
import importlib
from unittest.mock import patch

tts = importlib.import_module("server.voice.tts")


class EdgeTtsTests(unittest.TestCase):
    def test_japanese_prefers_configured_edge_voice(self):
        with patch.object(tts, "_synth_edge", return_value=b"edge") as edge:
            self.assertEqual(tts._synth_speech("こんにちは"), b"edge")
        edge.assert_called_once_with("こんにちは", "ja-JP-NanamiNeural")
        self.assertEqual(tts.EDGE_TTS_JA_VOICE, "ja-JP-NanamiNeural")

    def test_english_and_vietnamese_choose_neural_voices(self):
        self.assertEqual(tts._edge_voice_for_text("The cat is sleeping."), "en-US-AnaNeural")
        self.assertEqual(tts._edge_voice_for_text("The word こんにちは means hello."), "en-US-AnaNeural")
        self.assertEqual(tts._edge_voice_for_text("Chào bạn, mình là Moon."), "vi-VN-HoaiMyNeural")
        self.assertEqual(tts._edge_voice_for_text("こんにちは、ムーンです。"), "ja-JP-NanamiNeural")
        self.assertEqual(tts._edge_voice_for_text("猫"), "ja-JP-NanamiNeural")

    def test_edge_failure_does_not_call_fish_or_offline_tts(self):
        with patch.object(tts, "_synth_edge", return_value=None) as edge:
            self.assertIsNone(tts._synth_speech("猫です"))
        edge.assert_called_once_with("猫です", "ja-JP-NanamiNeural")

    def test_english_and_vietnamese_use_edge_voices(self):
        with patch.object(tts, "_synth_edge") as edge:
            edge.return_value = b"edge"
            self.assertEqual(tts._synth_speech("The cat is sleeping."), b"edge")
            self.assertEqual(tts._synth_speech("Chào bạn, mình là Moon."), b"edge")
        self.assertEqual(edge.call_args_list, [
            unittest.mock.call("The cat is sleeping.", "en-US-AnaNeural"),
            unittest.mock.call("Chào bạn, mình là Moon.", "vi-VN-HoaiMyNeural"),
        ])

    def test_async_stream_collects_audio_chunks(self):
        class FakeCommunicate:
            def __init__(self, text, voice):
                self.text = text
                self.voice = voice

            async def stream(self):
                yield {"type": "WordBoundary", "data": {}}
                yield {"type": "audio", "data": b"first"}
                yield {"type": "audio", "data": b"second"}

        fake_module = types.SimpleNamespace(Communicate=FakeCommunicate)
        with patch.dict(sys.modules, {"edge_tts": fake_module}):
            self.assertEqual(tts._synth_edge("こんにちは"), b"firstsecond")


if __name__ == "__main__":
    unittest.main()
