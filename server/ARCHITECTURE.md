# 🧠 Kiến Trúc Hệ Thống AI - Robot Moon (Server)

Tài liệu này giải thích chi tiết phương thức hoạt động, các thuật toán và mô hình (models) được sử dụng trong lõi AI của Robot Moon, nằm trong thư mục `server/`.

Hệ thống được chia thành 2 phân hệ chính chạy song song:
1. **Phân hệ Voice (`server/voice`)**: Đóng vai trò là "Tai" (VAD, STT) và "Miệng" (TTS).
2. **Phân hệ LLM (`server/llm`)**: Đóng vai trò là "Bộ Não" (LLM, RAG).

---

## 1. Phương thức hoạt động tổng thể (Pipeline)

Hệ thống hoạt động theo cơ chế **State Machine** (Cỗ máy trạng thái) và vòng lặp **Senses-Think-Act** (Cảm nhận - Suy nghĩ - Hành động). Mọi luồng dữ liệu được điều phối bởi tệp trung tâm `server/voice/brain.py`.

**Vòng lặp sự kiện:**
1. **[IDLE] (Chờ đợi):** `vad.py` chạy ngầm, liên tục quét các khối âm thanh nhỏ 30ms.
2. **Wake-word:** Nếu phát hiện tiếng người, `stt.py` dịch sang chữ. Nếu chữ có chứa "Moon ơi", Robot tỉnh dậy.
3. **[LISTENING] (Lắng nghe):** `vad.py` tiếp tục thu âm toàn bộ câu hỏi cho đến khi người dùng im lặng 2 giây.
4. **[THINKING] (Suy nghĩ):** 
   - `rag_engine.py` trích xuất thông tin bài học khớp với câu hỏi.
   - `moon_tutor.py` đẩy câu hỏi + RAG vào mô hình LLM.
5. **[SPEAKING] (Phản hồi):** `tts.py` nhận từng chữ do LLM sinh ra, ghép thành câu và phát ra loa lập tức (Streaming). Sau khi nói xong, robot mở lại cửa sổ [LISTENING] 8 giây để chờ câu hỏi tiếp (Multi-turn).

---

## 2. Phân hệ Thị giác/Thính giác (Voice)

### 2.1. Lắng nghe và Lọc ồn (VAD - Voice Activity Detection)
- **Tệp tin**: `vad.py`
- **Nhiệm vụ**: Xác định chính xác lúc nào con người đang nói và lúc nào là tiếng ồn môi trường.
- **Thuật toán sử dụng**:
  1. **RMS (Root Mean Square)**: Tính toán năng lượng âm thanh. Mic sẽ liên tục đo độ ồn nền (Ambient Noise) bằng đường trung bình động (Exponential Moving Average). Tiếng động chỉ được tính là "tiếng người" nếu âm lượng gấp 2 lần độ ồn nền.
  2. **Spectral Flatness (Độ phẳng phổ)**: Dùng toán học biến đổi âm thanh sang miền tần số (Fourier Transform - FFT). Tiếng quạt máy hoặc gió thổi có năng lượng rải đều (Độ phẳng > 0.6), trong khi giọng nói con người có thanh quản tạo ra các họa âm rõ rệt (Độ phẳng < 0.4). Thuật toán này giúp Robot Moon không bị đánh lừa bởi tiếng quạt máy chĩa thẳng vào micro.

### 2.2. Nhận diện giọng nói (STT - Speech to Text)
- **Tệp tin**: `stt.py`
- **Nhiệm vụ**: Biến tệp ghi âm thành văn bản.
- **Mô hình**: **Whisper (Large-v3 và Turbo)** của OpenAI, chạy thông qua API của Groq.
- **Thuật toán và Hướng tiếp cận**:
  1. **Dual-pass Transcription (Nhận diện Kép)**: Khi nghe lén từ khóa "Moon", do mô hình Whisper hay bị nhầm lẫn giữa tiếng Việt và Anh. Hệ thống sẽ ép luồng 1 nghe bằng tiếng Việt, luồng 2 nghe bằng tiếng Anh và luồng 3 nhồi Prompt định hướng ("Mớm lời"). Thằng nào trúng chữ Moon thì kích hoạt.
  2. **Fuzzy Matching (Khớp mờ Levenshtein)**: Để chống lại việc STT nghe nhầm (vd: "Anna", "panna"), thuật toán tính khoảng cách Levenshtein được áp dụng. Nếu chữ sai khác không quá 2 ký tự so với "moon", robot vẫn nhận ra.
  3. **Hallucination Filter (Bộ lọc ảo giác)**: Khi trong phòng quá ồn, Whisper thường bị ảo giác sinh ra các câu rác (vd: "Cảm ơn các bạn đã theo dõi"). Một bộ lọc Regex và Blacklist được thiết kế riêng để dập tắt các câu này.

