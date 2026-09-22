import unittest
from unittest.mock import patch

from server import llm


class ResponseLanguageTests(unittest.TestCase):
    def test_english_turn_is_answered_in_english(self):
        question = 'Hey, do you know who I am?'
        for utterance in [question, 'Explain quantum physics']:
            self.assertEqual(llm.response_language(utterance), 'en')
        messages = llm._get_messages(question)
        self.assertIn('Reply only in natural English', messages[-2]['content'])

    def test_vietnamese_turn_is_answered_in_vietnamese(self):
        question = 'Bạn có biết mình là ai không?'
        self.assertEqual(llm.response_language(question), 'vi')
        self.assertIn('Chỉ trả lời bằng tiếng Việt', llm.response_language_instruction(question))

    def test_japanese_turn_is_answered_in_japanese(self):
        for question in ['こんにちは。今日の天気はどうですか？', '今日晴天？']:
            self.assertEqual(llm.response_language(question), 'ja')
            self.assertIn('日本語', llm.response_language_instruction(question))

    def test_foreign_term_does_not_override_conversation_language(self):
        cases = {
            'Computer nghĩa là gì trong tiếng Việt?': 'vi',
            'こんいちは nghĩa là gì vậy Moon?': 'vi',
            'What does こんにちは mean?': 'en',
            '猫は英語で何ですか？': 'ja',
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(llm.response_language(question), expected)

    def test_safe_japanese_greeting_typo_is_repaired_before_llm(self):
        self.assertEqual(
            llm.normalize_user_question('こんいちは nghĩa là gì?'),
            'こんにちは nghĩa là gì?',
        )

    def test_explicit_response_language_wins(self):
        self.assertEqual(
            llm.response_language('こんにちは。Trả lời bằng tiếng Việt nhé.'),
            'vi',
        )
        self.assertEqual(
            llm.response_language('Xin chào. Answer in Japanese.'),
            'ja',
        )

    def test_output_language_validation_allows_quoted_foreign_terms(self):
        self.assertTrue(llm.response_language_matches(
            'こんにちは có nghĩa là xin chào trong tiếng Việt.', 'vi'
        ))
        self.assertTrue(llm.response_language_matches(
            'こんにちは means hello in English.', 'en'
        ))
        self.assertTrue(llm.response_language_matches(
            '「Computer」はベトナム語で「máy tính」です。', 'ja'
        ))
        self.assertFalse(llm.response_language_matches(
            'Hello! How can I help you today?', 'ja'
        ))

    def test_chat_retries_wrong_language_before_emitting_audio_text(self):
        chunks = []
        with (
            patch.object(llm, '_client', object()),
            patch.object(llm, '_provider_name', 'ollama'),
            patch.object(llm, '_model_name', 'test-qwen'),
            patch.object(llm, '_get_messages', return_value=[
                {'role': 'system', 'content': 'system'},
                {'role': 'user', 'content': 'こんにちは。'},
            ]),
            patch.object(
                llm,
                '_stream_provider',
                side_effect=[
                    iter(['Hello! How can I help?']),
                    iter(['こんにちは！何をお手伝いしましょうか？']),
                ],
            ) as stream,
            patch.object(llm, '_add_to_history'),
        ):
            answer = llm.chat('こんにちは。', on_chunk=chunks.append)

        self.assertEqual(answer, 'こんにちは！何をお手伝いしましょうか？')
        self.assertEqual(chunks, [answer])
        self.assertEqual(stream.call_count, 2)

    def test_mixed_or_ambiguous_turn_is_adaptive_not_duplicated(self):
        for question in ['Bạn know who I am?', 'Ronaldo?']:
            self.assertEqual(llm.response_language(question), 'adaptive')
            instruction = llm.response_language_instruction(question)
            self.assertIn('Code-switch', instruction)
            self.assertIn('Do not duplicate', instruction)


if __name__ == '__main__':
    unittest.main()
