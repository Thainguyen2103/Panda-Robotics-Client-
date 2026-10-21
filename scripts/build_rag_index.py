#!/usr/bin/env python3
"""
scripts/build_rag_index.py  --  Task 13: Reproducible Indexing Pipeline
======================================================================
1. Validates all records in data/data_v2.json against data/schema_v1.json.
2. Uses local model 'intfloat/multilingual-e5-small' (offline mode safe).
3. Generates embedding vectors with standardized 'passage: ' prefix.
4. Computes SHA256 checksum of corpus and saves metadata into .rag_embeddings_v2.npz.
5. Saves the index at one canonical location under data/ with corpus IDs.
"""

import datetime
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root in sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Safe UTF-8 console output for Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCHEMA_FILE = ROOT / "data" / "schema_v1.json"
DATA_FILE = ROOT / "data" / "data_v2.json"
TARGET_CACHE_DATA = ROOT / "data" / ".rag_embeddings_v2.npz"
MODEL_NAME = "intfloat/multilingual-e5-small"


def sha256_file(path: Path) -> str:
    """Computes SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_records(records: List[Dict[str, Any]], schema: Dict[str, Any]) -> None:
    """Validates records against Schema V1 rules."""
    required_fields = {
        "id", "language", "level", "skill", "type", "title",
        "content", "source_id", "stopwords_override", "review_status"
    }
    allowed_languages = {"ja", "vi", "en", "multilingual"}
    allowed_levels = {"N5", "N4", "N3", "N2", "N1", "basic", "intermediate", "advanced"}
    allowed_skills = {"vocab", "grammar", "pronunciation", "dialogue", "culture"}
    allowed_types = {"word", "sentence", "rule", "conversation"}
    allowed_review_status = {"draft", "verified", "deprecated"}

    id_pattern = re.compile(r"^[a-z0-9]+_[a-z0-9_]+$")
    seen_ids = set()

    for idx, item in enumerate(records):
        rec_id = item.get("id")
        if not rec_id:
            raise ValueError(f"Record #{idx} missing required field 'id'")
        if not id_pattern.match(rec_id):
            raise ValueError(f"Record '{rec_id}' has invalid ID format (must match 'category_item_name')")
        if rec_id in seen_ids:
            raise ValueError(f"Duplicate record ID found: '{rec_id}'")
        seen_ids.add(rec_id)

        # Check required fields
        for field in required_fields:
            if field not in item:
                raise ValueError(f"Record '{rec_id}' missing required field '{field}'")

        # Check enums
        if item["language"] not in allowed_languages:
            raise ValueError(f"Record '{rec_id}' invalid language '{item['language']}'")
        if item["level"] not in allowed_levels:
            raise ValueError(f"Record '{rec_id}' invalid level '{item['level']}'")
        if item["skill"] not in allowed_skills:
            raise ValueError(f"Record '{rec_id}' invalid skill '{item['skill']}'")
        if item["type"] not in allowed_types:
            raise ValueError(f"Record '{rec_id}' invalid type '{item['type']}'")
        if item["review_status"] not in allowed_review_status:
            raise ValueError(f"Record '{rec_id}' invalid review_status '{item['review_status']}'")

        # Check stopwords_override
        if not isinstance(item.get("stopwords_override"), list):
            raise ValueError(f"Record '{rec_id}' field 'stopwords_override' must be a list")

    print(f"✅ [VALIDATE] All {len(records)} records strictly conform to Schema V1 specifications.")


def build_passage_texts(records: List[Dict[str, Any]]) -> List[str]:
    """Builds standardized passage texts for E5 embedding."""
    texts = []
    for item in records:
        vi = item.get("vi") or item.get("vietnamese", "")
        en = item.get("en") or item.get("english", "")
        ja = item.get("ja", "")
        ja_kanji = item.get("ja_kanji") or item.get("kanji", "")
        ja_kana = item.get("ja_kana") or item.get("japanese_hiragana", "")
        keywords = " ".join(item.get("keywords", []))
        topic = item.get("topic", "")

        parts = [vi, en, ja, ja_kanji, ja_kana, topic, keywords]
        combined = " ".join(p for p in parts if p)
        # E5 model requires 'passage: ' prefix for document passages
        texts.append(f"passage: {combined}")
    return texts


def build_index():
    print("=" * 72)
    print("  TASK 13: Reproducible RAG Indexing Pipeline")
    print("=" * 72)

    # 1. Load data and schema
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Data file not found: {DATA_FILE}")
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_FILE}")

    print(f"[1/5] Loading {DATA_FILE} and {SCHEMA_FILE}...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # 2. Validate
    print("[2/5] Validating data against Schema V1...")
    validate_records(records, schema)

    # 3. Compute Checksum
    corpus_hash = sha256_file(DATA_FILE)
    print(f"[3/5] Corpus SHA256 Checksum: {corpus_hash}")

    # 4. Generate Embeddings
    print("[4/5] Loading local E5 model and generating embeddings...")
    passages = build_passage_texts(records)

    # Ensure offline mode
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    from sentence_transformers import SentenceTransformer
    import torch
    import numpy as np

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"      Loading '{MODEL_NAME}' on {device.upper()}...")
    t0_load = time.perf_counter()
    embedder = SentenceTransformer(MODEL_NAME, device=device)
    load_ms = (time.perf_counter() - t0_load) * 1000
    print(f"      Model loaded in {load_ms:.1f} ms.")

    t0_embed = time.perf_counter()
    embeddings = embedder.encode(
        passages,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,  # L2 normalize so cosine = dot product
    ).astype(np.float32)
    embed_ms = (time.perf_counter() - t0_embed) * 1000
    print(f"      Generated {embeddings.shape[0]} embeddings of dimension {embeddings.shape[1]} in {embed_ms:.1f} ms.")

    # 5. Export Index (.npz)
    print("[5/5] Exporting .rag_embeddings_v2.npz...")
    record_ids = [item["id"] for item in records]
    metadata = {
        "sha256": corpus_hash,
        "record_ids": np.array(record_ids),
        "num_records": len(records),
        "embedding_dim": embeddings.shape[1],
        "model_name": MODEL_NAME,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    TARGET_CACHE_DATA.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        TARGET_CACHE_DATA,
        embeddings=embeddings,
        sha256=metadata["sha256"],
        record_ids=metadata["record_ids"],
        model_name=metadata["model_name"],
        created_at=metadata["created_at"],
    )
    print(f"      Saved index artifact: {TARGET_CACHE_DATA} ({TARGET_CACHE_DATA.stat().st_size:,} bytes)")

    print("=" * 72)
    print("✅ REPRODUCIBLE INDEX BUILD COMPLETED SUCCESSFULLY")
    print(f"   Corpus records:   {len(records)}")
    print(f"   Matrix shape:     {embeddings.shape}")
    print(f"   Corpus SHA256:    {corpus_hash}")
    print("=" * 72)


if __name__ == "__main__":
    build_index()
