import unittest

from server import llm
from server.learning.rag_engine import MoonRAG
from server.learning.service import get_display_info, retrieve_context


class LearningRagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = MoonRAG()

    def test_loads_teammate_knowledge_base(self):
        self.assertEqual(len(self.rag.knowledge_base), 48)

    def test_exact_japanese_lesson_match(self):
        for question in (
            "Moon ơi, con mèo tiếng Nhật đọc sao?",
            "猫は日本語でどう読みますか？",
        ):
            result = self.rag.search(question, top_k=1)
            self.assertEqual(result[0]["id"], "animal_cat")
            self.assertEqual(result[0]["kanji"], "猫")
            self.assertEqual(result[0]["japanese_hiragana"], "ねこ")

    def test_unaccented_stt_query_match(self):
        result = self.rag.search("chi cho be tu qua tao di moon", top_k=1)
        self.assertEqual(result[0]["id"], "fruit_apple")

    def test_indirect_semantic_match(self):
        result = self.rag.search("con gi co chiec voi rat dai thich an mia", top_k=1)
        self.assertEqual(result[0]["id"], "animal_elephant")

    def test_general_conversation_does_not_inject_unrelated_lesson(self):
        for question in (
            "Hey, do you know who I am?",
            "Explain quantum physics",
            "こんにちは",
        ):
            self.assertEqual(self.rag.search(question), [])
            self.assertEqual(retrieve_context(question), "")

    def test_service_formats_prompt_and_display_payload(self):
        context = retrieve_context("con mèo tiếng Nhật", top_k=1)
        display = get_display_info("猫は日本語でどう読みますか？")
        self.assertIn("猫", context)
        self.assertIn("ねこ", context)
        self.assertEqual(display["id"], "animal_cat")
        self.assertEqual(display["romaji"], "Neko")

    def test_llm_messages_include_verified_lesson_and_language_rule(self):
        messages = llm._get_messages("Con mèo tiếng Nhật đọc thế nào?")
        contents = [message["content"] for message in messages]
        self.assertTrue(any("Verified learning material" in item for item in contents))
        self.assertTrue(any("猫" in item for item in contents))
        self.assertIn("Chỉ trả lời bằng tiếng Việt", contents[-2])


if __name__ == "__main__":
    unittest.main()
