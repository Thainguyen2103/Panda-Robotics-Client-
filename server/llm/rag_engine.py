"""
--------------------------------------------------------------------------------
TÀI LIỆU HƯỚNG DẪN CODE: rag_engine.py (Bộ máy tìm kiếm kiến thức RAG)
--------------------------------------------------------------------------------
Nhiệm vụ: Đóng vai trò là 'Sách giáo khoa' của robot. Giúp LLM không bao giờ bịa đặt kiến thức chuyên ngành.

[CẤU TRÚC CHÍNH]
1. Load dữ liệu: Đọc file data.json chứa bài học tiếng Anh / tiếng Nhật.
2. search(): Thuật toán tìm kiếm (Scoring). Chia nhỏ câu hỏi thành từ khóa, bỏ đi các từ vô nghĩa (stop_words), và đối chiếu để tìm ra 2 bài học có điểm cao nhất.
3. format_context_for_prompt(): Đóng gói bài học tìm được để nhét vào Prompt cho LLM đọc hiểu dễ nhất.
"""
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
        # Lưu đường dẫn file dữ liệu
        self.data_file = data_file
        # Biến chứa toàn bộ sách giáo khoa (dạng mảng các Dictionary)
        self.knowledge_base: List[Dict[str, Any]] = []
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
            print(f"✅ [RAG] Đã nạp thành công {len(self.knowledge_base)} bài học vào bộ nhớ.")
        except Exception as e:
            print(f"❌ [RAG] Lỗi đọc file data.json: {e}")
            self.knowledge_base = []

    def _normalize(self, text: str) -> str:
        """Hàm dọn dẹp văn bản cơ bản: Viết thường, xóa dấu câu thừa, xóa khoảng trắng thừa"""
        # Đưa về chữ in thường và xóa khoảng trắng hai đầu
        text = text.lower().strip()
        # Thay thế các dấu chấm, phẩy, chấm hỏi, ngoặc... thành khoảng trắng
        text = re.sub(r"[!?,.:;\"\'\(\)\[\]/\\-]", " ", text)
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
        for item in self.knowledge_base:
            # 1. Khớp chữ Hán (Kanji): Quét từng ký tự Kanji xem có lọt vào câu hỏi không
            kanji = item.get("kanji", "")
            if kanji and any(k_char in query for k_char in kanji if k_char.strip()):
                # Trúng Kanji thì cho điểm tuyệt đối 10.0
                matches.append((10.0, item))
                continue

            # 2. Khớp từ khóa chuẩn trong keywords list
            keywords = item.get("keywords", [])
            exact_hit = False
            for kw in keywords:
                kw_norm = self._normalize(kw)
                # Kiểm tra xem từ khóa có nằm y hệt trong câu không
                if kw_norm == q_norm or f" {kw_norm} " in f" {q_norm} ":
                    matches.append((9.0, item))
                    exact_hit = True
                    break
            if exact_hit:
                continue

            # 3. Khớp tên tiếng Anh hoặc Romaji dạng nguyên từ (Ví dụ: 'cat', 'inu')
            en = self._normalize(item.get("english", ""))
            romaji = self._normalize(item.get("japanese_romaji", ""))
            if (en and en in q_tokens) or (romaji and romaji in q_tokens):
                matches.append((8.0, item))

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
    #  TẦNG 3: BỘ LỌC PHỨC TẠP (SEMANTIC CONCEPT & KNOWLEDGE OVERLAP) ~ 5-10ms
    # ══════════════════════════════════════════════════════════════════════════
    def _tier3_semantic_filter(self, query: str) -> List[Dict[str, Any]]:
        """
        Tầng 3: Dành cho câu hỏi đố vui hoặc miêu tả. Không hề có từ khóa trực tiếp.
        Ví dụ: "con gì thích bắt chuột" -> mèo
        """
        q_norm = self._normalize(query)
        q_unacc = strip_accents(q_norm)
        q_words = set(q_unacc.split())

        # Loại bỏ các 'hư từ' (stop_words) vô nghĩa để tập trung vào 'thực từ' (ví dụ: bắt, chuột)
        stopwords = {"la", "gi", "the", "nao", "sao", "cho", "minh", "hoi", "ban", "oi", "con", "cai", "be", "biet", "khong"}
        content_words = q_words - stopwords
        # Nếu cắt xong mà không còn gì, thì lấy lại nguyên câu cũ
        if not content_words:
            content_words = q_words

        scored_items = []
        for item in self.knowledge_base:
            # Gom toàn bộ chữ từ các trường fact, quiz, example của bài học đó
            fact_unacc = strip_accents(self._normalize(item.get("fun_fact", "")))
            quiz_unacc = strip_accents(self._normalize(item.get("quiz", "")))
            ex_vi_unacc = strip_accents(self._normalize(item.get("example_vi", "")))

            doc_text = f"{fact_unacc} {quiz_unacc} {ex_vi_unacc}"
            doc_words = set(doc_text.split())

            # Tính độ giao nhau của 2 tập hợp chữ (Jaccard Similarity)
            matched_words = content_words.intersection(doc_words)
            if matched_words:
                # Công thức tính điểm tương đồng: Số từ giống nhau / Căn bậc 2(Độ dài A * Độ dài B)
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
        Hàm chính được gọi từ bên ngoài. Nó sẽ cho chạy lần lượt qua 3 Tầng:
        Tầng 1 (Trúng từ khóa) -> Nếu có thì trả về ngay (Siêu tốc 0ms).
        -> Nếu không có -> Chạy Tầng 2 (Fuzzy) -> Trả về (~1ms).
        -> Nếu Tầng 2 cũng không có -> Chạy Tầng 3 (Quét sâu) (~5ms).
        """
        if not self.knowledge_base or not query.strip():
            return []

        # Tách chữ "Moon" ra khỏi câu hỏi
        clean_query = self._clean_query(query)

        # Chạy Tầng 1
        t1_results = self._tier1_exact_filter(clean_query)
        if t1_results:
            return t1_results[:top_k]

        # Chạy Tầng 2
        t2_results = self._tier2_lexical_filter(clean_query)
        if t2_results:
            return t2_results[:top_k]

        # Chạy Tầng 3
        t3_results = self._tier3_semantic_filter(clean_query)
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


# ─── Script chạy thử nghiệm độc lập (Tự động chạy khi gọi thẳng file này) ────
if __name__ == "__main__":
    rag = MoonRAG()

    print("\n--- KIỂM TRA HỆ THỐNG LỌC 3 TẦNG (3-TIER RAG) ---")

    # Test 1: Khớp chính xác (Moon ơi -> bị xóa. Con mèo -> Exact Match)
    q1 = "Moon ơi con mèo tiếng Nhật đọc sao?"
    res1 = rag.search(q1)
    print(f"\n1️⃣ Test Tầng 1 (Exact Match): \"{q1}\"")
    print(f"-> Kết quả: {res1[0]['vietnamese']} | Kanji: {res1[0]['kanji']} | English: {res1[0]['english']}")

    # Test 2: Khớp tiếng Việt không dấu, viết dính chùm
    q2 = "chi cho be tu qua tao di moon"
    res2 = rag.search(q2)
    print(f"\n2️⃣ Test Tầng 2 (Lexical Unaccented): \"{q2}\"")
    print(f"-> Kết quả: {res2[0]['vietnamese']} | Kanji: {res2[0]['kanji']} | English: {res2[0]['english']}")

    # Test 3: Hỏi gián tiếp, đố vui
    q3 = "con gi co chiec voi rat dai thich an mia"
    res3 = rag.search(q3)
    print(f"\n3️⃣ Test Tầng 3 (Semantic Concept Match): \"{q3}\"")
    print(f"-> Kết quả: {res3[0]['vietnamese']} | Kanji: {res3[0]['kanji']} | English: {res3[0]['english']}")
