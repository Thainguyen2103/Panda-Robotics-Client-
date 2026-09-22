# ==============================================================================
# rag_engine.py — Bộ máy Cascading RAG 3 Tầng (3-Tier Filtering) cho Robot Moon
# Hỗ trợ học Tiếng Nhật - Tiếng Anh - Tiếng Việt cho trẻ em 7-10 tuổi
# ==============================================================================

import os
import sys
import json
import re
import math
import unicodedata
from typing import List, Dict, Any, Optional, Tuple

# Cấu hình UTF-8 cho Windows Terminal
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

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
_CJK_IDEOGRAPH = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_JAPANESE_META_KANJI = set("日本語")


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để tìm kiếm không dấu (ví dụ: 'con meo' -> 'con mèo')"""
    text = unicodedata.normalize('NFD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text)
    return text.replace('đ', 'd').replace('Đ', 'D')


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

    Tầng 3 (Phức tạp - Semantic / Ý niệm trừu tượng, ~5-15ms):
        - Kích hoạt khi bé hỏi câu đố hoặc mô tả đặc điểm gián tiếp mà KHÔNG nói thẳng tên từ.
        - Ví dụ: 'con gì có vòi dài', 'thứ màu vàng chiếu sáng trên trời', 'bạn gì thích ăn chuối'.
        - Quét toàn bộ ngữ nghĩa trong 'fun_fact', 'quiz', 'example' bằng Vector đặc trưng Cosine Similarity.
    """

    def __init__(self, data_file: str = DATA_PATH):
        self.data_file = data_file
        self.knowledge_base: List[Dict[str, Any]] = []
        self.load_data()

    def load_data(self) -> None:
        """Đọc cơ sở dữ liệu từ file data.json"""
        if not os.path.exists(self.data_file):
            print(f"⚠️ [RAG] Không tìm thấy file dữ liệu: {self.data_file}")
            self.knowledge_base = []
            return

        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                self.knowledge_base = json.load(f)
            print(f"✅ [RAG] Đã nạp thành công {len(self.knowledge_base)} bài học vào bộ nhớ.")
        except Exception as e:
            print(f"❌ [RAG] Lỗi đọc file data.json: {e}")
            self.knowledge_base = []

    def _normalize(self, text: str) -> str:
        """Chuẩn hóa chuỗi văn bản (chữ thường, bỏ dấu câu thừa)"""
        text = text.lower().strip()
        text = re.sub(r"[!?,.:;\"\'\(\)\[\]/\\-]", " ", text)
        return " ".join(text.split())

    def _clean_query(self, query: str) -> str:
        """Loại bỏ wake-word Moon nhưng vẫn giữ câu hỏi thật về gấu trúc."""
        q = query.lower()
        # Nếu bé hỏi rõ về con gấu trúc thì giữ lại
        if any(w in q for w in ["con gấu trúc", "loài gấu trúc", "gấu trúc tiếng", "gấu trúc ăn gì"]):
            return query
        # Bỏ các từ xưng hô chào robot ở đầu hoặc cuối câu
        q_clean = re.sub(r"\b(moon ơi|ơi moon|này moon|ê moon|hey moon|moon)\b", "", q, flags=re.IGNORECASE)
        q_clean = q_clean.strip()
        return q_clean if len(q_clean) >= 2 else query

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 1: BỘ LỌC ĐƠN GIẢN (FAST PATH - EXACT & KANJI MATCH) ~ 0ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier1_exact_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Khớp trực tiếp Chữ Hán (Kanji), từ khóa chuẩn và từ vựng chính xác.
        Nếu bé nói trúng từ khóa -> Ngắt sớm (Early Exit) lập tức!
        """
        clean_q = self._clean_query(query)
        q_norm = self._normalize(clean_q)
        q_tokens = set(q_norm.split())
        # Chỉ so Hán tự thật. Các trường Kanji có thể chứa cả Hiragana, còn
        # câu hỏi thường có cụm mô tả chung "日本語" không phải từ cần tra.
        query_kanji = set(_CJK_IDEOGRAPH.findall(query)) - _JAPANESE_META_KANJI

        matches = []
        for item in self.knowledge_base:
            # 1. Khớp chữ Hán (Kanji) trực tiếp
            kanji = item.get("kanji", "")
            item_kanji = set(_CJK_IDEOGRAPH.findall(kanji))
            if query_kanji.intersection(item_kanji):
                matches.append((10.0, item))
                continue

            # 2. Khớp từ khóa chuẩn trong keywords list
            keywords = item.get("keywords", [])
            exact_hit = False
            for kw in keywords:
                kw_norm = self._normalize(kw)
                if kw_norm == q_norm or f" {kw_norm} " in f" {q_norm} ":
                    matches.append((9.0, item))
                    exact_hit = True
                    break
            if exact_hit:
                continue

            # 3. Khớp tên tiếng Anh hoặc Romaji dạng nguyên từ (ví dụ 'cat', 'dog', 'neko')
            en = self._normalize(item.get("english", ""))
            romaji = self._normalize(item.get("japanese_romaji", ""))
            if (en and en in q_tokens) or (romaji and romaji in q_tokens):
                matches.append((8.0, item))

        if matches:
            matches.sort(key=lambda x: x[0], reverse=True)
            return [m[1] for m in matches[:2]]
        return []

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 2: BỘ LỌC VỪA (LEXICAL & FUZZY TOKEN MATCHING) ~ 1ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier2_lexical_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Xử lý tiếng Việt không dấu ('con meo', 'qua tao'), đảo từ, từ ghép.
        """
        q_norm = self._normalize(query)
        q_unacc = strip_accents(q_norm)
        q_tokens = set(q_norm.split())
        q_unacc_tokens = set(q_unacc.split())

        scored_items = []
        for item in self.knowledge_base:
            score = 0.0

            # 1. Khớp cụm từ trong keywords list (ưu tiên cụm từ dài hơn)
            for kw in item.get("keywords", []):
                kw_norm = self._normalize(kw)
                kw_unacc = strip_accents(kw_norm)

                # Từ không dấu quá ngắn dễ đụng từ tiếng Anh thông dụng:
                # "đỏ" -> "do", "cá" -> "ca". Chỉ khớp chúng khi còn dấu
                # ở tầng exact; bản không dấu nên dùng cụm từ dài hơn.
                if len(kw_unacc) < 3:
                    continue

                # Bỏ qua từ đơn 'cho' nếu câu là 'chỉ cho', 'nói cho'
                if kw_unacc == "cho" and ("chi cho" in q_unacc or "noi cho" in q_unacc or "do cho" in q_unacc):
                    continue

                if f" {kw_unacc} " in f" {q_unacc} ":
                    # Trọng số theo độ dài cụm từ: cụm 2-3 từ ('qua tao', 'con meo') điểm cao hơn từ đơn ('cho')
                    score += 5.0 + len(kw_unacc.split()) * 3.0
                    break

            # 2. Đối soát tên tiếng Việt có dấu & không dấu
            vi = self._normalize(item.get("vietnamese", ""))
            vi_unacc = strip_accents(vi)

            if vi in q_norm or vi_unacc in q_unacc:
                score += 8.0
            elif any(len(t) > 2 and t in q_unacc_tokens for t in vi_unacc.split()):
                score += 2.0

            # 3. Đối soát tên chủ đề
            topic_unacc = strip_accents(self._normalize(item.get("topic", "")))
            common_topic = q_unacc_tokens.intersection(set(topic_unacc.split()))
            if common_topic:
                score += len(common_topic) * 1.0

            if score >= 4.0:
                scored_items.append((score, item))

        if scored_items:
            scored_items.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored_items[:2]]
        return []

    # ══════════════════════════════════════════════════════════════════════════
    #  TẦNG 3: BỘ LỌC PHỨC TẠP (SEMANTIC CONCEPT & KNOWLEDGE OVERLAP) ~ 5-10ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier3_semantic_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Dành cho câu hỏi đố vui hoặc miêu tả gián tiếp, ví dụ:
        - "con gì thích bắt chuột" -> mèo
        - "loài vật có chiếc vòi rất dài" -> voi
        - "thứ gì màu vàng chiếu sáng trên trời" -> mặt trời
        Quét sâu qua fun_fact, quiz, example để tìm tương đồng ý niệm.
        """
        q_norm = self._normalize(query)
        q_unacc = strip_accents(q_norm)
        q_words = set(q_unacc.split())

        # Loại bỏ các hư từ tiếng Việt thông dụng để tập trung vào từ mang ý nghĩa
        stopwords = {
            "la", "gi", "the", "nao", "sao", "cho", "minh", "hoi", "ban",
            "oi", "con", "cai", "be", "biet", "khong", "co", "rat", "an",
            "a", "am", "are", "do", "does", "i", "is", "me", "my", "the",
            "to", "what", "who", "you", "your",
        }
        content_words = q_words - stopwords
        if not content_words:
            content_words = q_words

        scored_items = []
        for item in self.knowledge_base:
            # Gom toàn bộ ngữ cảnh tri thức của mục đó
            fact_unacc = strip_accents(self._normalize(item.get("fun_fact", "")))
            quiz_unacc = strip_accents(self._normalize(item.get("quiz", "")))
            ex_vi_unacc = strip_accents(self._normalize(item.get("example_vi", "")))

            doc_text = f"{fact_unacc} {quiz_unacc} {ex_vi_unacc}"
            doc_words = set(doc_text.split())

            # Tính độ trùng khớp ý niệm (Jaccard Overlap)
            matched_words = content_words.intersection(doc_words)
            # Một từ chung đơn lẻ (ví dụ "I", "you", "hôm nay") không đủ
            # chứng minh câu hỏi thuộc bài học; tránh bơm RAG sai vào hội thoại.
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
    def search(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """
        Điều phối tìm kiếm lần lượt qua 3 tầng:
        Tầng 1 (Trúng từ khóa) -> Trả về ngay (0ms)
        -> nếu không có -> Tầng 2 (Khớp từ mờ/không dấu) -> Trả về (~1ms)
        -> nếu không có -> Tầng 3 (Quét sâu ý niệm ngữ nghĩa) (~5ms)
        """
        if not self.knowledge_base or not query.strip():
            return []

        # Làm sạch tên robot (wake-word) khỏi câu hỏi để tránh nhiễu
        clean_query = self._clean_query(query)

        # Tầng 1: Đơn giản (Exact / Kanji Match)
        t1_results = self._tier1_exact_filter(clean_query)
        if t1_results:
            return t1_results[:top_k]

        # Tầng 2: Vừa (Fuzzy & Lexical Match)
        t2_results = self._tier2_lexical_filter(clean_query)
        if t2_results:
            return t2_results[:top_k]

        # Tầng 3: Phức tạp (Semantic Concept Search)
        t3_results = self._tier3_semantic_filter(clean_query)
        if t3_results:
            return t3_results[:top_k]

        return []

    def format_context_for_prompt(self, items: List[Dict[str, Any]]) -> str:
        """
        Tạo khối văn bản [TÀI LIỆU BÀI HỌC] dễ hiểu để nạp vào prompt cho LLM.
        """
        if not items:
            return ""

        context_lines = [
            "=== [TÀI LIỆU BÀI HỌC DÀNH CHO BÉ (RAG)] ===",
            "Hãy sử dụng các thông tin chính xác dưới đây để giải thích và chơi cùng bé:"
        ]

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
        return "\n".join(context_lines)


# ─── Chạy thử kiểm chứng 3 Tầng Lọc ──────────────────────────────────────────
if __name__ == "__main__":
    rag = MoonRAG()

    print("\n--- KIỂM TRA HỆ THỐNG LỌC 3 TẦNG (3-TIER RAG) ---")

    # Test 1: Đi vào Tầng 1 (Chính xác từ khóa / Kanji)
    q1 = "Moon ơi con mèo tiếng Nhật đọc sao?"
    res1 = rag.search(q1)
    print(f"\n1️⃣ Test Tầng 1 (Exact Match): \"{q1}\"")
    print(f"-> Kết quả: {res1[0]['vietnamese']} | Kanji: {res1[0]['kanji']} | English: {res1[0]['english']}")

    # Test 2: Đi vào Tầng 2 (Tiếng Việt không dấu / đảo từ)
    q2 = "chi cho be tu qua tao di moon"
    res2 = rag.search(q2)
    print(f"\n2️⃣ Test Tầng 2 (Lexical Unaccented): \"{q2}\"")
    print(f"-> Kết quả: {res2[0]['vietnamese']} | Kanji: {res2[0]['kanji']} | English: {res2[0]['english']}")

    # Test 3: Đi vào Tầng 3 (Câu hỏi đố vui gián tiếp, không nêu tên từ)
    q3 = "con gi co chiec voi rat dai thich an mia"
    res3 = rag.search(q3)
    print(f"\n3️⃣ Test Tầng 3 (Semantic Concept Match): \"{q3}\"")
    print(f"-> Kết quả: {res3[0]['vietnamese']} | Kanji: {res3[0]['kanji']} | English: {res3[0]['english']}")
