import unittest

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

    def test_mixed_or_ambiguous_turn_is_adaptive_not_duplicated(self):
        for question in ['Bạn know who I am?', 'Ronaldo?']:
            self.assertEqual(llm.response_language(question), 'adaptive')
            instruction = llm.response_language_instruction(question)
            self.assertIn('Code-switch', instruction)
            self.assertIn('Do not duplicate', instruction)


if __name__ == '__main__':
    unittest.main()
