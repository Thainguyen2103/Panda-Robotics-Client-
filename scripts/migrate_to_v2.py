#!/usr/bin/env python3
"""
scripts/migrate_to_v2.py -- Migrate server/llm/data.json to data/data_v2.json (Task 13)
Enriches 53 records with Schema V1 fields and token conflict protection.
"""

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_DATA_PATH = ROOT / "server" / "llm" / "data.json"
OUTPUT_DATA_PATH = ROOT / "data" / "data_v2.json"
SCHEMA_PATH = ROOT / "data" / "schema_v1.json"


def migrate():
    with open(INPUT_DATA_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    v2_records = []
    for item in records:
        rec_id = item["id"]
        topic = item.get("topic", "")

        # Determine skill and type
        if rec_id.startswith("manner_"):
            skill = "culture"
            rec_type = "sentence"
        elif rec_id.startswith("act_"):
            skill = "vocab"
            rec_type = "word"
        elif rec_id.startswith("grammar_"):
            skill = "grammar"
            rec_type = "rule"
        else:
            skill = "vocab"
            rec_type = "word"

        # Determine stopwords_override to fix short-circuit false positives
        # Especially n06 ('la' in French) and n11 ('ba' in English ba-form)
        stopwords_override = []
        if rec_id == "family_father":
            stopwords_override = ["ba"]
        elif rec_id == "nature_leaf":
            stopwords_override = ["la", "ha"]
        elif rec_id == "nature_tree":
            stopwords_override = ["ki"]
        elif rec_id == "color_blue":
            stopwords_override = ["ao"]

        # Structured content
        content = {
            "vi": item.get("vi", ""),
            "ja": item.get("ja", ""),
            "ja_kanji": item.get("ja_kanji", ""),
            "ja_kana": item.get("ja_kana", ""),
            "en": item.get("en", ""),
            "phonetic": item.get("phonetic", ""),
            "example": item.get("example", ""),
            "fact": item.get("fact", ""),
        }

        title = f"{item.get('vi', '')} ({item.get('ja', '')})" if item.get('ja') else item.get('vi', '')

        # Standard V1 Record
        v2_item = {
            "id": rec_id,
            "language": "ja",
            "level": "N5",
            "skill": skill,
            "type": rec_type,
            "title": title,
            "content": content,
            "source_id": "panda_kids_n5_curriculum",
            "stopwords_override": stopwords_override,
            "review_status": "verified",
            # Legacy fields retained for backwards compatibility
            "topic": topic,
            "keywords": item.get("keywords", []),
            "vi": item.get("vi", ""),
            "ja": item.get("ja", ""),
            "ja_kanji": item.get("ja_kanji", ""),
            "ja_kana": item.get("ja_kana", ""),
            "en": item.get("en", ""),
            "phonetic": item.get("phonetic", ""),
            "example": item.get("example", ""),
            "fact": item.get("fact", ""),
        }
        v2_records.append(v2_item)

    OUTPUT_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(v2_records, f, ensure_ascii=False, indent=2)

    print(f"Successfully migrated {len(v2_records)} records to {OUTPUT_DATA_PATH}")


if __name__ == "__main__":
    migrate()
