import math
import struct
import unittest

from server.voice_core import Segmenter, wake_tail, reliable_transcript


def frame(amplitude=1500):
    return struct.pack('<480h', *(int(amplitude * math.sin(i * .12)) for i in range(480)))


class EnergyVad:
    def is_speech(self, pcm, rate):
        return pcm != bytes(960)


class VoiceCoreTests(unittest.TestCase):
    def test_fan_misclassified_as_speech_is_calibrated_out(self):
        s = Segmenter(EnergyVad(), calibration_frames=60)
        fan = frame(1600)
        for _ in range(60):
            self.assertIsNone(s.feed(fan, .45)[0])
        for _ in range(100):
            clip, rms, speech = s.feed(fan, .45)
            self.assertIsNone(clip)
            self.assertFalse(speech)
        clips = [s.feed(pcm, .45)[0] for pcm in [frame(7000)] * 10 + [fan] * 15]
        self.assertEqual(sum(c is not None for c in clips), 1)

    def test_bad_segment_cannot_hide_behind_good_segment(self):
        result = {'text': 'Moon. Subscribe!', 'segments': [
            {'no_speech_prob': .01}, {'no_speech_prob': .9}]}
        self.assertEqual(reliable_transcript(result), '')

    def test_wake_boundaries_and_original_case(self):
        self.assertEqual(wake_tail('Hey MOON ơi, Hôm nay trời đẹp!'), 'Hôm nay trời đẹp!')
        self.assertEqual(wake_tail('Moon!'), '')
        for text in ['muốn ăn', 'môn học', 'món ngon', 'moonlight', 'honeymoon', 'Panda', 'Anna', 'Amanda']:
            self.assertIsNone(wake_tail(text), text)

    def test_silence_and_click_do_not_make_clip(self):
        s = Segmenter(EnergyVad())
        for pcm in [bytes(960)] * 50 + [frame()] + [bytes(960)] * 50:
            self.assertIsNone(s.feed(pcm, .45)[0])

    def test_preroll_and_quiet_syllables_survive_loud_onset(self):
        s = Segmenter(EnergyVad())
        frames = [bytes(960)] * 8 + [frame(12000)] * 6 + [frame(600)] * 10 + [bytes(960)] * 15
        clips = [clip for pcm in frames if (clip := s.feed(pcm, .45)[0])]
        self.assertEqual(len(clips), 1)
        self.assertIn(frame(600) * 10, clips[0])
        self.assertTrue(clips[0].startswith(bytes(960) * 7))

    def test_continuous_noise_is_bounded(self):
        s = Segmenter(EnergyVad(), max_sec=1)
        clips = [clip for _ in range(100) if (clip := s.feed(frame(), .45)[0])]
        self.assertTrue(clips)
        self.assertTrue(all(len(clip) <= 34 * 960 for clip in clips))

    def test_short_name_is_accepted(self):
        s = Segmenter(EnergyVad())
        results = [s.feed(pcm, .45)[0] for pcm in [frame()] * 7 + [bytes(960)] * 15]
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_invalid_frame_rejected(self):
        with self.assertRaises(ValueError):
            Segmenter(EnergyVad()).feed(b'123', .45)

    def test_confidence_instead_of_phrase_blacklist(self):
        self.assertEqual(reliable_transcript({'text': 'Cảm ơn các bạn', 'segments': [{'no_speech_prob': .01}]}), 'Cảm ơn các bạn')
        self.assertEqual(reliable_transcript({'text': 'Moon', 'segments': [{'no_speech_prob': .95}]}), '')
        self.assertEqual(reliable_transcript({'text': 'Moon', 'segments': [{'avg_logprob': -2}]}), '')


if __name__ == '__main__':
    unittest.main()
