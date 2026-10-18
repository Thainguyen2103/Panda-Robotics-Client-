import unittest
import sys
sys.path.insert(0, ".")

from server.llm import engine as llm
from server.llm.rag_engine import MoonRAG, get_display_info, retrieve_context


class LearningRagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = MoonRAG()

    def test_loads_teammate_knowledge_base(self):
        self.assertEqual(len(self.rag.knowledge_base), 53)

    def test_exact_japanese_lesson_match(self):
        for question in (
            "Moon ơi, con mèo tiếng Nhật đọc sao?",
            "猫は日本語でどう読みますか？",
        ):
            result = self.rag.search(question, top_k=1)
            self.assertEqual(result[0]["id"], "animal_cat")
            self.assertEqual(result[0]["ja_kanji"], "猫")
            self.assertEqual(result[0]["ja_kana"], "ねこ")

    def test_unaccented_stt_query_match(self):
        result = self.rag.search("chi cho be tu qua tao di moon", top_k=1)
        self.assertEqual(result[0]["id"], "fruit_apple")

    def test_indirect_semantic_match(self):
        result = self.rag.search("con gi co chiec voi rat dai thich an mia", top_k=1)
        self.assertEqual(result[0]["id"], "animal_elephant")

    def test_general_conversation_does_not_inject_unrelated_lesson(self):
        # NOTE (Task 12B/13): VECTOR_SIMILARITY_THRESHOLD was calibrated to 0.7961
        # to achieve 100% in-corpus recall.
        # General out-of-domain conversation queries below MUST cleanly return [] (clean abstention):
        for question in (
            "Hey, do you know who I am?",
            "What is the capital of France?",
            "How do I build a rocket engine?",
            "Who invented the telephone?",
            "Qu est-ce que le subjonctif en francais?",
        ):
            self.assertEqual(self.rag.search(question), [],
                             msg=f"Expected [] for out-of-domain query: {question!r}")
            self.assertEqual(retrieve_context(question), "")

    def test_science_adjacent_queries_accepted_borderline_fp(self):
        # Task 12B/13: Queries with semantic overlap to corpus topics (physics -> science,
        # Japanese greetings -> manner/etiquette lessons) are evaluated to ensure they
        # either cleanly abstain or retrieve only semantically related categories.
        queries_and_allowed_categories = [
            ("Explain quantum physics", {"subj_science", "subj_math"}),
            ("こんにちは", {"manner_gochisousama", "manner_itadakimasu", "manner_ittekimasu", "manner_tadaima", "feel_kind"}),
            ("今何時ですか？", {"manner_tadaima", "obj_clock", "act_wake_up", "act_study", "act_sleep"}),
        ]
        for question, allowed_ids in queries_and_allowed_categories:
            results = self.rag.search(question)
            returned_ids = {r["id"] for r in results}
            self.assertTrue(
                returned_ids.issubset(allowed_ids) or returned_ids == set(),
                msg=f"Query {question!r} returned unexpected IDs: {returned_ids}"
            )

    def test_service_formats_prompt_and_display_payload(self):
        context = retrieve_context("con mèo tiếng Nhật", top_k=1)
        display = get_display_info("猫は日本語でどう読みますか？")
        self.assertIn("猫", context)
        self.assertIn("ねこ", context)
        self.assertEqual(display["id"], "animal_cat")
        self.assertIn(display["romaji"], ("Neko", "nê-kô"))

    def test_llm_messages_include_verified_lesson_and_language_rule(self):
        messages = llm._get_messages("Con mèo tiếng Nhật đọc thế nào?")
        contents = [message["content"] for message in messages]
        self.assertTrue(any("LESSON DATA" in item for item in contents))
        self.assertTrue(any("猫" in item for item in contents))
        self.assertIn("Chỉ trả lời bằng tiếng Việt", contents[-2])

    def test_llm_does_not_inject_lessons_into_regular_conversation(self):
        for question in (
            "Xin chào Moon, hãy trả lời thật ngắn.",
            "Bạn thích màu gì?",
            "Hãy nói một điều vui vẻ.",
        ):
            contents = [message["content"] for message in llm._get_messages(question)]
            self.assertFalse(any("Verified learning material" in item for item in contents))


if __name__ == "__main__":
    unittest.main()
