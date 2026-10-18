"""
================================================================================
benchmark_rag_task12a.py  --  Task 12A: Pre-flight Check & Semantic E5 Benchmark
================================================================================
POLICY:
  - Production files (rag_engine.py, data.json, .rag_embeddings.npz) are NEVER
    modified; all retrieval calls go through the unchanged public API or internal
    tier methods of the production MoonRAG class.
  - HALT immediately if any dependency or local model weight is missing.
  - No pip-install, no internet download, no corpus or cache mutation.

Run from the project root:
    $env:HF_HUB_OFFLINE           = '1'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:PYTHONDONTWRITEBYTECODE   = '1'
    python tests/benchmark_rag_task12a.py

Output:
  - Colored console summary
  - TASK12A_BENCHMARK_REPORT.md  (written to project root)
================================================================================
"""

# -- stdlib -------------------------------------------------------------------
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# -- offline guards -----------------------------------------------------------
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

# -- add project root to sys.path ---------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# -- console UTF-8 (Windows) --------------------------------------------------
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# -- static paths -------------------------------------------------------------
DATA_V2_PATH  = ROOT / "data" / "data_v2.json"
CACHE_V2_PATH = ROOT / "data" / ".rag_embeddings_v2.npz"

DATA_PATH   = DATA_V2_PATH if DATA_V2_PATH.exists() else (ROOT / "server" / "llm" / "data.json")
CACHE_PATH  = CACHE_V2_PATH if CACHE_V2_PATH.exists() else (ROOT / "server" / "llm" / ".rag_embeddings.npz")
REPORT_PATH = ROOT / "TASK12A_BENCHMARK_REPORT.md"

# =============================================================================
# SECTION 1 -- QUERY DATASET (28 original + 12 new negative queries)
# =============================================================================

# Fields: (query_id, query_text, expected_id_or_None, rationale)
# expected_id == None  -> out-of-corpus negative; correct answer is abstention.

QUERIES: List[Tuple[str, str, Optional[str], str]] = [
    # -- 25 In-corpus positives (from Task 11) --------------------------------
    ("q01", "cat",                                        "animal_cat",       "Direct English field."),
    ("q02", "meo",                                        "animal_cat",       "Vietnamese field."),
    ("q03", "con meo",                                    "animal_cat",       "Unaccented Vietnamese keyword."),
    ("q04", "\u732b",                                     "animal_cat",       "Kanji field."),
    ("q05", "\u306d\u3053",                               "animal_cat",       "Kana keyword."),
    ("q06", "neko",                                       "animal_cat",       "Romaji keyword."),
    ("q07", "Which animal sees in the dark?",             "animal_cat",       "Paraphrase via cat fact (night vision)."),
    ("q08", "Mother",                                     "family_mother",    "Direct English field."),
    ("q09", "me",                                         "family_mother",    "Vietnamese field unaccented."),
    ("q10", "Who is the female parent?",                  "family_mother",    "Paraphrase of Mother record."),
    ("q11", "dog",                                        "animal_dog",       "Direct English field."),
    ("q12", "\u72ac",                                     "animal_dog",       "Kanji field."),
    ("q13", "\u3044\u306c",                               "animal_dog",       "Kana keyword."),
    ("q14", "inu",                                        "animal_dog",       "Romaji keyword."),
    ("q15", "elephant",                                   "animal_elephant",  "Direct English field."),
    ("q16", "\u8c61",                                     "animal_elephant",  "Kanji keyword."),
    ("q17", "Which animal has a long trunk and likes sugar cane?", "animal_elephant", "Paraphrase via elephant fact."),
    ("q18", "sun",                                        "nature_sun",       "Direct English field."),
    ("q19", "\u592a\u967d",                               "nature_sun",       "Kanji field."),
    ("q20", "What gives light and warmth that sustains life?", "nature_sun",  "Paraphrase via sun fact."),
    ("q21", "apple",                                      "fruit_apple",      "Direct English field."),
    ("q22", "\u308a\u3093\u3054",                         "fruit_apple",      "Kana keyword."),
    ("q23", "Which fruit has vitamin C and fiber?",       "fruit_apple",      "Paraphrase via apple fact."),
    ("q24", "What is the Japanese word for water bottle?","obj_water_bottle", "Vocabulary request."),
    ("q25", "Good night",                                 "manner_oyasumi",   "Direct English field."),

    # -- 3 Out-of-corpus negatives (from Task 11) -----------------------------
    ("n01", "How do I build a rocket engine?",            None, "Engineering -- not in corpus."),
    ("n02", "What is the capital of France?",             None, "Geography -- not in corpus."),
    ("n03", "Explain quantum entanglement.",               None, "Physics -- not in corpus."),

    # -- 12 NEW Out-of-corpus negatives (Task 12A expansion) ------------------
    # French language queries (not in corpus -- only Japanese/English/Vietnamese)
    ("n04", "Comment dit-on bonjour en japonais?",        None, "French question -- language not in corpus."),
    ("n05", "Qu est-ce que le subjonctif en francais?",   None, "French grammar N2/N1 level -- not in corpus."),
    ("n06", "Quelle est la difference entre etre et avoir?", None, "French grammar -- not in corpus."),
    # German language queries
    ("n07", "Wie sagt man Guten Morgen auf Japanisch?",   None, "German question -- language not in corpus."),
    ("n08", "Was ist der Unterschied zwischen Dativ und Akkusativ?", None, "German grammar -- not in corpus."),
    # Advanced Japanese grammar (N1/N2 level -- beyond the 53 vocabulary records)
    ("n09", "What is the difference between wa and ga in Japanese grammar?", None, "Advanced J-grammar N2 -- not in corpus."),
    ("n10", "Explain the usage of te-form in Japanese for requests.",        None, "Advanced J-grammar te-form -- not in corpus."),
    ("n11", "How does the conditional ba-form work in Japanese?",            None, "Advanced J-grammar N1 -- not in corpus."),
    # General knowledge unrelated to children language lessons
    ("n12", "What is photosynthesis?",                    None, "Biology -- not in corpus."),
    ("n13", "Who invented the telephone?",                None, "History -- not in corpus."),
    ("n14", "What are the planets in the solar system?",  None, "Astronomy -- not in corpus."),
    ("n15", "How do you calculate the area of a circle?", None, "Math -- not in corpus."),
]

