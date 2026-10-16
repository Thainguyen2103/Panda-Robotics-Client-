import sys, os
from pathlib import Path
ROOT = Path(os.path.abspath(".")).resolve()
sys.path.insert(0, str(ROOT))

from server.llm.rag_engine import MoonRAG

rag = MoonRAG()
print(f"RAG Data File: {rag.data_file}")
print(f"RAG Knowledge Base: {len(rag.knowledge_base)} items")

NEGATIVES = [
    ("n01", "How do I build a rocket engine?", None, "Engineering -- not in corpus."),
    ("n02", "What is the capital of France?", None, "Geography -- not in corpus."),
    ("n03", "Explain quantum entanglement.", None, "Physics -- not in corpus."),
    ("n04", "Comment dit-on bonjour en japonais?", None, "French question -- language not in corpus."),
    ("n05", "Qu est-ce que le subjonctif en francais?", None, "French grammar N2/N1 level -- not in corpus."),
    ("n06", "Quelle est la difference entre etre et avoir?", None, "French grammar -- not in corpus."),
    ("n07", "Wie sagt man Guten Morgen auf Japanisch?", None, "German question -- language not in corpus."),
    ("n08", "Was ist der Unterschied zwischen Dativ und Akkusativ?", None, "German grammar -- not in corpus."),
    ("n09", "What is the difference between wa and ga in Japanese grammar?", None, "Advanced J-grammar N2 -- not in corpus."),
    ("n10", "Explain the usage of te-form in Japanese for requests.", None, "Advanced J-grammar te-form -- not in corpus."),
    ("n11", "How does the conditional ba-form work in Japanese?", None, "Advanced J-grammar N1 -- not in corpus."),
    ("n12", "What is photosynthesis?", None, "Biology -- not in corpus."),
    ("n13", "Who invented the telephone?", None, "History -- not in corpus."),
    ("n14", "What are the planets in the solar system?", None, "Astronomy -- not in corpus."),
    ("n15", "How do you calculate the area of a circle?", None, "Math -- not in corpus."),
]

print("\n--- RESULTS ON FULL CASCADE ---")
for qid, q, _, rationale in NEGATIVES:
    res = rag.search(q, top_k=2)
    ids = [r["id"] for r in res]
    status = "REJECTED []" if not ids else f"ACCEPTED {ids}"
    print(f"{qid}: {q} -> {status}")
