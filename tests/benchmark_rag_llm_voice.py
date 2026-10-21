"""Benchmark RAG, grounded LLM responses, and voice-turn latency.

From repository root: python tests/benchmark_rag_llm_voice.py [--skip-llm]
TTS is measured with a mock text segmenter; it does not synthesize audio.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from server.llm import rag_engine  # noqa: E402


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    query: str
    expected_id: str | None
    kind: str = "corpus"  # corpus, negative, realtime


def cases() -> list[Case]:
    # Recreate the legacy audit composition: 20 positives + 15 non-corpus cases.
    rows = [
        ("A01", "A", "Nói gì trước khi ăn cơm?", "manner_itadakimasu", "corpus"),
        ("A02", "A", "Ăn xong bằng tiếng Nhật nói gì?", "manner_gochisousama", "corpus"),
        ("A03", "A", "Xin lỗi tiếng Nhật là gì?", "manner_gomennasai", "corpus"),
        ("A04", "A", "Chào người vừa về nhà bằng tiếng Nhật thế nào?", "manner_okaeri", "corpus"),
        ("A05", "A", "Từ tiếng Nhật của ngôi nhà?", "obj_house", "corpus"),
        ("A06", "A", "Mì ramen viết bằng tiếng Nhật sao?", "dish_ramen", "corpus"),
        ("A07", "A", "Kem tiếng Nhật gọi là gì?", "dish_icecream", "corpus"),
        ("A08", "A", "Gấu trúc tiếng Nhật là từ gì?", "animal_panda", "corpus"),
        ("A09", "A", "Quả chuối tiếng Nhật gọi thế nào?", "fruit_banana", "corpus"),
        ("A10", "A", "Bố tiếng Nhật là gì?", "family_father", "corpus"),
        ("A11", "A", "Mẹ trong tiếng Nhật gọi sao?", "family_mother", "corpus"),
        ("A12", "A", "Môn mỹ thuật tiếng Nhật nói thế nào?", "subj_art", "corpus"),
        ("A13", "A", "Môn thể dục tiếng Nhật là gì?", "subj_pe_football", "corpus"),
        ("A14", "A", "Cặp sách nói tiếng Nhật thế nào?", "obj_backpack", "corpus"),
        ("A15", "A", "Con vật có cái vòi dài là con gì?", "animal_elephant", "corpus"),
        ("A16", "A", "Con mèo tiếng Nhật là gì?", "animal_cat", "corpus"),
        ("A17", "A", "Chó tiếng Nhật là gì?", "animal_dog", "corpus"),
        ("B01", "B", "Nước ép trái cây trong tiếng Nhật là gì?", "dish_fruit_juice", "corpus"),
        ("B02", "B", "Về đến nhà thì nói câu nào?", "manner_tadaima", "corpus"),
        ("B03", "B", "Bạn ấy làm rất giỏi tiếng Nhật nói sao?", "feel_good_job", "corpus"),
        # Additional B regression cases (the first 20 positives above are the legacy set).
        ("B04", "B", "Về tới nhà mình nói gì bằng tiếng Nhật?", "manner_tadaima", "corpus"),
        ("B05", "B", "Khen bạn làm tốt lắm bằng tiếng Nhật nói sao?", "feel_good_job", "corpus"),
        ("B06", "B", "Chào người vừa về nhà tiếng Nhật là gì?", "manner_okaeri", "corpus"),
        ("B07", "B", "Từ tiếng Nhật của trái cây là gì?", None, "negative"),
        ("B08", "B", "Ngôi nhà tiếng Nhật viết bằng kanji thế nào?", "obj_house", "corpus"),
        ("B09", "B", "Bông hoa tiếng Nhật gọi là gì?", "nature_flower", "corpus"),
        ("B10", "B", "Cỏ tiếng Nhật nói sao?", "nature_grass", "corpus"),
        ("B11", "B", "Từ quả táo trong tiếng Nhật là gì?", "fruit_apple", "corpus"),
        ("C01", "C", "Thủ đô Nhật Bản là thành phố nào?", None, "negative"),
        ("C02", "C", "Ai là thủ tướng Nhật Bản?", None, "negative"),
        ("C03", "C", "Hôm nay thời tiết thế nào?", None, "negative"),
        ("C04", "C", "Tại sao bầu trời màu xanh?", None, "negative"),
        ("C05", "C", "Cách nấu mì ramen tại nhà?", None, "negative"),
        ("C06", "C", "Dạy mình ngữ pháp thể て tiếng Nhật.", None, "negative"),
        ("C07", "C", "Hôm nay ngày bao nhiêu?", None, "realtime"),
        ("C08", "C", "Số điện thoại cứu hỏa ở Nhật là gì?", None, "negative"),
        ("C09", "C", "Con voi sống được bao nhiêu năm?", None, "negative"),
        ("C10", "C", "Giá vé máy bay sang Tokyo bao nhiêu?", None, "negative"),
        ("C11", "C", "Cách viết email xin việc tiếng Nhật?", None, "negative"),
        ("C12", "C", "Nước Nhật có bao nhiêu tỉnh?", None, "negative"),
        ("C13", "C", "Ý nghĩa của từ samurai trong lịch sử?", None, "negative"),
        ("C14", "C", "Mình bị đau đầu uống thuốc gì?", None, "negative"),
        ("C15", "C", "Dự báo động đất ở Nhật tuần này?", None, "negative"),
        # Voice STT variants, added on top of the audit set.
        ("D01", "D", "À ừm cho hỏi, mì ramen tiếng Nhật nói sao?", "dish_ramen", "corpus"),
        ("D02", "D", "Mì ra men viết tiếng Nhật thế nào?", "dish_ramen", "corpus"),
        ("D03", "D", "Ờ cho mình hỏi về đến nhà thì nói câu nào?", "manner_tadaima", "corpus"),
        ("D04", "D", "Nước ep trai cay tiếng Nhật là gì?", "dish_fruit_juice", "corpus"),
        ("D05", "D", "Hôm nay ăn gì?", None, "negative"),
        ("D06", "D", "À ừm con voi tiếng Nhật gọi là gì?", "animal_elephant", "corpus"),
        ("D07", "D", "Ờm cứu hỏa ở Nhật gọi số mấy?", None, "negative"),
        ("D08", "D", "Mì ra men nấu ở nhà cần nguyên liệu gì?", None, "negative"),
    ]
    return [Case(*row) for row in rows]


def _fields(record: dict[str, Any]) -> dict[str, str]:
    content = record.get("content") or {}
    return {
        "ja_kana": str(record.get("ja_kana") or content.get("ja_kana") or "").strip(),
        "romaji": str(record.get("phonetic") or record.get("romaji") or content.get("phonetic") or "").strip(),
        "en": str(record.get("en") or content.get("en") or "").strip(),
    }


def _sentence_count(text: str) -> int:
    # Strip emoji before splitting: otherwise punctuation followed by an emoji
    # is incorrectly counted as a separate sentence (e.g. "Hi! 😊").
    clean = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", text or "").strip()
    return len([s for s in re.split(r"(?<=[.!?。！？])\s+|\n+", clean) if s.strip()]) if clean else 0


def _mock_tts(text: str) -> tuple[float, int]:
    start = time.perf_counter()
    segments = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s*", text) if s.strip()]
    _ = tuple(segments)
    return (time.perf_counter() - start) * 1000, len(segments)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def _stage(query: str, result: list[dict], rag) -> str:
    if rag_engine.is_out_of_scope_intent(query):
        return "Intent Filter"
    if not result:
        return "Semantic Gate / Reject"
    if rag._tier1_exact_filter(query):
        return "T1 Exact + Semantic Gate"
    if rag._tier2_lexical_filter(query):
        return "T2 Lexical + Semantic Gate"
    return "T3 Vector"


def _cosine(query: str, rag, result: list[dict]) -> float | None:
    ranked = rag._semantic_scores(query)
    if not ranked:
        return None
    if result:
        result_id = str(result[0].get("id", ""))
        return next((score for score, item in ranked if str(item.get("id", "")) == result_id), ranked[0][0])
    return ranked[0][0]


@contextlib.contextmanager
def _measure_stream(engine) -> Iterator[dict[str, Any]]:
    original = engine._stream_provider
    stats: dict[str, Any] = {"calls": 0, "ttft_ms": None, "total_ms": None, "started_at": None}

    def wrapped(*args, **kwargs):
        stats["calls"] += 1
        start = time.perf_counter()
        if stats["started_at"] is None:
            stats["started_at"] = start
        try:
            for chunk in original(*args, **kwargs):
                if stats["ttft_ms"] is None:
                    stats["ttft_ms"] = (time.perf_counter() - stats["started_at"]) * 1000
                yield chunk
        finally:
            stats["total_ms"] = (time.perf_counter() - stats["started_at"]) * 1000

    engine._stream_provider = wrapped
    try:
        yield stats
    finally:
        engine._stream_provider = original


def _run(case: Case, rag, engine, run_llm: bool) -> dict[str, Any]:
    e2e_start = time.perf_counter()
    rag.search.cache_clear()
    t0 = time.perf_counter()
    results = rag.search(case.query, top_k=1)
    rag_ms = (time.perf_counter() - t0) * 1000
    stage = _stage(case.query, results, rag)
    actual_id = str(results[0].get("id")) if results else None
    lesson = results[0] if results else None
    answer = ""
    stats: dict[str, Any] = {"calls": 0, "ttft_ms": 0, "total_ms": 0}
    llm_state = "skipped"
    if run_llm:
        benchmark_conversation = "benchmark-rag-llm-voice"
        original_grounded = engine.grounded_learning_answer
        engine.grounded_learning_answer = lambda _question, _record=None: None
        engine._semantic_cache.clear()
        engine.clear_history(conversation_id=benchmark_conversation)
        try:
            with _measure_stream(engine) as measured:
                answer = engine.chat(
                    case.query,
                    conversation_id=benchmark_conversation,
                    turn_id=uuid.uuid4().hex,
                )
                stats = dict(measured)
            llm_state = "called" if stats["calls"] else "fast path or circuit breaker"
        except Exception as exc:
            answer = f"[BENCHMARK LLM ERROR] {type(exc).__name__}: {exc}"
            llm_state = "error"
        finally:
            engine.grounded_learning_answer = original_grounded
            engine.clear_history(conversation_id=benchmark_conversation)
    llm_called = bool(stats["calls"])
    tts_ms, tts_segments = _mock_tts(answer)
    e2e_ms = (time.perf_counter() - e2e_start) * 1000
    # Cosine and stage attribution are diagnostic-only. Keep their extra model
    # encoding outside end-to-end latency so the metric reflects response time.
    cosine = _cosine(case.query, rag, results)

    grounded = None
    short = None
    if case.kind == "corpus" and lesson and answer and not answer.startswith("[BENCHMARK LLM ERROR]"):
        values = _fields(lesson)
        grounded = any(v.casefold() in answer.casefold() for v in values.values() if v)
        short = _sentence_count(answer) <= 3
    fallback_match = None
    if case.kind == "negative" and run_llm:
        fallback_match = answer.strip() == engine.HARDCODED_FALLBACK_MSG
    top1_only = len(results) <= 1
    rag_pass = (actual_id == case.expected_id and top1_only) if case.kind == "corpus" else actual_id is None
    return {
        "case_id": case.case_id, "group": case.group, "query": case.query, "kind": case.kind,
        "expected_id": case.expected_id, "actual_id": actual_id, "result_count": len(results),
        "top1_only_pass": top1_only, "rag_pass": rag_pass,
        "stage": stage, "cosine": cosine, "llm_called": llm_called, "llm_state": llm_state,
        "answer": answer, "grounding_pass": grounded, "max_3_sentences_pass": short,
        "fallback_match": fallback_match, "t_rag_ms": round(rag_ms, 3),
        "t_llm_ttft_ms": round(float(stats["ttft_ms"] or 0), 3),
        "t_llm_total_ms": round(float(stats["total_ms"] or 0), 3),
        "t_tts_ms": round(tts_ms, 3), "tts_mock_segments": tts_segments,
        "t_end_to_end_ms": round(e2e_ms, 3), "slow_warning": e2e_ms > 2000,
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [r for r in rows if r["kind"] in {"corpus", "negative", "realtime"}]
    pos = [r for r in evaluated if r["kind"] == "corpus"]
    # Realtime questions have no corpus record, so they count as RAG negatives;
    # their deterministic answer is exempt from the hardcoded RAG refusal check.
    neg = [r for r in evaluated if r["kind"] in {"negative", "realtime"}]
    tp = sum(r["actual_id"] == r["expected_id"] for r in pos)
    fn, fp = len(pos) - tp, sum(r["actual_id"] is not None for r in neg)
    tn = len(neg) - fp
    div = lambda a, b: a / b if b else None
    latency = {}
    for key in ("t_rag_ms", "t_llm_ttft_ms", "t_llm_total_ms", "t_tts_ms", "t_end_to_end_ms"):
        vals = [float(r[key]) for r in rows if float(r[key]) > 0]
        latency[key] = {"count": len(vals), "p50_ms": _percentile(vals, 50),
                        "p95_ms": _percentile(vals, 95), "max_ms": max(vals) if vals else None}
    return {
        "confusion_matrix": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
        "recall": div(tp, tp + fn), "specificity": div(tn, tn + fp),
        "precision": div(tp, tp + fp), "false_acceptance_rate": div(fp, len(neg)),
        "overall_accuracy": div(tp + tn, len(evaluated)),
        "counts": {"total_cases": len(rows), "positive": len(pos), "negative": len(neg),
                   "realtime_cases": sum(r["kind"] == "realtime" for r in rows)},
        "llm": {
            "positive_llm_called": sum(r["llm_called"] for r in pos),
            "grounding_pass": sum(r["grounding_pass"] is True for r in pos),
            "grounding_checked": sum(r["grounding_pass"] is not None for r in pos),
            "three_sentences_pass": sum(r["max_3_sentences_pass"] is True for r in pos),
            "fallback_pass": sum(r["fallback_match"] is True for r in rows if r["kind"] == "negative"),
            "fallback_checked": sum(r["fallback_match"] is not None for r in rows if r["kind"] == "negative"),
            "negative_llm_called": sum(r["llm_called"] for r in neg),
        },
        "latency": latency,
    }


def _warmup_ollama(engine) -> tuple[bool, str]:
    """Warm Ollama through the same prompt builder and streaming path as chat."""
    try:
        decision = engine.IntentDecision(
            engine.Intent.KNOWLEDGE_QNA, 1.0, True, "benchmark warm-up"
        )
        dummy_lesson = {
            "id": "benchmark_warmup",
            "title": "Warm-up lesson",
            "ja_kanji": "猫",
            "ja_kana": "ねこ",
            "phonetic": "neko",
            "en": "cat",
            "vi": "mèo",
            "example": "猫です。",
        }
        messages = engine._get_messages(
            "Warm up the lesson answer generator.", decision, dummy_lesson
        )
        chunks = engine._stream_provider(
            engine._client,
            engine._provider_name,
            engine._model_name,
            messages,
            max_tokens=5,
            temperature=0.0,
        )
        for _chunk in chunks:
            pass
        return True, "Ollama Qwen warmed through production prompt/stream path (excluded from case latency)"
    except Exception as exc:
        return False, f"Ollama warm-up failed: {type(exc).__name__}: {exc}"


def _failed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed = []
    for r in rows:
        bad = not r["rag_pass"]
        if r["kind"] == "corpus":
            bad |= r["grounding_pass"] is False or r["max_3_sentences_pass"] is False
        elif r["kind"] == "negative":
            bad |= r["llm_called"] or r["fallback_match"] is False
        if bad:
            failed.append(r)
    return failed


def _fmt(value: Any, digits: int = 1) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _markdown(report: dict[str, Any]) -> str:
    m, cm = report["metrics"], report["metrics"]["confusion_matrix"]
    lines = [
        "# RAG + LLM Voice Benchmark", "",
        f"- Generated: {report['generated_at']}", f"- LLM: {report['llm_mode']}",
        f"- TTS: {report['tts_mode']}", f"- Warm-up: {report['warmup_status']}",
        f"- RAG encoder warm-up: {report['rag_warmup_ms']:.1f} ms (excluded from case latency)",
        f"- Cases: {m['counts']['total_cases']} total; {m['counts']['positive']} corpus and {m['counts']['negative']} non-corpus (including {m['counts']['realtime_cases']} realtime) cases.",
        "", "> TTS is a mock text segmenter; it does not measure actual speech synthesis or playback.",
        "> The legacy audit composition is 20 in-corpus and 15 non-corpus cases. The realtime date case counts as RAG-negative but is excluded from exact hardcoded-fallback matching. Group D adds voice variants.", "",
        "## RAG confusion matrix and metrics", "",
        "| | Accepted | Rejected |", "|---|---:|---:|",
        f"| In corpus | TP {cm['TP']} | FN {cm['FN']} |",
        f"| Out of corpus | FP {cm['FP']} | TN {cm['TN']} |", "",
        "| Metric | Value |", "|---|---:|",
    ]
    for label, key in (("Recall", "recall"), ("Specificity", "specificity"), ("Precision", "precision"),
                       ("False acceptance rate", "false_acceptance_rate"), ("Overall accuracy", "overall_accuracy")):
        value = m[key]
        lines.append(f"| {label} | {_fmt(value * 100 if value is not None else None)}% |")
    lines.extend(["", "## LLM groundedness", "",
        f"- Grounding: {m['llm']['grounding_pass']}/{m['llm']['grounding_checked']} checked positive cases passed.",
        f"- At most 3 sentences: {m['llm']['three_sentences_pass']}/{m['llm']['grounding_checked']} checked positive cases passed.",
        f"- Negative cases that called LLM: {m['llm']['negative_llm_called']}.",
        f"- Exact fallback match: {m['llm']['fallback_pass']}/{m['llm']['fallback_checked']} checked negative cases.",
        "", "## Latency summary (ms)", "", "| Stage | N | P50 | P95 | Max |", "|---|---:|---:|---:|---:|"])
    for label, key in (("RAG", "t_rag_ms"), ("LLM TTFT", "t_llm_ttft_ms"),
                       ("LLM total", "t_llm_total_ms"), ("TTS mock", "t_tts_ms"),
                       ("End-to-end", "t_end_to_end_ms")):
        item = m["latency"][key]
        lines.append(f"| {label} | {item['count']} | {_fmt(item['p50_ms'])} | {_fmt(item['p95_ms'])} | {_fmt(item['max_ms'])} |")
    lines.extend(["", "## Failed cases", ""])
    failed = _failed(report["results"])
    if not failed:
        lines.append("No failed cases under the checks that were enabled.")
    else:
        lines.extend(["| ID | Group | Query | Expected → Actual | Retrieval stage | Cosine | Actual answer |", "|---|---|---|---|---|---:|---|"])
        for r in failed:
            query = r["query"].replace("|", "\\|")
            answer = (r["answer"] or "(no LLM call)").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {r['case_id']} | {r['group']} | {query} | {r['expected_id']} → {r['actual_id']} | {r['stage']} | {_fmt(r['cosine'], 4)} | {answer} |")
    lines.extend(["", "## Per-case results", "", "| ID | Group | Expected | Actual | RAG | Stage | Cosine | RAG ms | TTFT ms | LLM ms | E2E ms |", "|---|---|---|---|---|---|---:|---:|---:|---:|---:|"])
    for r in report["results"]:
        lines.append(f"| {r['case_id']} | {r['group']} | {r['expected_id']} | {r['actual_id']} | {'PASS' if r['rag_pass'] else 'FAIL'} | {r['stage']} | {_fmt(r['cosine'], 4)} | {r['t_rag_ms']:.1f} | {r['t_llm_ttft_ms']:.1f} | {r['t_llm_total_ms']:.1f} | {r['t_end_to_end_ms']:.1f} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-llm", action="store_true", help="Run only RAG retrieval checks.")
    parser.add_argument("--output-dir", type=Path, default=ROOT, help="Report output directory.")
    args = parser.parse_args()
    rag = rag_engine._get_rag()
    if not rag.knowledge_base:
        parser.error("RAG corpus failed to load; inspect data/data_v2.json and dependencies.")
    rag_warmup_start = time.perf_counter()
    if rag_engine._get_embedder() is None or not rag._semantic_scores("benchmark encoder warm-up"):
        parser.error("SentenceTransformer failed to initialize or encode; refusing to produce N/A cosine results.")
    rag_warmup_ms = round((time.perf_counter() - rag_warmup_start) * 1000.0, 3)

    engine = None
    llm_mode = "skipped by --skip-llm"
    warmup_status = "skipped"
    if not args.skip_llm:
        try:
            from server.llm import engine as engine_module
            name = str(engine_module._model_name or "").casefold()
            if (engine_module._provider_name == "ollama" and "qwen" in name and "2b" in name
                    and engine_module._client):
                engine, llm_mode = engine_module, f"Ollama/{engine_module._model_name}"
                _warmup_ok, warmup_status = _warmup_ollama(engine)
                print(f"[BENCHMARK] {warmup_status}")
            else:
                llm_mode = "unavailable: requires local Ollama Qwen 2B; no alternate provider called"
        except Exception as exc:
            llm_mode = f"unavailable: {type(exc).__name__}: {exc}"

    results = [_run(c, rag, engine, engine is not None) for c in cases()]
    report = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "llm_mode": llm_mode,
        "warmup_status": warmup_status,
        "rag_warmup_ms": rag_warmup_ms,
        "tts_mode": "mock text segmentation; no audio synthesis",
        "metrics": _metrics(results), "results": results,
    }
    markdown = _markdown(report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    md_path = args.output_dir / "BENCHMARK_REPORT.md"
    json_path = args.output_dir / "BENCHMARK_REPORT.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(markdown)
    print(f"\nWrote report: {md_path}\nWrote JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