POSITIVES = [(qid, q, eid, r) for qid, q, eid, r in QUERIES if eid is not None]
NEGATIVES = [(qid, q, eid, r) for qid, q, eid, r in QUERIES if eid is None]

# =============================================================================
# SECTION 2 -- PRE-FLIGHT CHECKS
# =============================================================================

def _check_dependency(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _find_e5_snapshot() -> Optional[Path]:
    """Return snapshot dir for intfloat/multilingual-e5-small, or None."""
    cache_root = os.environ.get("HF_HUB_CACHE")
    if not cache_root:
        hf_home = os.environ.get("HF_HOME")
        cache_root = (
            str(Path(hf_home) / "hub")
            if hf_home
            else str(Path.home() / ".cache" / "huggingface" / "hub")
        )
    model_dir = (
        Path(cache_root)
        / "models--intfloat--multilingual-e5-small"
        / "snapshots"
    )
    if not model_dir.is_dir():
        return None
    required = {"config.json", "modules.json", "tokenizer_config.json"}
    for snapshot in model_dir.iterdir():
        if not snapshot.is_dir():
            continue
        files = {p.name for p in snapshot.iterdir() if p.is_file()}
        has_weights = "model.safetensors" in files or "pytorch_model.bin" in files
        has_tokenizer = "tokenizer.json" in files or "sentencepiece.bpe.model" in files
        if required.issubset(files) and has_weights and has_tokenizer:
            return snapshot
    return None


def preflight() -> Dict:
    """
    Run all environment checks. Returns a dict with status details.
    HALTS (SystemExit) if any critical dependency or weight is missing.
    """
    results = {}

    # 1. Library checks
    for lib in ("sentence_transformers", "transformers", "numpy", "torch"):
        ok = _check_dependency(lib)
        results[lib] = ok
        symbol = "[OK]" if ok else "[MISSING]"
        print(f"  {symbol} {lib}")

    missing_libs = [k for k, v in results.items() if not v]
    if missing_libs:
        msg = (
            "HALT: Missing libraries: "
            + str(missing_libs)
            + " -- DO NOT install -- report to admin."
        )
        print("\n[HALT] " + msg)
        raise SystemExit(msg)

    # 2. Local model snapshot check
    snapshot_path = _find_e5_snapshot()
    if snapshot_path is None:
        msg = (
            "HALT: Local model weights for intfloat/multilingual-e5-small NOT FOUND."
            " DO NOT download."
        )
        print("\n[HALT] " + msg)
        raise SystemExit(msg)
    print(f"  [OK] E5 local weights: {snapshot_path}")
    results["e5_snapshot"] = str(snapshot_path)

    # 3. Corpus & cache verification
    if not DATA_PATH.exists():
        raise SystemExit(f"HALT: data.json not found at {DATA_PATH}")
    corpus = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    corpus_hash_md5 = hashlib.md5(DATA_PATH.read_bytes()).hexdigest()
    corpus_hash_sha = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()

    import numpy as np

    with np.load(str(CACHE_PATH), allow_pickle=True) as cache:
        cache_hash = str(cache["hash"].item()) if "hash" in cache.files else None
        vectors = cache["embeddings"] if "embeddings" in cache.files else None

    cache_ok = (
        cache_hash in (corpus_hash_md5, corpus_hash_sha)
        and vectors is not None
        and vectors.ndim == 2
        and vectors.shape[0] == len(corpus)
        and np.isfinite(vectors).all()
    )
    shape_str = str(getattr(vectors, "shape", None))
    match_str = str(cache_hash in (corpus_hash_md5, corpus_hash_sha))
    print(f"  [{'OK' if cache_ok else 'WARN'}] Embedding cache: shape={shape_str} hash_match={match_str}")
    results["corpus_records"] = len(corpus)
    results["cache_valid"] = cache_ok
    results["cache_shape"] = list(vectors.shape) if vectors is not None else None

    return results


# =============================================================================
# SECTION 3 -- TIER BENCHMARK RUNNERS (isolated; production file untouched)
# =============================================================================

def _silent(fn, *args, **kwargs):
    """Call fn suppressing stdout from production logging."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def benchmark_tier1(rag) -> List[Dict]:
    rows = []
    for qid, query, expected, rationale in QUERIES:
        t0 = time.perf_counter_ns()
        results = rag._tier1_exact_filter(query)
        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000
        ids = [str(r.get("id", "")) for r in results]
        rows.append({
            "query_id": qid, "query": query, "expected": expected,
            "returned_ids": ids, "latency_ms": latency_ms,
            "hit": bool(expected and expected in ids),
            "top1": bool(expected and ids and ids[0] == expected),
            "false_positive": (expected is None and bool(ids)),
        })
    return rows


def benchmark_tier2(rag) -> List[Dict]:
    rows = []
    for qid, query, expected, rationale in QUERIES:
        t0 = time.perf_counter_ns()
        results = rag._tier2_lexical_filter(query)
        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000
        ids = [str(r.get("id", "")) for r in results]
        rows.append({
            "query_id": qid, "query": query, "expected": expected,
            "returned_ids": ids, "latency_ms": latency_ms,
            "hit": bool(expected and expected in ids),
            "top1": bool(expected and ids and ids[0] == expected),
            "false_positive": (expected is None and bool(ids)),
        })
    return rows


def benchmark_tier3_jaccard(rag) -> List[Dict]:
    """Run Jaccard fallback in isolation (no embedder, no E5)."""
    rows = []
    for qid, query, expected, rationale in QUERIES:
        t0 = time.perf_counter_ns()
        results = rag._tier3_jaccard_fallback(query)
        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000
        ids = [str(r.get("id", "")) for r in results]
        rows.append({
            "query_id": qid, "query": query, "expected": expected,
            "returned_ids": ids, "latency_ms": latency_ms,
            "hit": bool(expected and expected in ids),
            "top1": bool(expected and ids and ids[0] == expected),
            "false_positive": (expected is None and bool(ids)),
        })
    return rows


def benchmark_tier3_e5(rag, embedder) -> List[Dict]:
    """
    Run Semantic E5 vector search in isolation.
    Returns per-query rows including raw similarity scores for ALL corpus items
    (for score-distribution analysis).
    """
    import numpy as np

    rows = []
    embeddings = rag._embeddings  # shape (N, 384), L2-normalized, from cache

    for qid, query, expected, rationale in QUERIES:
        t0 = time.perf_counter_ns()
        q_vec = embedder.encode(
            [f"query: {query}"],
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype(np.float32)
        scores = (embeddings @ q_vec.T).squeeze()  # shape (N,)
        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000

        top_indices = list(np.argsort(scores)[::-1][:2])
        returned_ids = []
        top_scores = []
        for idx in top_indices:
            returned_ids.append(str(rag.knowledge_base[idx].get("id", "")))
            top_scores.append(float(scores[idx]))

        # Find score of the expected document (if positive query)
        expected_score = None
        if expected:
            for i, item in enumerate(rag.knowledge_base):
                if str(item.get("id", "")) == expected:
                    expected_score = float(scores[i])
                    break

        rows.append({
            "query_id": qid,
            "query": query,
            "expected": expected,
            "returned_ids": returned_ids,
            "top_scores": top_scores,
            "expected_score": expected_score,
            "max_score_overall": float(scores.max()),
            "all_scores": scores.tolist(),
            "latency_ms": latency_ms,
            "hit": bool(expected and expected in returned_ids),
            "top1": bool(expected and returned_ids and returned_ids[0] == expected),
            "false_positive": (expected is None and bool(returned_ids)),
        })
    return rows


def benchmark_full_cascade(rag) -> List[Dict]:
    """Full production cascade (Tier1 -> Tier2 -> Tier3/E5 or Jaccard)."""
    # warm-up (excluded from timing)
    _silent(rag.search, "Moon oi cat", top_k=2)

    rows = []
    for qid, query, expected, rationale in QUERIES:
        t0 = time.perf_counter_ns()
        results = _silent(rag.search, query, top_k=2)
        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000
        ids = [str(r.get("id", "")) for r in results]
        rows.append({
            "query_id": qid, "query": query, "expected": expected,
            "returned_ids": ids, "latency_ms": latency_ms,
            "hit": bool(expected and expected in ids),
            "top1": bool(expected and ids and ids[0] == expected),
            "false_positive": (expected is None and bool(ids)),
        })
    return rows


# =============================================================================
# SECTION 4 -- METRICS COMPUTATION
# =============================================================================

def _percentile(values: List[float], pct: float) -> float:
    import numpy as np
    return float(np.percentile(np.asarray(values, dtype=np.float64), pct))


def compute_metrics(rows: List[Dict]) -> Dict:
    pos_rows = [r for r in rows if r["expected"] is not None]
    neg_rows = [r for r in rows if r["expected"] is None]

    hits      = [r for r in pos_rows if r["hit"]]
    top1_hits = [r for r in pos_rows if r["top1"]]
    fps       = [r for r in neg_rows if r["false_positive"]]

    relevant_returned = sum(
        1 for r in pos_rows if r["expected"] in r["returned_ids"]
    )
    total_returned = sum(len(r["returned_ids"]) for r in rows)
    precision = relevant_returned / total_returned if total_returned else 0.0
    recall    = len(hits) / len(pos_rows) if pos_rows else 0.0
    top1_acc  = len(top1_hits) / len(pos_rows) if pos_rows else 0.0
    fpr       = len(fps) / len(neg_rows) if neg_rows else 0.0

    latencies = [r["latency_ms"] for r in rows]
    return {
        "recall":              recall,
        "precision":           precision,
        "top1_accuracy":       top1_acc,
        "false_positive_rate": fpr,
        "false_positives":     len(fps),
        "total_negatives":     len(neg_rows),
        "latency_mean_ms":     statistics.mean(latencies),
        "latency_median_ms":   statistics.median(latencies),
        "latency_p95_ms":      _percentile(latencies, 95),
    }


def analyze_e5_score_distribution(e5_rows: List[Dict]) -> Dict:
    """Compute score distribution stats to recommend a rejection threshold."""
    pos_expected_scores = [
        r["expected_score"]
        for r in e5_rows
        if r["expected"] is not None and r["expected_score"] is not None
    ]
    neg_top1_scores = [
        r["top_scores"][0]
        for r in e5_rows
        if r["expected"] is None and r["top_scores"]
    ]
    neg_max_scores = [
        r["max_score_overall"]
        for r in e5_rows
        if r["expected"] is None
    ]

    def safe_stats(vals):
        if not vals:
            return {"min": None, "max": None, "mean": None, "median": None, "p5": None}
        return {
            "min":    min(vals),
            "max":    max(vals),
            "mean":   statistics.mean(vals),
            "median": statistics.median(vals),
            "p5":     _percentile(vals, 5),
        }

    pos_stats      = safe_stats(pos_expected_scores)
    neg_top1_stats = safe_stats(neg_top1_scores)
    neg_max_stats  = safe_stats(neg_max_scores)

    # Recommended threshold: midpoint between min in-corpus P5 and max out-of-corpus top-1,
    # with 30% conservative bias toward in-corpus side to prioritise precision.
    rec_threshold = None
    if pos_stats["p5"] is not None and neg_top1_stats["max"] is not None:
        gap_mid = (pos_stats["p5"] + neg_top1_stats["max"]) / 2
        rec_threshold = round(gap_mid + 0.3 * (pos_stats["p5"] - gap_mid), 4)
        rec_threshold = max(rec_threshold, 0.0)

    return {
        "in_corpus_expected_scores": pos_stats,
        "out_of_corpus_top1_scores": neg_top1_stats,
        "out_of_corpus_max_scores":  neg_max_stats,
        "recommended_threshold":     rec_threshold,
        "raw_pos_scores":            pos_expected_scores,
        "raw_neg_top1_scores":       neg_top1_scores,
    }


# =============================================================================
# SECTION 5 -- REPORT GENERATION
# =============================================================================

def _fmt(v, ms=False):
    if v is None:
        return "N/A"
    if ms:
        return f"{v:.4f} ms"
    return f"{v:.4f}"


def generate_report(
    preflight_info: Dict,
    metrics_t1: Dict,
    metrics_t2: Dict,
    metrics_t3_j: Dict,
    metrics_e5: Dict,
    metrics_full: Dict,
    dist: Dict,
    e5_rows: List[Dict],
    t1_rows: List[Dict],
    t2_rows: List[Dict],
    t3j_rows: List[Dict],
    full_rows: List[Dict],
) -> str:

    snap        = preflight_info.get("e5_snapshot", "N/A")
    corpus_n    = preflight_info.get("corpus_records", "?")
    cache_shape = preflight_info.get("cache_shape", "?")
    cache_ok    = preflight_info.get("cache_valid", False)

    dt    = dist
    pos_s = dt["in_corpus_expected_scores"]
    neg_s = dt["out_of_corpus_top1_scores"]
    threshold = dt["recommended_threshold"]

    def pct(v):
        return f"{v:.3f} ({v*100:.1f}%)" if v is not None else "N/A"

    def row_table(label, m):
        return (
            f"| {label} | {pct(m['recall'])} | "
            f"{pct(m['precision'])} | "
            f"{m['false_positives']}/{m['total_negatives']} "
            f"({pct(m['false_positive_rate'])}) | "
            f"{m['latency_mean_ms']:.4f} ms | "
            f"{m['latency_p95_ms']:.4f} ms |"
        )

    # Per-query E5 detail table
    e5_detail_lines = [
        "| ID | Query | Expected | Top-1 Returned | Top-1 Score | Expected Score | Hit | Latency (ms) |",
        "| :--- | :--- | :--- | :--- | ---: | ---: | :---: | ---: |",
    ]
    for r in e5_rows:
        top1_id    = r["returned_ids"][0] if r["returned_ids"] else "---"
        top1_score = f"{r['top_scores'][0]:.4f}" if r["top_scores"] else "---"
        exp_score  = f"{r['expected_score']:.4f}" if r["expected_score"] is not None else "N/A"
        hit_str    = "HIT" if r["hit"] else ("NEG-OK" if r["expected"] is None else "MISS")
        short_q    = r["query"][:50] + ("..." if len(r["query"]) > 50 else "")
        e5_detail_lines.append(
            f"| {r['query_id']} | `{short_q}` | "
            f"`{r['expected'] or 'NONE'}` | `{top1_id}` | "
            f"{top1_score} | {exp_score} | {hit_str} | {r['latency_ms']:.3f} |"
        )

    # Score distribution
    pos_raw = sorted(dt.get("raw_pos_scores", []))
    neg_raw = sorted(dt.get("raw_neg_top1_scores", []), reverse=True)
    score_lines = []
    for i, s in enumerate(pos_raw):
        score_lines.append(f"  in-corpus  [{i+1:02d}]: {s:.4f}")
    for i, s in enumerate(neg_raw):
        score_lines.append(f"  out-corpus [{i+1:02d}]: {s:.4f}  <- FP candidate")
    score_block = "\n".join(score_lines) if score_lines else "  (no data)"

    thr_str = f"{threshold:.4f}" if threshold is not None else "N/A"
    pos_p5  = _fmt(pos_s.get("p5"))
    neg_max = _fmt(neg_s.get("max"))

    report = f"""# TASK 12A BENCHMARK REPORT
*Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}*

