# Moon Learning RAG

Phần này được tích hợp có chọn lọc từ nhánh `feature/nanh-llm`. Nó chứa 48 bài
học Nhật–Anh–Việt và bộ truy xuất ba tầng của nhóm LLM.

## Luồng đang dùng trong bản demo

```text
STT Việt/Anh/Nhật
  -> server/llm.py
  -> learning.retrieve_context()
  -> Gemini/DeepSeek/Groq
  -> Fish TTS
```

`server/llm.py` là cổng LLM chính. Khi câu hỏi khớp bài học, dữ liệu Kanji,
Hiragana, Romaji, tiếng Anh, tiếng Việt, ví dụ và câu đố được đưa vào prompt.
Nếu không khớp, cuộc hội thoại dùng LLM bình thường.

## Thành phần

- `data.json`: 48 bài học do nhóm LLM xây dựng.
- `rag_engine.py`: tìm kiếm exact, lexical không dấu và semantic overlap.
- `service.py`: giao diện ổn định để Brain và màn hình sử dụng.
- `ollama_tutor.py`: runner Ollama độc lập, tùy chọn; không phải đường chạy mặc định.
- `Modelfile`: cấu hình tạo model Ollama `moon-tutor` nếu muốn chạy local.

## Kiểm tra RAG

```powershell
.\server\venv\Scripts\python.exe -m unittest discover -s tests -p "test_learning_rag.py" -v
```

## Ollama tùy chọn

```powershell
ollama create moon-tutor -f server/learning/Modelfile
.\server\venv\Scripts\python.exe server/learning/ollama_tutor.py
```

Không cần cài Ollama để chạy dashboard demo; Gemini đang là provider mặc định
khi có `GEMINI_API_KEY`.
