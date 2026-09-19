import math
import struct
import unittest

from server.voice_core import (Segmenter, wake_tail, possible_moon_miss,
                               should_verify_wake, confirmed_wake_tail,
                               confident_wake_tail, reliable_transcript, wake_transcript,
                               safe_asr_correction)


def frame(amplitude=1500):
    return struct.pack('<480h', *(int(amplitude * math.sin(i * .12)) for i in range(480)))


class EnergyVad:
    def is_speech(self, pcm, rate):
        return pcm != bytes(960)


class VoiceCoreTests(unittest.TestCase):
    def test_safe_asr_correction_accepts_spelling_repair(self):
        self.assertEqual(
            safe_asr_correction('bây giờ là mẹ giờ', 'Bây giờ là mấy giờ?'),
            'Bây giờ là mấy giờ?')

    def test_safe_asr_correction_rejects_rewrite_and_changed_facts(self):
        self.assertEqual(
            safe_asr_correction('nhiệt độ là 28 độ', 'Thời tiết hôm nay rất đẹp và nhiệt độ là 30 độ.'),
            'nhiệt độ là 28 độ')
        self.assertEqual(
            safe_asr_correction('Moon mở ESP32 số 2', 'Mở thiết bị số 3'),
            'Moon mở ESP32 số 2')

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

    def test_only_narrow_moon_misses_are_eligible_for_verification(self):
        for text in ['', 'Mun', 'Mùn ơi', 'Hey Muôn', 'muun']:
            self.assertTrue(possible_moon_miss(text), text)
        for text in ['muốn', 'môn', 'món', 'muốn ăn', 'môn học', 'moonlight', 'xin chào']:
            self.assertFalse(possible_moon_miss(text), text)

    def test_short_wake_candidates_get_second_pass_but_real_near_words_do_not(self):
        for text in ['Moon', 'Mum', 'move', 'xin chào']:
            self.assertTrue(should_verify_wake(text,1200),text)
        for text in ['muốn', 'môn học', 'món ngon']:
            self.assertFalse(should_verify_wake(text,1200),text)
        self.assertFalse(should_verify_wake('một câu nói dài hơn ba từ',1200))
        self.assertFalse(should_verify_wake('Moon',4000))

    def test_two_stt_passes_can_confirm_a_moon_spelling_variant(self):
        self.assertEqual(confirmed_wake_tail('Mun', 'Hey Mun'), '')
        self.assertEqual(confirmed_wake_tail('Mun', 'Hey Moon'), '')
        self.assertEqual(confirmed_wake_tail('Hey Mom', 'Hey Mum'), '')
        self.assertEqual(confirmed_wake_tail('Hey Moon', 'Hey Moan'), '')
        self.assertEqual(confirmed_wake_tail('Hê mon', 'Hey Moon'), '')
        self.assertEqual(confirmed_wake_tail('Hey muon', 'Hey Moon'), '')
        self.assertIsNone(confirmed_wake_tail('Mun', 'Mom'))
        self.assertIsNone(confirmed_wake_tail('Mom', 'Mum'))
        self.assertIsNone(confirmed_wake_tail('môn', 'Hey Mom'))
        self.assertIsNone(confirmed_wake_tail('xin chào', 'Hey Mun'))

    def test_vietnamese_stt_miss_after_explicit_hey_uses_english_confirmation(self):
        for primary in ['Hey múa', 'Hey mưa', 'Hey mua']:
            self.assertEqual(confirmed_wake_tail(primary, 'Hey Moon'), '', primary)
        # A Vietnamese word without an explicit call prefix remains protected.
        self.assertIsNone(confirmed_wake_tail('trời mưa', 'Hey Moon'))

    def test_confident_explicit_call_skips_slow_second_pass(self):
        for text in [
                'Hey Moon', 'Moon', 'Hey múa', 'Hey mưa', 'Hi Mun',
                'ê Môn', 'này Mun', 'Moon ơi', 'Mun ơi', 'alo Moon']:
            self.assertEqual(confident_wake_tail(text), '', text)
        for text in ['trời mưa', 'đi múa', 'môn học', 'món ngon', 'Hey man', 'xin chào']:
            self.assertIsNone(confident_wake_tail(text), text)

    def test_one_pass_or_blank_noise_cannot_confirm_wake(self):
        self.assertEqual(confirmed_wake_tail('', 'Hey Moon'), '')
        self.assertIsNone(confirmed_wake_tail('', 'Moon'))
        self.assertIsNone(confirmed_wake_tail('', 'Hey man'))
        self.assertIsNone(confirmed_wake_tail('A', 'Moon'))
        self.assertIsNone(confirmed_wake_tail('xin chào', 'Moon'))

    def test_short_wake_uses_relaxed_confidence_but_still_rejects_noise(self):
        uncertain = {'text': 'Hey Moon', 'segments': [
            {'no_speech_prob': .65, 'avg_logprob': -1.2, 'compression_ratio': 1.1}]}
        self.assertEqual(reliable_transcript(uncertain), '')
        self.assertEqual(wake_transcript(uncertain), 'Hey Moon')
        self.assertEqual(wake_transcript({
            'text': 'Moon',
            'segments': [{'no_speech_prob': .96, 'avg_logprob': -2.1}],
        }), '')

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

    def test_known_whisper_outro_hallucinations_are_rejected(self):
        result = {
            'text': 'Hãy subscribe cho kênh Ghiền Mì Gõ để không bỏ lỡ những video hấp dẫn',
            'segments': [{'no_speech_prob': .01, 'avg_logprob': -.1}],
        }
        self.assertEqual(reliable_transcript(result), '')


if __name__ == '__main__':
    unittest.main()
