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

# Đường dẫn tĩnh trỏ đến file data.json nằm cùng thư mục với file này
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
# Đường dẫn cache embeddings (nằm cạnh data.json)
EMBEDDINGS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".rag_embeddings.npz")

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
            from sentence_transformers import SentenceTransformer
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
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
    """Tính MD5 hash của file data.json để biết khi nào dữ liệu thay đổi."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class MoonRAG:
    """
    Kiến trúc RAG Lọc 3 Tầng (3-Tier Cascading Filter / Multi-Stage Retrieval):
    --------------------------------------------------------------------------
    Tầng 1 (Đơn giản - Fast Path, 0ms, O(1)):
        - Khớp chính xác Từ khóa (Keywords), Chữ Hán (Kanji), Romaji, Từ tiếng Anh.
        - Nếu tìm thấy mục tiêu xác thực cao -> Trả về NGAY LẬP TỨC (Short-circuit),
          tiết kiệm 100% thời gian tính toán và tài nguyên CPU/GPU!

    Tầng 2 (Vừa - Lexical & Fuzzy Matching, ~1ms):
        - Xử lý tiếng Việt không dấu ('con meo', 'qua tao'), viết tắt, đảo từ.
        - Tính điểm trùng khớp Token (Jaccard) trên tên và chủ đề.
        - Nếu độ tin cậy đạt ngưỡng -> Trả về kết quả, không cần đến Tầng 3.

    Tầng 3 (Vector Search - Sentence Embedding + Cosine Similarity, <1ms):
        - Kích hoạt khi bé hỏi câu đố hoặc mô tả đặc điểm gián tiếp mà KHÔNG nói thẳng tên từ.
        - Ví dụ: 'con gì có vòi dài', 'thứ màu vàng chiếu sáng trên trời', 'bạn gì thích ăn chuối'.
        - Sử dụng sentence-transformers (multilingual-e5-small) chạy trên GPU RTX 4050.
        - Hỗ trợ đầy đủ 3 ngôn ngữ: Tiếng Việt, Tiếng Nhật, Tiếng Anh.
        - Embeddings được pre-compute và cache vào file .npz, cosine similarity trên numpy vectorized.
    """

    # Ngưỡng cosine similarity tối thiểu để Tầng 3 coi là kết quả hợp lệ.
    # multilingual-e5-small thường cho cosine similarity khá cao.
    VECTOR_SIMILARITY_THRESHOLD = 0.82

    def __init__(self, data_file: str = DATA_PATH):
        # Lưu đường dẫn file dữ liệu
        self.data_file = data_file
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
                fact_unacc = strip_accents(self._normalize(item.get("fun_fact", "")))
                quiz_unacc = strip_accents(self._normalize(item.get("quiz", "")))
                ex_vi_unacc = strip_accents(self._normalize(item.get("example_vi", "")))
                doc_text = f"{fact_unacc} {quiz_unacc} {ex_vi_unacc}"
                item["_precomputed_words"] = set(doc_text.split())

                # 2. Xây dựng Mục lục ngược cho Tầng 1 (Keyword, English, Romaji)
                index_keys = [self._normalize(kw) for kw in item.get("keywords", [])]
                en = self._normalize(item.get("english", ""))
                romaji = self._normalize(item.get("japanese_romaji", ""))
                if en: index_keys.append(en)
                if romaji: index_keys.append(romaji)

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
        Tạo chuỗi đại diện cho mỗi bài học để embed.
        Kết hợp tên tiếng Việt + English + fun_fact + quiz + example
        để vector chứa đủ ngữ nghĩa cho câu hỏi gián tiếp.

        E5 model yêu cầu prefix 'passage: ' cho documents để tối ưu retrieval.
        """
        texts = []
        for item in self.knowledge_base:
            parts = [
                item.get("vietnamese", ""),
                item.get("english", ""),
                item.get("fun_fact", ""),
                item.get("quiz", ""),
                item.get("example_vi", ""),
                item.get("example_en", ""),
                " ".join(item.get("keywords", [])),
            ]
            # E5 model yêu cầu prefix 'passage:' cho documents
            combined = " ".join(p for p in parts if p)
            texts.append(f"passage: {combined}")
        return texts

    def _build_embeddings(self) -> None:
        """
        Tính hoặc nạp embeddings từ cache.
        - Nếu data.json chưa thay đổi (so MD5 hash) → nạp từ file .npz (< 1ms)
        - Nếu thay đổi hoặc chưa có cache → tính mới trên GPU/CPU, lưu cache
        """
        embedder = _get_embedder()
        if embedder is None:
            print("⚠️ [RAG-VEC] Tầng 3 sẽ fallback về Jaccard cũ (không có sentence-transformers).")
            self._embeddings = None
            return

        self._embedding_texts = self._build_embedding_texts()
        if not self._embedding_texts:
            self._embeddings = None
            return

        # Kiểm tra cache
        current_hash = _data_file_hash(self.data_file)
        cache_path = EMBEDDINGS_CACHE_PATH

        if os.path.exists(cache_path):
            try:
                cached = np.load(cache_path, allow_pickle=True)
                if (cached.get("hash", "") == current_hash
                        and cached["embeddings"].shape[0] == len(self._embedding_texts)):
                    self._embeddings = cached["embeddings"].astype(np.float32)
                    print(f"⚡ [RAG-VEC] Nạp {self._embeddings.shape[0]} embeddings từ cache ({self._embeddings.shape[1]}D).")
                    return
            except Exception as e:
                print(f"⚠️ [RAG-VEC] Cache hỏng, tính lại: {e}")

        # Tính embeddings mới
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
            np.savez_compressed(cache_path, embeddings=self._embeddings, hash=current_hash)
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
    def _tier1_exact_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Tầng 1: Khớp trực tiếp 1-1. Nhanh và chính xác nhất.
        Nếu bé nói trúng y chang chữ Hán hoặc từ vựng tiếng Anh -> Trả về luôn!
        """
        # Dọn dẹp câu hỏi
        clean_q = self._clean_query(query)
        q_norm = self._normalize(clean_q)
        # Chuyển câu hỏi thành mảng các từ đơn (tập hợp set để truy vấn nhanh)
        q_tokens = set(q_norm.split())

        matches = []
        seen_items = set()

        # 1. Khớp chữ Hán (Kanji): Lặp qua toàn bộ vì nó là tìm kiếm từng ký tự
        for item in self.knowledge_base:
            kanji = item.get("kanji", "")
            if kanji and any(k_char in query for k_char in kanji if k_char.strip()):
                if id(item) not in seen_items:
                    matches.append((10.0, item))
                    seen_items.add(id(item))

        # 2. Khớp siêu tốc bằng Mục lục ngược (Inverted Index)
        # 2.1 Cụm từ dài (Nguyên câu hỏi)
        if q_norm in self.inverted_index:
            for item in self.inverted_index[q_norm]:
                if id(item) not in seen_items:
                    matches.append((9.0, item))
                    seen_items.add(id(item))

        # 2.2 Từng từ đơn (Ví dụ: "cat", "apple")
        for token in q_tokens:
            if token in self.inverted_index:
                for item in self.inverted_index[token]:
                    if id(item) not in seen_items:
                        matches.append((8.0, item))
                        seen_items.add(id(item))

        # Nếu có kết quả ở Tầng 1
        if matches:
            # Sắp xếp theo điểm số từ cao xuống thấp
            matches.sort(key=lambda x: x[0], reverse=True)
            # Lấy tối đa 2 bài học tốt nhất
            return [m[1] for m in matches[:2]]
        return []

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 2: BỘ LỌC VỪA (LEXICAL & FUZZY TOKEN MATCHING) ~ 1ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier2_lexical_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Tầng 2: Xử lý tiếng Việt không dấu, viết tắt, hoặc từ lóng.
        Ví dụ: STT nghe nhầm thành 'con meo' thay vì 'con mèo'.
        """
        q_norm = self._normalize(query)
        # Tạo thêm một bản sao không dấu của câu hỏi
        q_unacc = strip_accents(q_norm)
        q_tokens = set(q_norm.split())
        q_unacc_tokens = set(q_unacc.split())

        scored_items = []
        for item in self.knowledge_base:
            score = 0.0

            # 1. Quét cụm từ trong keywords list (kể cả không dấu)
            for kw in item.get("keywords", []):
                kw_norm = self._normalize(kw)
                kw_unacc = strip_accents(kw_norm)

                # Ngoại lệ: Bỏ qua từ 'cho' (trong con chó) nếu câu hỏi là 'chỉ cho', 'nói cho'
                if kw_unacc == "cho" and ("chi cho" in q_unacc or "noi cho" in q_unacc or "do cho" in q_unacc):
                    continue

                if f" {kw_unacc} " in f" {q_unacc} ":
                    # Cụm từ dài ('con meo') được điểm cao hơn cụm từ ngắn ('meo')
                    score += 5.0 + len(kw_unacc.split()) * 3.0
                    break

            # 2. Khớp thẳng tên bài học bằng tiếng Việt (có dấu và không dấu)
            vi = self._normalize(item.get("vietnamese", ""))
            vi_unacc = strip_accents(vi)

            if vi in q_norm or vi_unacc in q_unacc:
                score += 8.0
            # Nếu tên bài học có chứa các từ khóa nằm rải rác trong câu hỏi
            elif any(len(t) > 2 and t in q_unacc_tokens for t in vi_unacc.split()):
                score += 2.0

            # 3. Khớp theo chủ đề (Ví dụ: hỏi về 'động vật' -> lấy bài học nhóm động vật)
            topic_unacc = strip_accents(self._normalize(item.get("topic", "")))
            common_topic = q_unacc_tokens.intersection(set(topic_unacc.split()))
            if common_topic:
                score += len(common_topic) * 1.0

            # Chỉ đưa vào danh sách nếu điểm số vượt ngưỡng an toàn (4.0)
            if score >= 4.0:
                scored_items.append((score, item))

        if scored_items:
            scored_items.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored_items[:2]]
        return []

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 3: VECTOR SEARCH (SENTENCE EMBEDDING + COSINE SIMILARITY) < 1ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier3_vector_search(self, query: str) -> List[Dict[str, Any]]:
        """
        Tầng 3 (CẢI TIẾN): Dùng sentence-transformers thay vì Jaccard thô.
        - Encode câu hỏi thành vector 384 chiều trên GPU (< 5ms)
        - Tính cosine similarity bằng numpy dot product (< 0.1ms)
        - Trả về top-2 bài học có score >= ngưỡng

        Fallback: Nếu không có sentence-transformers → dùng Jaccard cũ.
        """
        # ── Thử Vector Search trước ──────────────────────────────────────────
        if self._embeddings is not None:
            embedder = _get_embedder()
            if embedder is not None:
                try:
                    # Encode câu hỏi thành vector (GPU-accelerated nếu có CUDA)
                    # E5 model yêu cầu prefix 'query:' cho câu hỏi tìm kiếm
                    q_vec = embedder.encode(
                        [f"query: {query}"],
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    ).astype(np.float32)  # shape: (1, 384)

                    # Cosine similarity = dot product (vì đã L2-normalize)
                    scores = (self._embeddings @ q_vec.T).squeeze()  # shape: (N,)

                    # Lọc theo ngưỡng và lấy top-2
                    top_indices = np.argsort(scores)[::-1][:2]
                    results = []
                    for idx in top_indices:
                        if scores[idx] >= self.VECTOR_SIMILARITY_THRESHOLD:
                            results.append(self.knowledge_base[idx])

                    if results:
                        return results
                except Exception as e:
                    print(f"⚠️ [RAG-VEC] Vector search lỗi, fallback Jaccard: {e}")

        # ── Fallback: Jaccard cũ (khi không có sentence-transformers) ────────
        return self._tier3_jaccard_fallback(query)

    def _tier3_jaccard_fallback(self, query: str) -> List[Dict[str, Any]]:
        """
        Fallback Tầng 3 cũ: Jaccard overlap trên precomputed words.
        Chỉ dùng khi sentence-transformers không khả dụng.
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
            if matched_words:
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
        Hàm chính được gọi từ bên ngoài. Nó sẽ cho chạy lần lượt qua 3 Tầng:
        Tầng 1 (Trúng từ khóa) -> Nếu có thì trả về ngay (Siêu tốc 0ms).
        -> Nếu không có -> Chạy Tầng 2 (Fuzzy) -> Trả về (~1ms).
        -> Nếu Tầng 2 cũng không có -> Chạy Tầng 3 (Vector Search) (<1ms).
        """
        if not self.knowledge_base or not query.strip():
            return []

        # Tách chữ "Moon" ra khỏi câu hỏi
        clean_query = self._clean_query(query)

        # Chạy Tầng 1
        t1_results = self._tier1_exact_filter(clean_query)
        if t1_results:
            print("⚡ [RAG] NGẮN MẠCH: Tìm thấy ở Tầng 1 (Exact Match, 0ms), bỏ qua Vector Search!")
            return t1_results[:top_k]

        # Chạy Tầng 2
        t2_results = self._tier2_lexical_filter(clean_query)
        if t2_results:
            print("⚡ [RAG] NGẮN MẠCH: Tìm thấy ở Tầng 2 (Fuzzy Match, ~1ms), bỏ qua Vector Search!")
            return t2_results[:top_k]

        # Chạy Tầng 3 (Vector Search — với fallback Jaccard)
        t3_results = self._tier3_vector_search(clean_query)
        if t3_results:
            return t3_results[:top_k]

        # Nếu không có bài học nào khớp, trả về mảng rỗng
        return []

    def format_context_for_prompt(self, items: List[Dict[str, Any]]) -> str:
        """
        Sau khi tìm được bài học, hàm này đóng gói mảng JSON thành
        đoạn văn bản Text dễ đọc để nạp vào Prompt cho Ollama đọc.
        """
        if not items:
            return ""

        context_lines = [
            "=== [TÀI LIỆU BÀI HỌC DÀNH CHO BÉ (RAG)] ===",
            "Hãy sử dụng các thông tin chính xác dưới đây để giải thích và chơi cùng bé:"
        ]

        # Lặp qua từng bài học để định dạng
        for idx, item in enumerate(items, 1):
            context_lines.append(
                f"\nBài học {idx}: {item.get('vietnamese')} ({item.get('topic')})\n"
                f"- Chữ Hán (Kanji chuẩn): {item.get('kanji')}\n"
                f"- Cách đọc Hiragana: {item.get('japanese_hiragana')}\n"
                f"- Phiên âm Romaji: {item.get('japanese_romaji')}\n"
                f"- Mẹo phát âm tiếng Nhật: {item.get('japanese_phonetic')}\n"
                f"- Tiếng Anh: {item.get('english')} (Mẹo đọc tiếng Anh: {item.get('english_phonetic')})\n"
                f"- Ví dụ tiếng Anh: {item.get('example_en')} ({item.get('example_vi')})\n"
                f"- Ví dụ tiếng Nhật: {item.get('example_jp')}\n"
                f"- Sự thật thú vị: {item.get('fun_fact')}\n"
                f"- Câu đố tương tác cho bé: {item.get('quiz')}"
            )

        context_lines.append("=== [HẾT TÀI LIỆU BÀI HỌC] ===\n")
        # Nối tất cả mảng thành 1 chuỗi lớn
        return "\n".join(context_lines)


_global_rag = None

def _get_rag():
    global _global_rag
    if not _global_rag:
        _global_rag = MoonRAG()
    return _global_rag

def retrieve_context(query: str, top_k: int = 2) -> str:
    rag = _get_rag()
    results = rag.search(query, top_k=top_k)
    return rag.format_context_for_prompt(results) if results else ""

def get_display_info(query: str) -> dict | None:
    rag = _get_rag()
    results = rag.search(query, top_k=1)
    return results[0] if results else None

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
