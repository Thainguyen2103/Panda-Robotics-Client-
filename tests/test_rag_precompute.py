import unittest

from server.llm.rag_engine import MoonRAG


class RagPrecomputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = MoonRAG()

    def test_load_precomputes_lexical_fields(self):
        cat = next(item for item in self.rag.knowledge_base if item.get("id") == "animal_cat")
        self.assertIn(("con mèo", "con meo"), cat["_rag_keywords_normalized"])
        self.assertEqual(cat["_rag_vi_normalized"], "con mèo")
        self.assertEqual(cat["_rag_vi_unaccented"], "con meo")
        self.assertIn("animals", cat["_rag_topic_tokens"])

    def test_lexical_results_preserve_accented_and_unaccented_queries(self):
        for query in ("chi cho be tu qua tao di moon", "con mèo tiếng Nhật"):
            clean = self.rag._clean_query(query)
            result = self.rag._tier2_lexical_filter(clean)
            self.assertTrue(result)
        result = self.rag._tier2_lexical_filter("chi cho be tu qua tao di")
        self.assertEqual(result[0]["id"], "fruit_apple")

    def test_lexical_filter_supports_unannotated_items(self):
        rag = MoonRAG.__new__(MoonRAG)
        rag.knowledge_base = [{"keywords": ["con mèo"], "vi": "Con mèo", "topic": "Animals"}]
        self.assertEqual(rag._tier2_lexical_filter("con meo")[0]["vi"], "Con mèo")


if __name__ == "__main__":
    unittest.main()
