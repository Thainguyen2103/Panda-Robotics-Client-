"""Offline baseline runner for the real MOON RAG retrieval implementation.

The expected IDs below are manually labelled from server/llm/data.json before
running retrieval. This script imports only the production retriever; it never
calls an LLM or writes the corpus/cache. It refuses to import RAG unless the
existing cache is a verified hit, preventing the production loader's rebuild
path from being entered.
"""

import contextlib
import hashlib
import io
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA_PATH = ROOT / "server" / "llm" / "data.json"
CACHE_PATH = ROOT / "server" / "llm" / ".rag_embeddings.npz"


def local_embedding_snapshot_complete():
    """Check the expected local HF snapshot files without resolving a model."""
    cache_root = os.environ.get("HF_HUB_CACHE")
    if not cache_root:
        hf_home = os.environ.get("HF_HOME")
        cache_root = str(Path(hf_home) / "hub") if hf_home else str(Path.home() / ".cache" / "huggingface" / "hub")
    model_dir = Path(cache_root) / "models--intfloat--multilingual-e5-small" / "snapshots"
    if not model_dir.is_dir():
        return False
    required = {"config.json", "modules.json", "tokenizer_config.json"}
    for snapshot in model_dir.iterdir():
        if not snapshot.is_dir():
            continue
        files = {path.name for path in snapshot.iterdir() if path.is_file()}
        has_weights = "model.safetensors" in files or "pytorch_model.bin" in files
        has_tokenizer = "tokenizer.json" in files or "sentencepiece.bpe.model" in files
        if required.issubset(files) and has_weights and has_tokenizer:
            return True
    return False

# Labels were assigned from the record fields/facts in data.json, before any
# retrieval results were collected. Each expected ID identifies one KB record.
QUERIES = [
    ("q01", "cat", "animal_cat", "Direct English vocabulary field."),
    ("q02", "mèo", "animal_cat", "Vietnamese vocabulary field."),
    ("q03", "con meo", "animal_cat", "Unaccented Vietnamese keyword."),
    ("q04", "猫", "animal_cat", "Kanji field."),
    ("q05", "ねこ", "animal_cat", "Kana keyword."),
    ("q06", "neko", "animal_cat", "Romaji keyword."),
    ("q07", "Which animal sees in the dark?", "animal_cat", "Paraphrase supported by the cat fact."),
    ("q08", "Mother", "family_mother", "Direct English vocabulary field."),
    ("q09", "mẹ", "family_mother", "Vietnamese vocabulary field."),
    ("q10", "me", "family_mother", "Unaccented Vietnamese title."),
    ("q11", "Who is the female parent?", "family_mother", "English paraphrase of the Mother record."),
    ("q12", "dog", "animal_dog", "Direct English vocabulary field."),
    ("q13", "犬", "animal_dog", "Kanji field."),
    ("q14", "いぬ", "animal_dog", "Kana keyword."),
    ("q15", "inu", "animal_dog", "Romaji keyword."),
    ("q16", "elephant", "animal_elephant", "Direct English vocabulary field."),
    ("q17", "象", "animal_elephant", "Kanji keyword."),
    ("q18", "Which animal has a long trunk and likes sugar cane?", "animal_elephant", "Paraphrase supported by the elephant fact/keywords."),
    ("q19", "sun", "nature_sun", "Direct English vocabulary field."),
    ("q20", "太陽", "nature_sun", "Kanji field and keyword."),
    ("q21", "What gives light and warmth that sustains life?", "nature_sun", "Paraphrase supported by the sun fact."),
    ("q22", "apple", "fruit_apple", "Direct English vocabulary field."),
    ("q23", "りんご", "fruit_apple", "Kana keyword."),
    ("q24", "Which fruit has vitamin C and fiber?", "fruit_apple", "Paraphrase supported by the apple fact."),
    ("q25", "What is the Japanese word for water bottle?", "obj_water_bottle", "Vocabulary request supported by the Water bottle record."),
    ("n01", "How do I build a rocket engine?", None, "No corresponding record in this vocabulary corpus."),
    ("n02", "What is the capital of France?", None, "No corresponding record in this vocabulary corpus."),
    ("n03", "Explain quantum entanglement.", None, "No corresponding record in this vocabulary corpus."),
]