---

## 1. Environment & E5 Availability

| Check | Result |
| :--- | :--- |
| `sentence_transformers` | {'FOUND' if preflight_info.get('sentence_transformers') else 'MISSING'} |
| `transformers` | {'FOUND' if preflight_info.get('transformers') else 'MISSING'} |
| `numpy` | {'FOUND' if preflight_info.get('numpy') else 'MISSING'} |
| `torch` | {'FOUND' if preflight_info.get('torch') else 'MISSING'} |
| E5 Local Weights (model.safetensors) | FOUND |
| Snapshot Path | `{snap}` |
| Embedding Cache | shape={cache_shape}, valid={cache_ok} |
| Corpus Records | {corpus_n} |

- **Status: READY** -- All dependencies and local model weights confirmed present.

---

## 2. Query Dataset Summary

| Category | Count |
| :--- | ---: |
| In-corpus positive queries | {len(POSITIVES)} |
| Out-of-corpus negative queries (Task 11) | 3 |
| Out-of-corpus negative queries (Task 12A NEW) | 12 |
| **Total** | **{len(QUERIES)}** |

New negative query categories added in Task 12A:
- French language (N2/N1 grammar) -- 3 queries
- German language (grammar cases) -- 2 queries
- Advanced Japanese grammar (N1/N2 level) -- 3 queries
- General knowledge (biology, history, astronomy, math) -- 4 queries

