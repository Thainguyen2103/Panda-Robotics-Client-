"""Stable integration layer between the lesson RAG and any LLM provider."""

from typing import Optional

from .rag_engine import MoonRAG


_engine = MoonRAG()


def retrieve_context(question: str, top_k: int = 2) -> str:
    """Return verified lesson context for a user question, or an empty string."""
    items = _engine.search(question, top_k=top_k)
    return _engine.format_context_for_prompt(items) if items else ""


def get_display_info(question: str) -> Optional[dict]:
    """Return the best lesson fields for an OLED/LED consumer."""
    items = _engine.search(question, top_k=1)
    if not items:
        return None
    item = items[0]
    return {
        "id": item.get("id", ""),
        "kanji": item.get("kanji", ""),
        "hiragana": item.get("japanese_hiragana", ""),
        "romaji": item.get("japanese_romaji", ""),
        "english": item.get("english", ""),
        "vietnamese": item.get("vietnamese", ""),
        "topic": item.get("topic", ""),
    }
