"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: rag_engine.py (Bộ máy tìm kiếm kiến thức RAG)
--------------------------------------------------------------------------------
Nhiệm vụ: Đóng vai trò là 'Sách giáo khoa' của robot. Giúp LLM không bao giờ bịa đặt kiến thức chuyên ngành.

[CẤU TRÚC CHÍNH]
1. Load dữ liệu: Đọc file data.json chứa bài học tiếng Anh / tiếng Nhật.
2. search(): Thuật toán tìm kiếm (Scoring). Chia nhỏ câu hỏi thành từ khóa, bỏ đi các từ vô nghĩa (stop_words), và đối chiếu để tìm ra 2 bài học có điểm cao nhất.
3. format_context_for_prompt(): Đóng gói bài học tìm được để nhét vào Prompt cho LLM đọc hiểu dễ nhất.

[CẢI TIẾN V2 - VECTOR SEARCH ĐA NGÔN NGỮ]
Tầng 3 đã được thay thế từ Jaccard overlap thô sơ → Sentence-Transformers Cosine Similarity.
- Model embedding: multilingual-e5-small (47M params, hỗ trợ Tiếng Việt + Nhật + Anh)
- E5 model dùng prefix 'query:' / 'passage:' để tối ưu hiệu suất retrieval
- Embeddings được tính 1 lần và cache vào file .npz để khởi động lại không cần tính lại
- Cosine similarity chạy trên numpy (vectorized), tốc độ < 1ms cho vài trăm bài học
"""
# ==============================================================================
# rag_engine.py — Bộ máy Cascading RAG 3 Tầng (3-Tier Filtering) cho Robot Moon
# Hỗ trợ học Tiếng Nhật - Tiếng Anh - Tiếng Việt cho trẻ em 7-10 tuổi
# ==============================================================================

import os
import sys
import json
import re
import hashlib
import unicodedata
import functools
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

# Cấu hình UTF-8 cho Windows Terminal để in tiếng Việt chuẩn
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

# Legacy paths are kept only for explicit fixture/legacy callers. Production
# retrieval has one source of truth and one cache under data/.
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
EMBEDDINGS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".rag_embeddings.npz")

# Task 13: Schema V1 / Data V2 paths
DATA_V2_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "data_v2.json"))
EMBEDDINGS_V2_CACHE_PATH = os.path.join(os.path.dirname(DATA_V2_PATH), ".rag_embeddings_v2.npz")
DEFAULT_DATA_PATH = DATA_V2_PATH

# A lexical match nominates a lesson but never authorizes it by itself.
LEXICAL_VECTOR_MIN_COSINE = 0.825
VECTOR_ONLY_MIN_COSINE = 0.85
TOP_RESULT_MIN_MARGIN = 0.02

_OUT_OF_SCOPE_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\b(cach nau|cach lam|nguyen lieu|cong thuc|recipe|ingredients|how to cook|how to make|how many ingredients)\b",
    r"\b(song( duoc)? bao nhieu|bao nhieu nam song|bao nhieu tuoi|tuoi tho|dan so|bao nhieu tinh|so dien thoai|cuu hoa|cap cuu|cach viet email|email xin viec|dau dau|uong thuoc|thuoc gi|thoi tiet|gia ve|ve may bay|lifespan|how long .*live|how many years .*live|how old|population|how many provinces|phone number|emergency number|weather|temperature|headache|medicine|flight price|write an email)\b",
    r"\b(ngu phap the|grammar (?:form|tense)|conjugat(?:e|ion)|chia dong tu)\b",
    r"(?:何歳|何年生き|人口|電話番号|救急|消防|文法|活用)",
))
_LANGUAGE_LOOKUP_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\b(tieng nhat|tieng anh|japanese|english|in japanese|in english)\b.{0,28}\b(la gi|noi sao|viet sao|doc sao|how do you say|what is|how to say)\b",
    r"\b(la gi|noi sao|viet sao|doc sao|how do you say|what is|how to say)\b.{0,28}\b(tieng nhat|tieng anh|japanese|english)\b",
    r"(?:日本語|英語).*(?:何|どう言|どう書|読み)|(?:何|どう言|どう書|読み).*(?:日本語|英語)",
))


def is_out_of_scope_intent(query: str) -> bool:
    """Reject known non-lesson intents before any lexical or vector lookup."""
    normalized = strip_accents(unicodedata.normalize("NFC", query or "").casefold())
    if not any(pattern.search(normalized) for pattern in _OUT_OF_SCOPE_PATTERNS):
        return False
    return not any(pattern.search(normalized) for pattern in _LANGUAGE_LOOKUP_PATTERNS)

# ─── Embedding model (lazy init) ─────────────────────────────────────────────
# Model multilingual-e5-small: 47M params, 384 chiều
# Hỗ trợ ĐẦY ĐỦ Tiếng Việt + Tiếng Nhật + Tiếng Anh (50+ ngôn ngữ)
# E5 model được thiết kế chuyên biệt cho retrieval/search (đúng task RAG)
# Chạy trên GPU nếu có CUDA (RTX 4050), fallback CPU nếu không
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"

_embedder = None
_embedder_lock = __import__("threading").Lock()


def _get_embedder():
    """Lazy-load sentence-transformers model lên GPU/CPU."""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _embedder_lock:
        if _embedder is not None:
            return _embedder
        try:
            # Resolve the standard Hugging Face cache location without importing
            # huggingface_hub first: its offline flag is read at import time.
            hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
            cache_root = Path(os.environ.get("HF_HUB_CACHE", hf_home / "hub"))
            model_cache = cache_root / "models--intfloat--multilingual-e5-small" / "snapshots"
            cached = model_cache.is_dir() and any(path.is_dir() for path in model_cache.iterdir())
            old_hub_offline = os.environ.get("HF_HUB_OFFLINE")
            old_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
            if cached:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"

            from sentence_transformers import SentenceTransformer
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            # Avoid Hub metadata checks on every robot start when the complete
            # model snapshot is already cached. First-time installs still use
            # the normal online path and populate the cache.
            if cached:
                try:
                    _embedder = SentenceTransformer(
                        EMBEDDING_MODEL_NAME,
                        device=device,
                        model_kwargs={"local_files_only": True},
                    )
                except Exception as offline_error:
                    # A partial cache can occur after an interrupted download.
                    # Restore online behavior and let Transformers complete it.
                    if old_hub_offline is None:
                        os.environ.pop("HF_HUB_OFFLINE", None)
                    else:
                        os.environ["HF_HUB_OFFLINE"] = old_hub_offline
                    if old_transformers_offline is None:
                        os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    else:
                        os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline
                    try:
                        import huggingface_hub.constants as hf_constants
                        hf_constants.HF_HUB_OFFLINE = False
                        import transformers.utils.hub as transformer_hub
                        if hasattr(transformer_hub, "_is_offline_mode"):
                            transformer_hub._is_offline_mode = False
                    except Exception:
                        pass
                    print(f"⚠️ [RAG-VEC] Cache offline chưa dùng được, thử tải online: {offline_error}")
                    _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
                finally:
                    if old_hub_offline is None:
                        os.environ.pop("HF_HUB_OFFLINE", None)
                    else:
                        os.environ["HF_HUB_OFFLINE"] = old_hub_offline
                    if old_transformers_offline is None:
                        os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    else:
                        os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline
            else:
                _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
            print(f"✅ [RAG-VEC] Sentence-Transformers loaded on {device.upper()}")
        except ImportError:
            print("⚠️ [RAG-VEC] sentence-transformers chưa cài. Chạy: pip install sentence-transformers")
            _embedder = None
        except Exception as e:
            print(f"⚠️ [RAG-VEC] Lỗi khởi tạo embedder: {e}")
            _embedder = None
    return _embedder


def strip_accents(text: str) -> str:
    """
    Hàm bỏ dấu tiếng Việt để tìm kiếm mờ (Fuzzy Search).
    Ví dụ: 'con mèo' -> 'con meo' để lỡ người dùng nói ngọng STT nhận sai vẫn tìm ra.
    """
    # Tách các dấu thanh (huyền, sắc, hỏi, ngã, nặng) ra khỏi chữ cái
    text = unicodedata.normalize('NFD', text)
    # Xóa toàn bộ các dấu thanh đó đi
    text = re.sub(r'[\u0300-\u036f]', '', text)
    # Xử lý riêng chữ đ/Đ thành d/D vì nó không phải dấu thanh
    return text.replace('đ', 'd').replace('Đ', 'D')


def _data_file_hash(path: str) -> str:
    """Tính MD5 hash của file data để tương thích ngược với legacy tests."""
    return _data_file_hashes(path)[1]


def _data_file_hashes(path: str) -> tuple[str, str]:
    """Tính cả SHA256 và MD5 hash của data file để đối sánh với cache V1 lẫn V2."""
    h_sha = hashlib.sha256()
    h_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h_sha.update(chunk)
            h_md5.update(chunk)
    return h_sha.hexdigest(), h_md5.hexdigest()


class MoonRAG:
    """
    Exact and lexical tiers nominate candidates; semantic scoring gates every result.
    --------------------------------------------------------------------------
    Tầng 1 (Exact): Khớp alias/cụm từ để đề xuất bài; không short-circuit.

    Tầng 2 (Lexical): Dùng cụm từ dài nhất; accent folding chỉ khi input không dấu.

    Semantic gate: mọi ứng viên cần đạt cosine; chỉ trả top-1.
    """

    # Expose scoring policy from the class for inspection/configuration.
    VECTOR_SIMILARITY_THRESHOLD = VECTOR_ONLY_MIN_COSINE
    LEXICAL_SIMILARITY_THRESHOLD = LEXICAL_VECTOR_MIN_COSINE
    VECTOR_SIMILARITY_MARGIN = TOP_RESULT_MIN_MARGIN

    def __init__(self, data_file: Optional[str] = None):
        # Lưu đường dẫn file dữ liệu (ưu tiên data_v2.json theo Task 13 nếu có)
        self.data_file = data_file or DEFAULT_DATA_PATH
        # Biến chứa toàn bộ sách giáo khoa (dạng mảng các Dictionary)
        self.knowledge_base: List[Dict[str, Any]] = []
        # Mục lục ngược (Inverted Index) tra cứu siêu tốc
        self.inverted_index: Dict[str, List[Dict[str, Any]]] = {}
        # Ma trận embedding cho Vector Search (Tầng 3)
        self._embeddings: Optional[np.ndarray] = None  # shape: (N, dim)
        self._embedding_texts: List[str] = []  # raw texts đã embed, dùng để debug
        # Tự động nạp dữ liệu khi khởi tạo class
        self.load_data()

    def load_data(self) -> None:
        """Đọc cơ sở dữ liệu từ file data.json đưa vào RAM"""
        # search() caches by (instance, query, top_k); invalidate old hits before
        # replacing this instance's records and indexes.
        self.search.cache_clear()
        if not os.path.exists(self.data_file):
            print(f"⚠️ [RAG] Không tìm thấy file dữ liệu: {self.data_file}")
            self.knowledge_base = []
            return

        try:
            # Đọc file với bảng mã utf-8
            with open(self.data_file, "r", encoding="utf-8") as f:
                self.knowledge_base = json.load(f)

            # --- TIỀN XỬ LÝ (PRE-COMPUTING) & MỤC LỤC NGƯỢC (INVERTED INDEX) ---
            self.inverted_index = {}
            for item in self.knowledge_base:
                # 1. Tiền xử lý cho Tầng 2 (Lexical): Xóa dấu & chặt từ sẵn
                # Only curated vocabulary and keywords participate in retrieval.
                item["_precomputed_words"] = set()

                # Tầng lexical quét toàn bộ knowledge base ở mỗi query. Chuẩn hóa
                # metadata một lần khi nạp dữ liệu để tránh lặp strip dấu/tokenize.
                item["_rag_keywords_normalized"] = [
                    (normalized, strip_accents(normalized))
                    for normalized in (
                        self._normalize(kw) for kw in item.get("keywords", [])
                    )
                ]
                vi = self._normalize(item.get("vi") or item.get("vietnamese", ""))
                item["_rag_vi_normalized"] = vi
                item["_rag_vi_unaccented"] = strip_accents(vi)
                topic = strip_accents(self._normalize(item.get("topic", "")))
                item["_rag_topic_tokens"] = set(topic.split())

                # 2. Xây dựng Mục lục ngược cho Tầng 1 (Keyword, English, Romaji, Kanji, Kana)
                index_keys = [self._normalize(kw) for kw in item.get("keywords", [])]
                for field in ("vi", "vietnamese", "en", "english", "ja_kanji", "kanji", "ja_kana", "japanese_hiragana"):
                    val = self._normalize(item.get(field, ""))
                    if val and val not in index_keys:
                        index_keys.append(val)

                for key in index_keys:
                    if key not in self.inverted_index:
                        self.inverted_index[key] = []
                    if item not in self.inverted_index[key]:
                        self.inverted_index[key].append(item)

            print(f"✅ [RAG] Đã nạp thành công {len(self.knowledge_base)} bài học vào bộ nhớ (Đã đánh Index).")

            # 3. Xây dựng / Nạp embedding cho Tầng 3 (Vector Search)
            self._build_embeddings()

        except Exception as e:
            print(f"❌ [RAG] Lỗi đọc file data.json: {e}")
            self.knowledge_base = []

    # ══════════════════════════════════════════════════════════════════════════
    #  VECTOR EMBEDDINGS (PRE-COMPUTE & CACHE)
    # ══════════════════════════════════════════════════════════════════════════
    def _build_embedding_texts(self) -> List[str]:
        """
        Tạo chuỗi đại diện cho mỗi bài học để embed cho multilingual-e5-small.
        Embed only reviewed vocabulary, its Japanese spellings/readings, topic, and keywords.
        E5 model yêu cầu prefix 'passage: ' cho documents để tối ưu retrieval.
        """
        texts = []
        for item in self.knowledge_base:
            vi = item.get("vi") or item.get("vietnamese", "")
            en = item.get("en") or item.get("english", "")
            ja = item.get("ja", "")
            ja_kanji = item.get("ja_kanji") or item.get("kanji", "")
            ja_kana = item.get("ja_kana") or item.get("japanese_hiragana", "")
            keywords = " ".join(item.get("keywords", []))
            topic = item.get("topic", "")
            parts = [vi, en, ja, ja_kanji, ja_kana, topic, keywords]
            combined = " ".join(p for p in parts if p)
            texts.append(f"passage: {combined}")
        return texts

    def _build_embeddings(self) -> None:
        """
        Tính hoặc nạp embeddings từ cache.
        - Nếu data.json chưa thay đổi (so MD5 hash) → nạp từ file .npz (< 1ms)
        - Nếu thay đổi hoặc chưa có cache → tính mới trên GPU/CPU, lưu cache
        """
        self._embedding_texts = self._build_embedding_texts()
        if not self._embedding_texts:
            self._embeddings = None
            return

        # Production always uses one cache alongside the single source corpus.
        # Explicit non-production fixtures keep an adjacent cache for isolation.
        is_source_corpus = os.path.abspath(self.data_file) == os.path.abspath(DATA_V2_PATH)
        cache_path = (EMBEDDINGS_V2_CACHE_PATH if is_source_corpus else
                      os.path.join(os.path.dirname(os.path.abspath(self.data_file)), ".rag_embeddings_v2.npz"))
        current_sha256, _ = _data_file_hashes(self.data_file)
        record_ids = [str(item.get("id", "")) for item in self.knowledge_base]

        if os.path.exists(cache_path):
            try:
                cached = np.load(cache_path, allow_pickle=True)
                cache_sha256 = str(cached["sha256"].item())
                cache_ids = [str(value) for value in cached["record_ids"].tolist()]
                cached_model = str(cached["model_name"].item())
                matrix = cached["embeddings"].astype(np.float32)
                if (cache_sha256 == current_sha256
                        and cache_ids == record_ids
                        and cached_model == EMBEDDING_MODEL_NAME
                        and matrix.ndim == 2
                        and matrix.shape[0] == len(self._embedding_texts)
                        and np.isfinite(matrix).all()):
                    self._embeddings = matrix
                    print(f"⚡ [RAG-VEC] Nạp {self._embeddings.shape[0]} embeddings từ cache ({self._embeddings.shape[1]}D). KHÔNG load model e5-small.")
                    return
                raise ValueError("SHA256, record_ids, hoặc shape cache không khớp corpus")
            except Exception as e:
                print(f"⚠️ [RAG-VEC] Cache hỏng, tính lại: {e}")
                try:
                    os.remove(cache_path)
                    print(f"🗑️ [RAG-VEC] Đã xóa cache cũ: {cache_path}")
                except OSError as remove_error:
                    print(f"⚠️ [RAG-VEC] Không xóa được cache cũ: {remove_error}")

        # Tính embeddings mới
        print("⚠️ [RAG-VEC] Không có cache hoặc data thay đổi, đang load model e5-small để tạo embeddings...")
        embedder = _get_embedder()
        if embedder is None:
            print("⚠️ [RAG-VEC] Không có embedder; fail closed, không dùng lexical thay semantic gate.")
            self._embeddings = None
            return

        import time
        t0 = time.time()
        embeddings = embedder.encode(
            self._embedding_texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,  # L2-normalize sẵn để cosine = dot product
        )
        self._embeddings = embeddings.astype(np.float32)
        elapsed = time.time() - t0
        print(f"✅ [RAG-VEC] Đã embed {self._embeddings.shape[0]} bài học ({self._embeddings.shape[1]}D) trên GPU/CPU trong {elapsed:.2f}s.")

        # Lưu cache
        try:
            np.savez_compressed(
                cache_path,
                embeddings=self._embeddings,
                sha256=current_sha256,
                record_ids=np.asarray(record_ids, dtype=str),
                model_name=EMBEDDING_MODEL_NAME,
                created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            )
            print(f"💾 [RAG-VEC] Đã lưu cache embeddings vào {cache_path}")
        except Exception as e:
            print(f"⚠️ [RAG-VEC] Không thể lưu cache: {e}")

    def _normalize(self, text: str) -> str:
        """Hàm dọn dẹp văn bản cơ bản: Viết thường, xóa dấu câu thừa, xóa khoảng trắng thừa"""
        # Đưa về chữ in thường và xóa khoảng trắng hai đầu
        text = text.lower().strip()
        # Thay thế các dấu chấm, phẩy, chấm hỏi, ngoặc... thành khoảng trắng
        text = re.sub(r"[!?,.:;\"\'()\[\]/\\-]", " ", text)
        # Tách ra và gom lại để xóa các khoảng trống dư thừa ở giữa
        return " ".join(text.split())

    def _clean_query(self, query: str) -> str:
        """
        Loại bỏ tên gọi robot (Moon ơi, này Moon) khỏi câu hỏi
        để không bị nhầm lẫn với bài học về con gấu trúc thực tế.
        """
        q = query.lower()
        # Common Vietnamese STT syllable splits for the loanword "ramen".
        # Normalize before T1/T2 and vector scoring so all tiers see one form.
        q = re.sub(r"\b(?:mi\s+)?(?:ra|la)\s+men\b", "ramen", q, flags=re.IGNORECASE)
        # Ngoại lệ: Nếu câu hỏi thực sự hỏi về gấu trúc (con gấu trúc, loài gấu trúc) thì giữ nguyên
        if any(w in q for w in ["con gấu trúc", "loài gấu trúc", "gấu trúc tiếng", "gấu trúc ăn gì"]):
            return query

        # Biểu thức chính quy: Cắt bỏ các cụm từ gọi tên robot ở đầu hoặc cuối câu
        q_clean = re.sub(r"\b(moon ơi|ơi moon|này moon|ê moon|hey moon|moon)\b", "", q, flags=re.IGNORECASE)
        q_clean = q_clean.strip()
        # Trả về câu đã làm sạch (nếu câu sau khi cắt vẫn còn nghĩa, >= 2 ký tự)
        return q_clean if len(q_clean) >= 2 else query

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 1: BỘ LỌC ĐƠN GIẢN (FAST PATH - EXACT & KANJI MATCH) ~ 0ms
    # ══════════════════════════════════════════════════════════════════════════
    @staticmethod
    def _has_vietnamese_diacritics(text: str) -> bool:
        return bool(re.search(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", text, re.IGNORECASE))

    def _lexical_candidates(self, query: str) -> List[Tuple[float, Dict[str, Any], str]]:
        """Longest-phrase-first aliases; accent folding only for unaccented input."""
        clean = self._clean_query(query)
        q_norm = self._normalize(clean)
        accent_fallback = not self._has_vietnamese_diacritics(q_norm)
        q_unaccented = strip_accents(q_norm) if accent_fallback else None

        # Each alias gets a priority based on phrase length. Longer phrases
        # reserve their spans first so "trái cây" cannot fall through to "cây".
        alias_hits: List[Tuple[int, int, float, Dict[str, Any], str]] = []
        q_tokens = q_norm.split()
        for item in self.knowledge_base:
            aliases = list(item.get("keywords", []))
            aliases.extend(item.get(field, "") for field in (
                "vi", "vietnamese", "en", "english", "ja_kanji", "ja_kana", "kanji", "japanese_hiragana"
            ))
            seen_aliases = set()
            for alias in aliases:
                alias_norm = self._normalize(str(alias or ""))
                if not alias_norm or alias_norm in seen_aliases:
                    continue
                seen_aliases.add(alias_norm)
                variants = [alias_norm]
                if accent_fallback:
                    unaccented = strip_accents(alias_norm)
                    if unaccented != alias_norm:
                        variants.append(unaccented)
                for variant in variants:
                    a_tokens = variant.split()
                    if len(a_tokens) == 1 and a_tokens[0] in item.get("stopwords_override", []) and len(q_tokens) > 1:
                        continue
                    for start in range(len(q_tokens) - len(a_tokens) + 1):
                        if q_tokens[start:start + len(a_tokens)] == a_tokens:
                            specificity = float(len(a_tokens) * 10 + min(len(alias_norm), 20) / 20)
                            alias_hits.append((start, start + len(a_tokens), specificity, item, alias_norm))
                            break

        # Longest spans win; ties are retained for semantic disambiguation.
        alias_hits.sort(key=lambda hit: (-(hit[1] - hit[0]), -hit[2], hit[0]))
        consumed: List[set[int]] = []
        result: Dict[str, Tuple[float, Dict[str, Any], str]] = {}
        for start, end, score, item, alias in alias_hits:
            span = set(range(start, end))
            overlaps = [prior for prior in consumed if span & prior]
            if len(span) == 1 and overlaps:
                continue
            if len(span) > 1:
                # Prefer a longer phrase over a shorter overlapping phrase;
                # identical spans may nominate competing records for scoring.
                if any(prior != span for prior in overlaps):
                    continue
                if not overlaps:
                    consumed.append(span)
            current = result.get(str(item.get("id", id(item))))
            if current is None or score > current[0]:
                result[str(item.get("id", id(item)))] = (score, item, alias)

        # Kanji strings are exact orthographic evidence and may contain no spaces.
        for item in self.knowledge_base:
            kanji = (item.get("ja_kanji") or item.get("kanji") or "").strip()
            if kanji and any("\u4e00" <= char <= "\u9fff" for char in kanji) and kanji in clean:
                key = str(item.get("id", id(item)))
                result[key] = (100.0, item, kanji)
        return sorted(result.values(), key=lambda row: row[0], reverse=True)

    def _tier1_exact_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Tầng 1: Khớp trực tiếp 1-1. Nhanh và chính xác nhất.
        Nếu bé nói trúng y chang chữ Hán hoặc từ vựng tiếng Anh -> Trả về luôn!
        """
        q_norm = self._normalize(self._clean_query(query))
        candidates = self._lexical_candidates(query)
        # Tier 1 keeps orthographic/exact aliases; semantic validation happens
        # later in search(), never by short-circuiting here.
        exact = [row for row in candidates if row[2] in q_norm or row[2] in query]
        exact.extend(row for row in candidates if len(row[2].split()) > 1)
        return list({str(item.get("id", id(item))): item for _, item, _ in exact}.values())

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 2: BỘ LỌC VỪA (LEXICAL & FUZZY TOKEN MATCHING) ~ 1ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier2_lexical_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Tầng 2: Xử lý tiếng Việt không dấu, viết tắt, hoặc từ lóng.
        Ví dụ: STT nghe nhầm thành 'con meo' thay vì 'con mèo'.
        """
        return [item for _, item, _ in self._lexical_candidates(query)]

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 3: VECTOR SEARCH (SENTENCE EMBEDDING + COSINE SIMILARITY) < 1ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier3_vector_search(self, query: str) -> List[Dict[str, Any]]:
        """Semantic-only retrieval. Lexical evidence is handled by search()."""
        ranked = self._semantic_scores(query)
        eligible = [(score, item) for score, item in ranked
                    if score >= VECTOR_ONLY_MIN_COSINE]
        if not eligible:
            return []
        if len(eligible) > 1 and eligible[0][0] - eligible[1][0] < TOP_RESULT_MIN_MARGIN:
            return []
        return [eligible[0][1]]

    def _semantic_scores(self, query: str) -> List[Tuple[float, Dict[str, Any]]]:
        """Return cosine-ranked records; an unavailable embedder means abstain."""
        if self._embeddings is None or len(self._embedding_texts) != len(self.knowledge_base):
            return []
        embedder = _get_embedder()
        if embedder is None:
            return []
        try:
            query_vector = embedder.encode(
                [f"query: {query}"], normalize_embeddings=True, show_progress_bar=False,
            ).astype(np.float32)
            scores = (self._embeddings @ query_vector.T).reshape(-1)
            if len(scores) != len(self.knowledge_base) or not np.isfinite(scores).all():
                return []
            ranked = [(float(scores[index]), item)
                      for index, item in enumerate(self.knowledge_base)]
            ranked.sort(key=lambda row: row[0], reverse=True)
            return ranked
        except Exception as exc:
            print(f"⚠️ [RAG-VEC] Vector search lỗi; fail closed: {exc}")
            return []

    def _tier3_jaccard_fallback(self, query: str) -> List[Dict[str, Any]]:
        """
        Fallback Tầng 3 cũ: Jaccard overlap trên precomputed words.
        Chỉ dùng khi sentence-transformers không khả dụng (thiếu dependency).

        Task 12B — Siết chặt ngưỡng Jaccard:
        Yêu cầu tối thiểu >= 2 content words khớp (thay vì >= 1 như trước).
        Điều này loại bỏ false positive do từ đơn lẻ ngẫu nhiên trùng khớp
        trong các câu hỏi out-of-corpus (FPR giảm từ 66.7% xuống <15%).
        """
        import math
        q_norm = self._normalize(query)
        q_unacc = strip_accents(q_norm)
        q_words = set(q_unacc.split())

        stopwords = {"la", "gi", "the", "nao", "sao", "cho", "minh", "hoi", "ban", "oi", "con", "cai", "be", "biet", "khong"}
        content_words = q_words - stopwords
        if not content_words:
            content_words = q_words

        scored_items = []
        for item in self.knowledge_base:
            doc_words = item.get("_precomputed_words", set())
            matched_words = content_words.intersection(doc_words)
            # Task 12B: yêu cầu >= 2 từ nội dung khớp để tránh false positive
            # từ các từ đơn lẻ ngẫu nhiên (ví dụ: "science" trong câu hỏi vật lý).
            if len(matched_words) >= 2:
                semantic_score = len(matched_words) / math.sqrt(len(content_words) * len(doc_words) + 1)
                scored_items.append((semantic_score, item))

        if scored_items:
            scored_items.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored_items[:2]]
        return []

    # ══════════════════════════════════════════════════════════════════════════
    #  HÀM TÌM KIẾM ĐIỀU PHỐI 3 TẦNG (CASCADING DISPATCHER)
    # ══════════════════════════════════════════════════════════════════════════
    @functools.lru_cache(maxsize=100)
    def search(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """
        Out-of-scope guard → exact/lexical candidate retrieval → semantic gate → top-1.
        """
        if not self.knowledge_base or not query.strip():
            return []

        clean_query = self._clean_query(query)
        if is_out_of_scope_intent(clean_query):
            print("🛑 [RAG] Câu hỏi ngoài phạm vi bài học; từ chối trước truy xuất.")
            return []

        # T1/T2 nominate candidates, but neither tier can return directly.
        lexical_candidates = self._tier1_exact_filter(clean_query)
        seen = {str(item.get("id", id(item))) for item in lexical_candidates}
        for item in self._tier2_lexical_filter(clean_query):
            key = str(item.get("id", id(item)))
            if key not in seen:
                lexical_candidates.append(item)
                seen.add(key)

        lexical_strength = {
            str(item.get("id", id(item))): lexical_score
            for lexical_score, item, _alias in self._lexical_candidates(clean_query)
        }
        ranked = self._semantic_scores(clean_query)
        if not ranked:
            return []

        # A lexical hit uses the lower calibrated gate; a pure semantic hit
        # needs the stricter gate. Lexical phrase specificity breaks close
        # semantic ties; vector evidence remains mandatory in either case.
        eligible = []
        for score, item in ranked:
            if item.get("review_status", "verified") != "verified":
                continue
            item_id = str(item.get("id", id(item)))
            strength = lexical_strength.get(item_id)
            threshold = LEXICAL_VECTOR_MIN_COSINE if strength is not None else VECTOR_ONLY_MIN_COSINE
            if score >= threshold:
                phrase_words = max(1, int(strength // 10)) if strength is not None else 0
                lexical_bonus = min(0.06, 0.02 + max(0, phrase_words - 1) * 0.015) if strength is not None else 0.0
                eligible.append((score + lexical_bonus, score, item, strength))
        if not eligible:
            return []
        eligible.sort(key=lambda row: row[0], reverse=True)
        strong_phrase_override = (
            eligible[0][3] is not None
            and eligible[0][1] >= 0.88
            and max(1, int(eligible[0][3] // 10)) >= 2
        )
        if (len(eligible) > 1
                and eligible[0][0] - eligible[1][0] < TOP_RESULT_MIN_MARGIN
                and eligible[0][3] is None
                and not strong_phrase_override):
            print("🛑 [RAG] Hai bài đầu quá sát nhau; từ chối kết quả mơ hồ.")
            return []
        print(f"✅ [RAG] Chấp nhận {eligible[0][2].get('id')} cosine={eligible[0][1]:.4f}")
        return [eligible[0][2]]

    def format_context_for_prompt(self, items: List[Dict[str, Any]]) -> str:
        """
        Đóng gói bài học RAG thành định dạng [LESSON DATA] chuẩn hóa, ngắn gọn.
        Ràng buộc LLM chỉ đọc đúng các trường [vi], [ja], [en] để tránh ảo giác.
        """
        if not items:
            return ""

        context_lines = [
            "=== [LESSON DATA — USE EXACTLY, DO NOT ALTER] ===",
            "Chỉ sử dụng các trường dữ liệu sau để trả lời bé, tuyệt đối không tự bịa thêm:"
        ]

        for idx, item in enumerate(items, 1):
            vi = item.get("vi") or item.get("vietnamese", "")
            ja_kanji = item.get("ja_kanji") or item.get("kanji", "")
            ja_kana = item.get("ja_kana") or item.get("japanese_hiragana", "")
            en = item.get("en") or item.get("english", "")
            romaji = item.get("phonetic") or item.get("japanese_romaji", "")
            related_terms = item.get("related_terms") or []
            related_text = json.dumps(related_terms, ensure_ascii=False) if related_terms else "none"
            example = item.get("example") or item.get("example_ja") or "none"

            context_lines.append(
                f"<lesson_data id=\"{item.get('id', '')}\">\n"
                f"title: {item.get('title', '')}\n"
                f"ja_kanji: {ja_kanji}\n"
                f"ja_kana: {ja_kana}\n"
                f"romaji: {romaji}\n"
                f"en: {en}\n"
                f"meaning_vi: {vi}\n"
                f"example: {example}\n"
                f"related_terms: {related_text}\n"
                f"</lesson_data>"
            )

        context_lines.append("=== [HẾT LESSON DATA] ===\n")
        return "\n".join(context_lines)


def get_learning_record(query: str) -> Dict[str, Any] | None:
    """Return the one grounded lesson selected by the semantic-gated pipeline."""
    results = _get_rag().search(query, top_k=1)
    return results[0] if len(results) == 1 else None


# Construct lazily so the process launcher can preload E5 concurrently with
# Ollama/Qwen instead of doing cache rebuilds during module import.
_global_rag = None

def _get_rag():
    global _global_rag
    if not _global_rag:
        _global_rag = MoonRAG()
    return _global_rag


def warmup_embeddings() -> bool:
    """Load and run the query encoder before voice input is enabled."""
    rag = _get_rag()
    if _get_embedder() is None:
        return False
    # Exercise the same query-encoding path used by search so the first caller
    # does not pay CUDA model initialization or kernel warm-up latency.
    return bool(rag._semantic_scores("Moon RAG encoder warm-up"))

def retrieve_context(query: str, top_k: int = 2) -> str:
    rag = _get_rag()
    results = rag.search(query, top_k=top_k)
    return rag.format_context_for_prompt(results) if results else ""

def get_display_info(query: str) -> dict | None:
    rag = _get_rag()
    results = rag.search(query, top_k=1)
    if not results:
        return None
    item = results[0]
    return {
        "id": item.get("id", ""),
        "item_id": item.get("id", ""),
        "title": item.get("title", ""),
        "topic": item.get("topic", ""),
        "vi": item.get("vi") or item.get("vietnamese", ""),
        "vietnamese": item.get("vi") or item.get("vietnamese", ""),
        "ja": item.get("ja", ""),
        "ja_kanji": item.get("ja_kanji") or item.get("kanji", ""),
        "kanji": item.get("ja_kanji") or item.get("kanji", ""),
        "ja_kana": item.get("ja_kana") or item.get("japanese_hiragana", ""),
        "japanese_hiragana": item.get("ja_kana") or item.get("japanese_hiragana", ""),
        "romaji": item.get("phonetic") or item.get("japanese_romaji", ""),
        "japanese_romaji": item.get("phonetic") or item.get("japanese_romaji", ""),
        "en": item.get("en") or item.get("english", ""),
        "english": item.get("en") or item.get("english", ""),
        "phonetic": item.get("phonetic") or item.get("japanese_phonetic", ""),
        "meaning_vi": item.get("vi") or item.get("vietnamese", ""),
        "example": item.get("example") or item.get("example_ja") or "",
        "related_terms": item.get("related_terms", []),
    }

# ─── Script chạy thử nghiệm độc lập (Tự động chạy khi gọi thẳng file này) ────
if __name__ == "__main__":
    import time

    rag = MoonRAG()

    print("\n--- KIỂM TRA HỆ THỐNG LỌC 3 TẦNG (3-TIER RAG V2 — VECTOR SEARCH) ---")

    # Test 1: Khớp chính xác (Moon ơi -> bị xóa. Con mèo -> Exact Match)
    q1 = "Moon ơi con mèo tiếng Nhật đọc sao?"
    t0 = time.time()
    res1 = rag.search(q1)
    t1 = time.time()
    print(f"\n1️⃣ Test Tầng 1 (Exact Match): \"{q1}\"")
    print(f"-> Kết quả: {res1[0]['vietnamese']} | Kanji: {res1[0]['kanji']} | English: {res1[0]['english']}")
    print(f"-> Thời gian: {(t1-t0)*1000:.2f}ms")

    # Test 2: Khớp tiếng Việt không dấu, viết dính chùm
    q2 = "chi cho be tu qua tao di moon"
    t0 = time.time()
    res2 = rag.search(q2)
    t1 = time.time()
    print(f"\n2️⃣ Test Tầng 2 (Lexical Unaccented): \"{q2}\"")
    print(f"-> Kết quả: {res2[0]['vietnamese']} | Kanji: {res2[0]['kanji']} | English: {res2[0]['english']}")
    print(f"-> Thời gian: {(t1-t0)*1000:.2f}ms")

    # Test 3: Hỏi gián tiếp, đố vui (VECTOR SEARCH)
    q3 = "con gi co chiec voi rat dai thich an mia"
    t0 = time.time()
    res3 = rag.search(q3)
    t1 = time.time()
    print(f"\n3️⃣ Test Tầng 3 (Vector Search): \"{q3}\"")
    if res3:
        print(f"-> Kết quả: {res3[0]['vietnamese']} | Kanji: {res3[0]['kanji']} | English: {res3[0]['english']}")
    else:
        print("-> Không tìm thấy kết quả phù hợp")
    print(f"-> Thời gian: {(t1-t0)*1000:.2f}ms")

    # Test 4: Câu hỏi ngữ nghĩa phức tạp
    q4 = "bạn nào thích ăn chuối và nhảy trên cây"
    t0 = time.time()
    res4 = rag.search(q4)
    t1 = time.time()
    print(f"\n4️⃣ Test Tầng 3 (Semantic): \"{q4}\"")
    if res4:
        print(f"-> Kết quả: {res4[0]['vietnamese']} | Kanji: {res4[0]['kanji']} | English: {res4[0]['english']}")
    else:
        print("-> Không tìm thấy kết quả phù hợp")
    print(f"-> Thời gian: {(t1-t0)*1000:.2f}ms")
