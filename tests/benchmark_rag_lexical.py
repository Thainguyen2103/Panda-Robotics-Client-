"""Offline microbenchmark for exact and lexical RAG tiers (no model/API calls)."""

import json
import sys
import statistics
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.llm.rag_engine import MoonRAG


CASES = {
    "exact_japanese": ("猫", "exact"),
    "lexical_unaccented_vi": ("chi cho be tu qua tao di", "lexical"),
    "lexical_phrase_vi": ("con mèo tiếng Nhật", "lexical"),
}


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main(samples=500):
    rag = MoonRAG()
    output = {"samples": samples, "unit": "ms", "cases": {}}
    for name, (query, tier) in CASES.items():
        run = rag._tier1_exact_filter(query) if tier == "exact" else rag._tier2_lexical_filter(query)
        if not run:
            raise RuntimeError(f"Benchmark query did not match expected tier: {name}")
        timings = []
        for _ in range(samples):
            started = time.perf_counter()
            if tier == "exact":
                rag._tier1_exact_filter(query)
            else:
                rag._tier2_lexical_filter(query)
            timings.append((time.perf_counter() - started) * 1000)
        output["cases"][name] = {
            "tier": tier,
            "matches": len(run),
            "min": round(min(timings), 4),
            "p50": round(statistics.median(timings), 4),
            "p95": round(percentile(timings, 0.95), 4),
            "max": round(max(timings), 4),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