def percentile(values, pct):
    return float(np.percentile(np.asarray(values, dtype=np.float64), pct))


def retrieval_metrics(rows, field, positives):
    relevant = sum(
        row["expected"] in row[field].split(",")
        for row in rows
        if row["expected"] != "NONE"
    )
    returned = sum(
        len(row[field].split(",")) for row in rows if row[field] != "NONE"
    )
    precision = relevant / returned if returned else 0.0
    recall = relevant / positives if positives else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"relevant_records": relevant, "returned_records": returned,
            "precision": precision, "recall": recall, "f1": f1}


def main():
    if os.environ.get("HF_HUB_OFFLINE") != "1" or os.environ.get("HF_HUB_DISABLE_TELEMETRY") != "1":
        raise SystemExit("Set HF_HUB_OFFLINE=1 and HF_HUB_DISABLE_TELEMETRY=1 before Python.")

    # Preflight without importing the RAG module: its constructor can rebuild
    # cache on a miss. Only proceed when data and cache prove this is a hit.
    corpus = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    corpus_hash = hashlib.md5(DATA_PATH.read_bytes()).hexdigest()
    with np.load(CACHE_PATH, allow_pickle=False) as cache:
        cache_keys = set(cache.files)
        cache_hash = str(cache["hash"].item()) if "hash" in cache_keys else None
        vectors = cache["embeddings"] if "embeddings" in cache_keys else None
        if (
            cache_hash != corpus_hash
            or vectors is None
            or vectors.ndim != 2
            or vectors.shape[0] != len(corpus)
            or not np.isfinite(vectors).all()
        ):
            raise SystemExit("Production cache is not a verified read-only hit; retrieval was not imported or run.")

    ids = [str(record.get("id", "")) for record in corpus]
    if len(ids) != len(set(ids)) or any(expected and expected not in ids for _, _, expected, _ in QUERIES):
        raise SystemExit("Labels require IDs absent from or duplicated in the current corpus; stop for manual review.")

    # This import creates the real production MoonRAG singleton. Cache preflight
    # above ensures its constructor takes the cache-hit branch, not rebuild.
    import server.llm.rag_engine as production_rag

    rag = production_rag._get_rag()
    if rag._embeddings is None:
        raise SystemExit("Production retriever did not load the verified cached vectors; no evaluation performed.")

    # Confirm whether the actual query encoder can be imported without loading a
    # model. Missing sentence-transformers means semantic vector queries are
    # intentionally not attempted by this runner.
    try:
        import importlib.util
        semantic_available = (
            importlib.util.find_spec("sentence_transformers") is not None
            and local_embedding_snapshot_complete()
        )
    except (ImportError, ValueError):
        semantic_available = False
    if not semantic_available:
        # In-memory only: choose the same Jaccard fallback branch production
        # uses when no embedder can be initialized. Never attempt model resolve.
        rag._embeddings = None

    # Warm search is excluded from per-query measurements.
    with contextlib.redirect_stdout(io.StringIO()):
        rag.search("Moon ơi cat", top_k=2)

    rows = []
    for query_id, query, expected, rationale in QUERIES:
        t0 = time.perf_counter_ns()
        exact = rag._tier1_exact_filter(query)
        exact_ms = (time.perf_counter_ns() - t0) / 1_000_000
        t0 = time.perf_counter_ns()
        lexical = rag._tier2_lexical_filter(query)
        lexical_ms = (time.perf_counter_ns() - t0) / 1_000_000

        t0 = time.perf_counter_ns()
        with contextlib.redirect_stdout(io.StringIO()):
            actual = rag.search(query, top_k=2)
        full_ms = (time.perf_counter_ns() - t0) / 1_000_000

        ids_actual = [str(item.get("id", "")) for item in actual]
        exact_ids = [str(item.get("id", "")) for item in exact]
        lexical_ids = [str(item.get("id", "")) for item in lexical]
        if exact_ids:
            stage = "exact"
        elif lexical_ids:
            stage = "lexical"
        else:
            stage = "vector" if semantic_available else "tier3_jaccard_fallback"
        relevant = {expected} if expected else set()
        hit = bool(relevant.intersection(ids_actual))
        top1 = bool(expected and ids_actual and ids_actual[0] == expected)
        if expected is None:
            outcome = "correct_abstention" if not ids_actual else "false_positive"
        elif not ids_actual:
            outcome = "no_result"
        elif top1:
            outcome = "correct_top1"
        elif hit:
            outcome = "relevant_below_top1"
        else:
            outcome = "incorrect_retrieval"
        rows.append({
            "query_id": query_id,
            "query": query,
            "expected": expected or "NONE",
            "exact_ids": ",".join(exact_ids) or "NONE",
            "lexical_ids": ",".join(lexical_ids) or "NONE",
            "actual": ",".join(ids_actual) or "NONE",
            "stage": stage,
            "outcome": outcome,
            "exact_ms": exact_ms,
            "lexical_ms": lexical_ms,
            "full_ms": full_ms,
            "rationale": rationale,
        })

    positives = [row for row in rows if row["expected"] != "NONE"]
    negatives = [row for row in rows if row["expected"] == "NONE"]
    relevant_returned = sum(
        1 for row in rows if row["expected"] != "NONE" and row["expected"] in row["actual"].split(",")
    )
    returned_count = sum(len(row["actual"].split(",")) for row in rows if row["actual"] != "NONE")
    precision = relevant_returned / returned_count if returned_count else 0.0
    recall = relevant_returned / len(positives) if positives else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    top1 = sum(row["outcome"] == "correct_top1" for row in positives) / len(positives)
    exact_recall = sum(
        row["expected"] in row["exact_ids"].split(",") for row in positives
    ) / len(positives)
    lexical_recall = sum(
        row["expected"] in row["lexical_ids"].split(",") for row in positives
    ) / len(positives)

    print(json.dumps({
        "corpus_records": len(corpus),
        "cache_hash_matches": True,
        "cache_shape": list(vectors.shape),
        "cache_dtype": str(vectors.dtype),
        "sentence_transformers_available": semantic_available,
        "semantic_vector_queries_executed": False,
        "positive_queries": len(positives),
        "negative_queries": len(negatives),
        "correct_relevant_retrievals": relevant_returned,
        "false_positives": sum(row["outcome"] == "false_positive" for row in rows),
        "no_result_positive": sum(row["outcome"] == "no_result" for row in rows),
        "incorrect_positive_retrievals": sum(row["outcome"] in {"incorrect_retrieval", "relevant_below_top1"} for row in positives),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "top1_accuracy_positive": top1,
        "exact_layer_positive_recall": exact_recall,
        "lexical_layer_positive_recall": lexical_recall,
        "exact_layer_metrics": retrieval_metrics(rows, "exact_ids", len(positives)),
        "lexical_layer_metrics": retrieval_metrics(rows, "lexical_ids", len(positives)),
        "full_cascade_metrics": retrieval_metrics(rows, "actual", len(positives)),
        "full_search_ms_mean": statistics.mean(row["full_ms"] for row in rows),
        "full_search_ms_median": statistics.median(row["full_ms"] for row in rows),
        "full_search_ms_p95": percentile([row["full_ms"] for row in rows], 95),
        "exact_layer_ms_mean": statistics.mean(row["exact_ms"] for row in rows),
        "exact_layer_ms_median": statistics.median(row["exact_ms"] for row in rows),
        "lexical_layer_ms_mean": statistics.mean(row["lexical_ms"] for row in rows),
        "lexical_layer_ms_median": statistics.median(row["lexical_ms"] for row in rows),
        "rows": rows,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
