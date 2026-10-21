"""Offline regression coverage for the production MoonRAG retrieval path."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

# Keep test execution offline even on machines without a local model cache.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from server.llm import rag_engine
from server.llm.rag_engine import MoonRAG


class FakeEmbedder:
    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32)

    def encode(self, texts, **kwargs):
        return self.vector.reshape(1, -1)


class RagRetrievalRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = MoonRAG()

    def tearDown(self):
        # search is decorated with a shared lru_cache wrapper.
        self.rag.search.cache_clear()

    def result_ids(self, query):
        return [item["id"] for item in self.rag.search(query, top_k=2)]

    def test_jaccard_fallback_ignores_english_function_words(self):
        self.assertEqual(self.rag._tier3_jaccard_fallback("Hey, do you know who I am?"), [])
        results = self.rag._tier3_jaccard_fallback("con gi co chiec voi rat dai thich an mia")
        self.assertEqual(results[0]["id"], "animal_elephant")

    def test_paraphrase_does_not_match_mother_from_english_substring(self):
        query = (
            "Which Japanese word names the animal whose eyes see in the dark "
            "and that walks silently without a sound?"
        )
        # Red on the pre-fix implementation: "me" (Mẹ, after accent strip)
        # is found inside "names", so lexical tier short-circuits vector search.
        lexical = self.rag._tier2_lexical_filter(query)
        self.assertNotIn("family_mother", [item["id"] for item in lexical])

    def test_vietnamese_mother_forms_match_as_bounded_terms(self):
        for query in ("mẹ", "me", "mẹ của tôi", "me cua toi"):
            with self.subTest(query=query):
                results = self.rag._tier2_lexical_filter(query)
                self.assertTrue(results)
                self.assertEqual(results[0]["id"], "family_mother")

    def test_english_words_containing_unaccented_vietnamese_do_not_match(self):
        for query in ("names", "someone named Moon", "the same animal"):
            with self.subTest(query=query):
                results = self.rag._tier2_lexical_filter(query)
                self.assertNotIn("family_mother", [item["id"] for item in results])

    def test_normal_vietnamese_accented_and_unaccented_queries(self):
        for query in ("con mèo", "con meo", "chi cho be tu qua tao di"):
            with self.subTest(query=query):
                results = self.rag._tier2_lexical_filter(query)
                self.assertTrue(results)
                expected = "fruit_apple" if "tao" in query else "animal_cat"
                self.assertEqual(results[0]["id"], expected)

    def test_japanese_kanji_kana_and_romaji_exact_queries(self):
        for query in ("猫", "ねこ", "neko"):
            with self.subTest(query=query):
                results = self.rag.search(query, top_k=1)
                self.assertEqual(results[0]["id"], "animal_cat")

    def test_known_exact_and_keyword_queries_keep_working(self):
        for query, expected in (
            ("cat", "animal_cat"),
            ("Moon ơi con mèo tiếng Nhật đọc sao?", "animal_cat"),
            ("apple", "fruit_apple"),
        ):
            with self.subTest(query=query):
                self.assertEqual(self.result_ids(query)[0], expected)

    def test_unrelated_query_returns_no_record(self):
        # Force the offline Jaccard fallback; this test does not require a model.
        with patch.object(rag_engine, "_get_embedder", return_value=None):
            self.assertEqual(self.rag.search("Explain differential equations", top_k=1), [])

    def test_cascade_uses_vector_after_lexical_false_positive_is_removed(self):
        query = "Which Japanese word names the animal whose eyes see in the dark and walks silently?"
        cat = next(item for item in self.rag.knowledge_base if item["id"] == "animal_cat")
        with patch.object(self.rag, "_tier3_vector_search", return_value=[cat]) as vector_search:
            results = self.rag.search(query, top_k=1)
        self.assertEqual([item["id"] for item in results], ["animal_cat"])
        vector_search.assert_called_once()

    def test_vector_fallback_with_fake_embedder(self):
        rag = MoonRAG.__new__(MoonRAG)
        rag.knowledge_base = [{"id": "vector_hit"}, {"id": "other"}]
        rag._embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        with patch.object(rag_engine, "_get_embedder", return_value=FakeEmbedder([1.0, 0.0])):
            self.assertEqual([x["id"] for x in rag._tier3_vector_search("semantic query")], ["vector_hit"])


class RagCacheFixtureTests(unittest.TestCase):
    class StubEmbedder:
        def __init__(self):
            self.calls = []

        def encode(self, texts, **kwargs):
            self.calls.append(list(texts))
            return np.tile(np.asarray([[1.0, 0.0]], dtype=np.float32), (len(texts), 1))

    def make_rag(self, data_file):
        rag = MoonRAG.__new__(MoonRAG)
        rag.data_file = str(data_file)
        rag.knowledge_base = [{"id": "fixture", "vi": "Xin chào"}]
        rag._embeddings = None
        rag._embedding_texts = []
        return rag

    def temp_directory(self):
        # Keep fixtures inside the writable checkout; Windows sandbox temp may
        # be outside the workspace and deny writes.
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def test_valid_fixture_cache_is_reused_without_model(self):
        with self.temp_directory() as directory:
            data = Path(directory) / "data.json"
            cache = Path(directory) / "cache.npz"
            data.write_text(json.dumps([{"id": "fixture"}]), encoding="utf-8")
            fingerprint = rag_engine._data_file_hash(str(data))
            np.savez_compressed(cache, embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32), hash=fingerprint)
            rag = self.make_rag(data)
            with patch.object(rag_engine, "EMBEDDINGS_CACHE_PATH", str(cache)), patch.object(
                rag_engine, "_get_embedder", side_effect=AssertionError("must reuse fixture cache")
            ):
                rag._build_embeddings()
            self.assertEqual(rag._embeddings.shape, (1, 2))

    def test_bad_hash_and_wrong_row_count_rebuild_only_fixture_cache(self):
        for cached_hash, rows in (("not-the-data-hash", 1), ("wrong-row-count", 2)):
            with self.subTest(rows=rows), self.temp_directory() as directory:
                data = Path(directory) / "data.json"
                cache = Path(directory) / "cache.npz"
                data.write_text(json.dumps([{"id": "fixture"}]), encoding="utf-8")
                np.savez_compressed(cache, embeddings=np.ones((rows, 2), dtype=np.float32), hash=cached_hash)
                rag = self.make_rag(data)
                embedder = self.StubEmbedder()
                with patch.object(rag_engine, "EMBEDDINGS_CACHE_PATH", str(cache)), patch.object(
                    rag_engine, "_get_embedder", return_value=embedder
                ):
                    rag._build_embeddings()
                self.assertEqual(len(embedder.calls), 1)
                self.assertEqual(rag._embeddings.shape, (1, 2))

    def test_corrupt_fixture_archive_rebuilds(self):
        with self.temp_directory() as directory:
            data = Path(directory) / "data.json"
            cache = Path(directory) / "cache.npz"
            data.write_text(json.dumps([{"id": "fixture"}]), encoding="utf-8")
            cache.write_bytes(b"not an npz archive")
            rag = self.make_rag(data)
            embedder = self.StubEmbedder()
            with patch.object(rag_engine, "EMBEDDINGS_CACHE_PATH", str(cache)), patch.object(
                rag_engine, "_get_embedder", return_value=embedder
            ):
                rag._build_embeddings()
            self.assertEqual(len(embedder.calls), 1)
            self.assertEqual(rag._embeddings.shape, (1, 2))

    def test_legacy_cache_dimension_and_nonfinite_validation_gap(self):
        """Characterize known gaps; this test never touches the production cache."""
        for vector in (np.ones((1, 3), dtype=np.float32), np.asarray([[np.nan, 0]], dtype=np.float32),
                       np.asarray([[np.inf, 0]], dtype=np.float32)):
            with self.subTest(vector=vector.tolist()), self.temp_directory() as directory:
                data = Path(directory) / "data.json"
                cache = Path(directory) / "cache.npz"
                data.write_text(json.dumps([{"id": "fixture"}]), encoding="utf-8")
                np.savez_compressed(cache, embeddings=vector, hash=rag_engine._data_file_hash(str(data)))
                rag = self.make_rag(data)
                with patch.object(rag_engine, "EMBEDDINGS_CACHE_PATH", str(cache)), patch.object(
                    rag_engine, "_get_embedder", side_effect=AssertionError("legacy loader accepts this cache")
                ):
                    rag._build_embeddings()
                self.assertEqual(rag._embeddings.shape[0], 1)

    def test_reload_invalidates_search_results_for_same_query(self):
        with self.temp_directory() as directory:
            data = Path(directory) / "data.json"
            data.write_text(json.dumps([{"id": "first", "vi": "Con mèo"}]), encoding="utf-8")
            rag = MoonRAG.__new__(MoonRAG)
            rag.data_file = str(data)
            rag.knowledge_base = []
            rag.inverted_index = {}
            rag._embeddings = None
            rag._embedding_texts = []
            with patch.object(rag, "_build_embeddings"):
                rag.load_data()
                self.assertEqual(rag.search("con mèo", top_k=1)[0]["id"], "first")
                data.write_text(json.dumps([{"id": "second", "vi": "Con mèo"}]), encoding="utf-8")
                rag.load_data()
                self.assertEqual(rag.search("con mèo", top_k=1)[0]["id"], "second")


if __name__ == "__main__":
    unittest.main()