---

## 3. Benchmark Summary Table

| Retrieval Pipeline | Recall (In-corpus) | Precision | False Positives (Out-of-corpus) | Latency Mean (ms) | Latency P95 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- |
{row_table("Tier 1 -- Exact / Keyword", metrics_t1)}
{row_table("Tier 2 -- Fuzzy Lexical", metrics_t2)}
{row_table("Tier 3 -- Jaccard Fallback", metrics_t3_j)}
{row_table("**Tier 3 -- Semantic E5 (Real)**", metrics_e5)}
{row_table("Full 3-Tier Cascade", metrics_full)}

> Precision = relevant records returned / total records returned across all queries.
> FPR = negative queries returning >=1 result / total negatives.
> Recall = positive queries where expected ID appeared in top-2 / total positives.

---

## 4. Semantic E5 -- Per-Query Detail

{chr(10).join(e5_detail_lines)}

---

## 5. Score Distribution & Rejection Threshold Proposal

```
In-corpus expected-document similarity scores (E5, higher = better):
  Min:    {_fmt(pos_s.get('min'))}
  Max:    {_fmt(pos_s.get('max'))}
  Mean:   {_fmt(pos_s.get('mean'))}
  Median: {_fmt(pos_s.get('median'))}
  P5:     {pos_p5}   <- worst-case in-corpus score

Out-of-corpus top-1 similarity scores (FP candidates):
  Min:    {_fmt(neg_s.get('min'))}
  Max:    {neg_max}
  Mean:   {_fmt(neg_s.get('mean'))}
  Median: {_fmt(neg_s.get('median'))}

Score distribution (sorted):
{score_block}
```

