# Moon Learning RAG

Phần này được tích hợp có chọn lọc từ nhánh `feature/nanh-llm`. Nó chứa 48 bài
học Nhật–Anh–Việt và bộ truy xuất ba tầng của nhóm LLM.

## Luồng đang dùng trong bản demo

```text
STT Việt/Anh/Nhật
  -> server/llm.py
  -> learning.retrieve_context()
  -> Qwen qua Ollama
  -> Fish TTS
```

`server/llm.py` là cổng LLM chính. Mặc định nó dùng model Ollama `moon-tutor`
(được tạo từ Qwen 3.5 2B Q4 để vừa GPU 4 GB); Gemini chỉ phục vụ STT trong cấu
hình mặc định.
Khi câu hỏi khớp bài học, dữ liệu Kanji,
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

Có thể đổi model hoặc provider bằng biến môi trường:

```powershell
$env:MOON_LLM_PROVIDER = "ollama"
$env:OLLAMA_LLM_MODEL = "moon-tutor"
$env:OLLAMA_MAX_TOKENS = "128"
```

Nếu model chưa có, tải bằng `ollama pull qwen3.5:2b-q4_K_M`, rồi chạy lại lệnh
`ollama create` phía trên. Khi Ollama hoặc model
không sẵn sàng, phần LLM báo lỗi rõ ràng thay vì dùng quota Gemini. Chỉ khi chủ
động đặt `MOON_LLM_PROVIDER=gemini` thì Gemini mới được dùng để sinh văn bản.
