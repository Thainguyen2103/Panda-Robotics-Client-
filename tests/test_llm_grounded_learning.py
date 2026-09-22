import unittest
from unittest.mock import patch

from server import llm


APPLE = {
    "kanji": "林檎",
    "hiragana": "りんご",
    "romaji": "Ringo",
    "english": "Apple",
    "vietnamese": "Quả táo đỏ",
}


class GroundedLearningAnswerTests(unittest.TestCase):
    def test_realtime_time_answer_uses_latest_turn_language(self):
        japanese = llm.realtime_answer("今何時ですか？")
        english = llm.realtime_answer("What time is it?")
        vietnamese = llm.realtime_answer("Bây giờ là mấy giờ?")
        self.assertIn("現在は", japanese)
        self.assertIn("です", japanese)
        self.assertTrue(english.startswith("It is "))
        self.assertTrue(vietnamese.startswith("Bây giờ là "))

    def test_non_time_question_does_not_use_realtime_shortcut(self):
        self.assertIsNone(llm.realtime_answer("Hãy kể một câu chuyện ngắn"))

    def test_direct_lookup_is_grounded_in_vietnamese(self):
        with patch.object(llm, "learning_display_info", return_value=APPLE):
            answer = llm.grounded_learning_answer(
                "Quả táo trong tiếng Nhật đọc thế nào?"
            )
        self.assertIn("林檎", answer)
        self.assertIn("りんご", answer)
        self.assertIn("Ringo", answer)
        self.assertIn("Apple", answer)

    def test_direct_lookup_uses_latest_turn_language(self):
        with patch.object(llm, "learning_display_info", return_value=APPLE):
            english = llm.grounded_learning_answer(
                "How do you say apple in Japanese?"
            )
            japanese = llm.grounded_learning_answer(
                "林檎は日本語でどう読みますか？"
            )
        self.assertTrue(english.startswith("In Japanese"))
        self.assertIn("ローマ字", japanese)

    def test_chat_can_answer_verified_lookup_without_llm(self):
        chunks = []
        with (
            patch.object(llm, "_client", None),
            patch.object(llm, "learning_display_info", return_value=APPLE),
            patch.object(llm, "_add_to_history"),
        ):
            answer = llm.chat(
                "How do you say apple in Japanese?",
                on_chunk=chunks.append,
            )
        self.assertEqual(chunks, [answer])
        self.assertIn("林檎", answer)
        self.assertNotIn("Gemini", answer)

    def test_open_ended_question_still_goes_to_qwen(self):
        with patch.object(llm, "learning_display_info") as lookup:
            answer = llm.grounded_learning_answer("Tell me a story about an apple")
        self.assertIsNone(answer)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