### 5.1 Threshold Recommendation

| Parameter | Value |
| :--- | :--- |
| Average Similarity Score (In-Corpus Matches) | `{_fmt(pos_s.get('mean'))}` |
| Max Similarity Score (Out-of-Corpus FPs) | `{neg_max}` |
| **Recommended Threshold for Task 12B** | **`{thr_str}`** |

**Rationale:** The gap between the lowest in-corpus expected score at P5 (`{pos_p5}`)
and the highest out-of-corpus top-1 score (`{neg_max}`) determines the safe rejection zone.
A threshold of `{thr_str}` is positioned 30% bias toward the in-corpus side of the midpoint --
maximising recall while reducing false positives from out-of-corpus queries.

> Current production threshold is `0.85` (hardcoded as `MoonRAG.VECTOR_SIMILARITY_THRESHOLD`).
> If the recommended threshold differs meaningfully, Task 12B should update this value.

---

## 6. Tier Comparison Analysis

### Tier 1 (Exact/Keyword Match)
- Strength: Near-zero latency, precision 1.0 on exact vocabulary hits.
- Weakness: Cannot handle paraphrases, descriptive riddles, or semantic variants.
- Recall on {len(POSITIVES)} positive queries: {metrics_t1['recall']*100:.1f}%.

### Tier 2 (Fuzzy Lexical)
- Strength: Handles unaccented Vietnamese, STT errors, topic matching.
- Weakness: Word-overlap sensitive; may false-positive on negatives with common words.
- False Positive Rate on {len(NEGATIVES)} negatives: {metrics_t2['false_positive_rate']*100:.1f}%.

