import unittest
import sys
from types import ModuleType
from unittest.mock import patch

from server.llm.brain_router import Intent, IntentRouter


class IntentRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = IntentRouter()

    def test_knowledge_questions_are_grounded_with_rag(self):
        questions = [
            "Con mèo tiếng Nhật là gì?",
            "Mặt trời là gì?",
            "What does neko mean in English?",
            "りんごの意味は何ですか？",
            "Translate hello into English",
        ]
        for question in questions:
            with self.subTest(question=question):
                route = self.router.classify(question)
                self.assertEqual(route.intent, Intent.KNOWLEDGE_QNA)
                self.assertTrue(route.use_rag)

    def test_chitchat_bypasses_rag(self):
        questions = [
            "Chào Moon!",
            "Hôm nay bạn thế nào?",
            "Cảm ơn nhé",
            "How are you, Moon?",
            "こんにちは",
        ]
        for question in questions:
            with self.subTest(question=question):
                route = self.router.classify(question)
                self.assertEqual(route.intent, Intent.CHITCHAT)
                self.assertFalse(route.use_rag)

    def test_grammar_fix_requests_have_dedicated_route(self):
        questions = [
            "Sửa giúp tớ câu này: Watashi wa ringo wo tabemasu",
            "Câu này đúng ngữ pháp chưa?",
            "Is this sentence correct?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(self.router.classify(question).intent, Intent.GRAMMAR_FIX)

    def test_curriculum_requests_have_dedicated_route(self):
        questions = ["Hôm nay học bài gì tiếp theo?", "Tớ hoàn thành N5 chưa?"]
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(self.router.classify(question).intent, Intent.CURRICULUM_NEXT)

    def test_pronunciation_route_is_recognized(self):
        self.assertEqual(
            self.router.classify("Moon nghe tớ đọc từ Arigatou xem chuẩn chưa").intent,
            Intent.PRONUNCIATION,
        )

    def test_ambiguous_input_defaults_to_grounded_knowledge_route(self):
        route = self.router.classify("Could you tell me about this?")
        self.assertEqual(route.intent, Intent.KNOWLEDGE_QNA)
        self.assertTrue(route.use_rag)
        self.assertLess(route.confidence, 0.5)


class EngineDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Avoid both Ollama readiness calls and RAG/model initialization.
        from server.llm_providers.ollama import OllamaTextClient

        cls.ensure_ready_patch = patch.object(OllamaTextClient, "ensure_ready", return_value=None)
        cls.ensure_ready_patch.start()
        rag_stub = ModuleType("server.llm.rag_engine")
        rag_stub.retrieve_context = lambda *_args, **_kwargs: "verified lesson fixture"
        rag_stub.get_display_info = lambda *_args, **_kwargs: None
        cls.rag_patch = patch.dict(sys.modules, {"server.llm.rag_engine": rag_stub})
        cls.rag_patch.start()
        try:
            from server.llm import engine
            cls.engine = engine
        finally:
            cls.rag_patch.stop()

    @classmethod
    def tearDownClass(cls):
        cls.ensure_ready_patch.stop()

    def test_engine_calls_rag_only_for_knowledge_intents(self):
        calls = []

        def retrieve(question, top_k):
            calls.append((question, top_k))
            return "verified lesson fixture"

        with patch.object(self.engine, "_retrieve_learning_context", side_effect=retrieve), \
             patch.object(self.engine, "_maybe_weather", return_value=None):
            questions = [
                "Con mèo tiếng Nhật là gì?",
                "Mặt trời là gì?",
                "What does neko mean in English?",
                "りんごの意味は何ですか？",
                "Translate hello into English",
            ]
            for question in questions:
                with self.subTest(knowledge_question=question):
                    messages = self.engine._get_messages(question)
                    self.assertTrue(any("verified lesson fixture" in m["content"] for m in messages))
            self.assertEqual(len(calls), len(questions))

            calls.clear()
            chat_questions = [
                "Chào Moon!", "Hôm nay bạn thế nào?", "Cảm ơn nhé",
                "How are you, Moon?", "こんにちは",
            ]
            for question in chat_questions:
                with self.subTest(chitchat_question=question):
                    messages = self.engine._get_messages(question)
                    self.assertFalse(any("verified lesson fixture" in m["content"] for m in messages))
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