### 2.3. Phát âm thanh (TTS - Text to Speech)
- **Tệp tin**: `tts.py`
- **Nhiệm vụ**: Đọc văn bản với giọng tự nhiên.
- **Mô hình**: **Fish Audio (Neural TTS)**.
- **Thuật toán và Hướng tiếp cận**:
  1. **Streaming Audio (Sentence Player)**: Đây là thuật toán cốt lõi chống lag. Thay vì chờ LLM viết xong cả một bài văn 500 chữ rồi mới tạo MP3, hệ thống sẽ cắt văn bản thành từng câu ngắn. Câu số 1 vừa tạo MP3 xong sẽ được quăng thẳng ra loa, trong lúc loa đang hát câu 1 thì mạng ngầm tải tiếp câu 2. Giúp tốc độ phản hồi giảm từ 5 giây xuống chỉ còn dưới 1 giây.
  2. **Barge-in (Cướp lời)**: Sử dụng Multithreading. Trong lúc loa đang phát, một luồng VAD ngầm vẫn liên tục đo âm thanh. Nếu phát hiện tiếng người xen vào, hệ thống gửi ngắt ngầm (Interrupt) tắt hệ thống Windows MCI, bắt robot nín lặng ngay lập tức để nghe.

---

## 3. Phân hệ Bộ Não (LLM & RAG)

### 3.1. Truy xuất kiến thức (RAG Engine)
- **Tệp tin**: `rag_engine.py`
- **Nhiệm vụ**: Giống như sách giáo khoa của Robot. Ngăn chặn LLM nói dối (Hallucination) về kiến thức chuyên ngành học tiếng Anh/Nhật.
- **Thuật toán sử dụng: 3-Tier Cascading Filter (Lọc 3 Tầng)**:
  1. **Tầng 1 (Exact Match)**: O(1) Time complexity. Tìm kiếm khớp chính xác. Nếu trẻ em đọc đúng chữ Hán (Kanji) hoặc từ vựng chuẩn, trả về ngay lập tức.
  2. **Tầng 2 (Fuzzy & Lexical Match)**: Loại bỏ dấu tiếng Việt (thành chữ không dấu) để vượt qua lỗi của STT (nghe nhầm "con mèo" thành "con meo"). Chấm điểm dựa trên Keyword trùng khớp.
  3. **Tầng 3 (Semantic Jaccard Similarity)**: Xử lý các câu đố gián tiếp (Vd: "con gì thích bắt chuột"). Thuật toán loại bỏ Stop-words (hư từ), trích xuất Noun/Verb (thực từ) và đo độ giao nhau của 2 tập hợp chữ (Jaccard Index) trên toàn bộ database để tìm ra kết quả giống nhất.

### 3.2. Sinh ngôn ngữ (LLM - Large Language Model)
- **Tệp tin**: `moon_tutor.py`
- **Nhiệm vụ**: Đóng vai bạn gấu trúc 5 tuổi, kết hợp kiến thức từ RAG để trò chuyện với bé.
- **Mô hình**: **Llama-3 (8B) hoặc Qwen**, chạy cục bộ qua Ollama.
- **Thuật toán và Hướng tiếp cận**:
  1. **Hybrid Prompting (Kết hợp ngữ cảnh kép)**: Gộp System Prompt (Định hình tính cách tấu hài, nhõng nhẽo) + RAG Context (Kiến thức cứng từ giáo án) vào làm một để đưa cho Llama xử lý.
  2. **Session Memory Management**: Dùng một mảng bộ nhớ đệm (Ring Buffer) lưu trữ 6 đoạn hội thoại gần nhất dựa trên `session_id`. Kỹ thuật này giúp Robot biết "nhớ" ngữ cảnh của câu hỏi trước đó trong chu kỳ 8 giây multi-turn, nhưng không làm tràn bộ nhớ RAM (VRAM) của Llama.
  3. **Streaming Generator**: Sử dụng kỹ thuật `yield` trong Python kết hợp API stream của Ollama để ép mô hình "nghĩ tới đâu, phun chữ tới đó" thay vì ngâm toàn bộ câu trả lời, phối hợp hoàn hảo với hệ thống Sentence Player của TTS.