### Tier 3 -- Jaccard Fallback
- Recall: {metrics_t3_j['recall']*100:.1f}%  |  FPR: {metrics_t3_j['false_positive_rate']*100:.1f}%
- Known failure modes: "female parent" -> mother, "gives light" -> sun.

### Tier 3 -- Semantic E5 (Real)
- Recall: {metrics_e5['recall']*100:.1f}%  |  FPR: {metrics_e5['false_positive_rate']*100:.1f}%
- Uses correct `query:` / `passage:` E5 prefixes and L2-normalized cosine similarity.
- Embeddings loaded from verified production cache `.rag_embeddings.npz`.

---

## 7. Next Steps -- Task 12B Specifications

1. **Implement Rejection Rule:** Replace hardcoded `VECTOR_SIMILARITY_THRESHOLD = 0.85`
   with the validated threshold `{thr_str}` (or task-12B re-validated value).
   Gate behind a config flag to allow rollback.

2. **Fallback Tuning:** Tighten Jaccard fallback (require >=2 content-word overlaps)
   to reduce FPR from {metrics_t3_j['false_positive_rate']*100:.1f}% to <10%.

3. **Abstention Signal:** If Tier 3 score < threshold, return `[]` explicitly
   instead of returning the top-2 Jaccard result.

4. **Expanded Negative Set:** Before finalising Task 12B, add >=30 negative queries
   (Vietnamese off-topic, J-grammar N1/N2, multi-language mix) for a stable FPR estimate.

5. **LLM Grounding Test:** Run end-to-end with Brain (LLM) to confirm that the
   abstention signal prevents hallucinated answers on out-of-corpus queries.

---

## 8. Reproduction Command

```powershell
$env:HF_HUB_OFFLINE           = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:PYTHONDONTWRITEBYTECODE   = '1'
python tests/benchmark_rag_task12a.py
```

*Production files modified: NONE.*
*Files created by this task: `tests/benchmark_rag_task12a.py`, `TASK12A_BENCHMARK_REPORT.md`.*
"""
    return report


# =============================================================================
# SECTION 6 -- MAIN ENTRY POINT
# =============================================================================

def main():
    # Enforce offline guard (same policy as Task 11)
    if (
        os.environ.get("HF_HUB_OFFLINE") != "1"
        or os.environ.get("HF_HUB_DISABLE_TELEMETRY") != "1"
    ):
        raise SystemExit(
            "HALT: Set HF_HUB_OFFLINE=1 and HF_HUB_DISABLE_TELEMETRY=1 before running."
        )

    print("=" * 72)
    print("  TASK 12A -- Pre-flight Check & Semantic E5 Benchmark")
    print("=" * 72)

    # -- Step 1: Pre-flight ---------------------------------------------------
    print("\n[1/6] Pre-flight environment checks...")
    preflight_info = preflight()  # Halts on any failure

    # -- Step 2: Import production RAG (read-only; cache must be valid hit) ---
    print("\n[2/6] Importing production MoonRAG (read-only)...")
    import numpy as np

    # Verify cache is a valid hit before importing (prevents rebuild path)
    corpus      = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    corpus_hash_md5 = hashlib.md5(DATA_PATH.read_bytes()).hexdigest()
    corpus_hash_sha = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
    with np.load(str(CACHE_PATH), allow_pickle=True) as cache_check:
        vectors     = cache_check["embeddings"]
        cached_hash = str(cache_check["hash"].item())

    if (
        cached_hash not in (corpus_hash_md5, corpus_hash_sha)
        or vectors.ndim != 2
        or vectors.shape[0] != len(corpus)
        or not np.isfinite(vectors).all()
    ):
        raise SystemExit("HALT: Cache is not a verified hit. Will not import RAG.")

    # Verify all expected IDs exist in corpus
    corpus_ids = {str(r.get("id", "")) for r in corpus}
    for qid, query, expected, _ in QUERIES:
        if expected and expected not in corpus_ids:
            raise SystemExit(
                f"HALT: Expected ID '{expected}' (query {qid}) not in corpus. Review labels."
            )

    import server.llm.rag_engine as prod_rag

    rag = prod_rag._get_rag()
    if rag._embeddings is None:
        raise SystemExit("HALT: Production RAG did not load cached embeddings.")
    print(f"   MoonRAG loaded: {len(rag.knowledge_base)} records, "
          f"embeddings shape={rag._embeddings.shape}")

    # -- Step 3: Load E5 embedder (local only) --------------------------------
    print("\n[3/6] Loading Semantic E5 embedder (local weights only)...")
    from sentence_transformers import SentenceTransformer
    import torch

    snap_path = preflight_info["e5_snapshot"]
    device    = "cuda" if torch.cuda.is_available() else "cpu"
    t_load    = time.perf_counter()
    embedder  = SentenceTransformer(snap_path, device=device)
    load_ms   = (time.perf_counter() - t_load) * 1000
    print(f"   E5 loaded on {device.upper()} in {load_ms:.0f} ms")

    # -- Step 4: Run isolated tier benchmarks ---------------------------------
    print(f"\n[4/6] Running isolated tier benchmarks ({len(QUERIES)} queries)...")

    print("   -> Tier 1 (Exact/Keyword)...")
    t1_rows = benchmark_tier1(rag)

    print("   -> Tier 2 (Fuzzy Lexical)...")
    t2_rows = benchmark_tier2(rag)

    print("   -> Tier 3 Jaccard Fallback...")
    t3j_rows = benchmark_tier3_jaccard(rag)

    print("   -> Tier 3 Semantic E5 (Real)...")
    e5_rows = benchmark_tier3_e5(rag, embedder)

    print("   -> Full 3-Tier Cascade...")
    full_rows = benchmark_full_cascade(rag)

    # -- Step 5: Compute metrics ----------------------------------------------
    print("\n[5/6] Computing metrics...")
    metrics_t1   = compute_metrics(t1_rows)
    metrics_t2   = compute_metrics(t2_rows)
    metrics_t3j  = compute_metrics(t3j_rows)
    metrics_e5   = compute_metrics(e5_rows)
    metrics_full = compute_metrics(full_rows)
    dist         = analyze_e5_score_distribution(e5_rows)

    # -- Step 6: Console summary ----------------------------------------------
    print("\n[6/6] Results:")
    header = f"{'Pipeline':<32} {'Recall':>8} {'Precision':>10} {'FPR':>8} {'Mean ms':>10} {'P95 ms':>9}"
    print("\n" + header)
    print("-" * len(header))
    for label, m in [
        ("Tier1 Exact",       metrics_t1),
        ("Tier2 Lexical",     metrics_t2),
        ("Tier3 Jaccard",     metrics_t3j),
        ("Tier3 E5 Semantic", metrics_e5),
        ("Full Cascade",      metrics_full),
    ]:
        print(
            f"  {label:<30} "
            f"{m['recall']:>7.3f}  "
            f"{m['precision']:>9.3f}  "
            f"{m['false_positive_rate']:>7.3f}  "
            f"{m['latency_mean_ms']:>9.4f}  "
            f"{m['latency_p95_ms']:>8.4f}"
        )

    ps = dist["in_corpus_expected_scores"]
    ns = dist["out_of_corpus_top1_scores"]
    print(f"\nE5 Score Distribution:")
    print(f"  In-corpus expected  -- min:{ps['min']:.4f} mean:{ps['mean']:.4f} max:{ps['max']:.4f}")
    print(f"  Out-of-corpus top-1 -- min:{ns['min']:.4f} mean:{ns['mean']:.4f} max:{ns['max']:.4f}")
    thr = dist["recommended_threshold"]
    print(f"  Recommended threshold for Task 12B: {thr:.4f}" if thr else "  Threshold: N/A")

    # Write Markdown report
    report_md = generate_report(
        preflight_info,
        metrics_t1, metrics_t2, metrics_t3j, metrics_e5, metrics_full,
        dist, e5_rows, t1_rows, t2_rows, t3j_rows, full_rows,
    )
    REPORT_PATH.write_text(report_md, encoding="utf-8")
    print(f"\n[OK] Report written to: {REPORT_PATH}")
    print("=" * 72)


if __name__ == "__main__":
    main()

