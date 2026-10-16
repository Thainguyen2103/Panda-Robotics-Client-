# Task 14 — Intent Routing Report

## Phạm vi và luồng

Brain nhận transcript rồi gọi `llm.chat_async()` trong `server/brain.py`; hàm này chạy `server/llm/engine.py::chat()`. Trước Task 14, `_get_messages()` chỉ gọi RAG khi `has_learning_intent()` khớp marker. Vì vậy, thực tế trước đây không phải mọi câu đều chạy retrieval.

```text
Brain transcript → engine.chat() → normalize → IntentRouter
  ├─ KNOWLEDGE_QNA → fast vocabulary path (nếu khớp) → RAG context → LLM
  ├─ CHITCHAT → bỏ qua RAG → social-chat system instruction → LLM
  ├─ GRAMMAR_FIX → correction path/prompt → LLM
  ├─ PRONUNCIATION → pronunciation guidance prompt → LLM
  └─ CURRICULUM_NEXT → progress-aware prompt → LLM
```

RAG tiếp tục dùng `retrieve_context()` trong `server/llm/rag_engine.py`; file này chọn `data/data_v2.json` nếu tồn tại, nếu không thì `server/llm/data.json`. Không sửa RAG, cache, corpus hoặc các voice/TTS voice mappings.

## Thay đổi

- `server/llm/brain_router.py`: classifier rule-based nhẹ, 5 intent, confidence/reason, fallback bảo thủ sang KNOWLEDGE_QNA và prompt theo intent. Không gọi LLM phân loại để tránh thêm một inference vào mỗi lượt.
- `server/llm/engine.py`: phân loại sau normalize; chỉ intent kiến thức được phép thêm RAG context; chitchat bỏ retrieval; các intent còn lại được bổ sung prompt. Không đổi interface Brain → `chat_async()`.
- `tests/test_brain_router.py`: các câu mẫu cho 5 nhóm cùng test dispatch engine với retrieval stub; stub ngăn tải model hoặc gọi dịch vụ ngoài.

Pronunciation và curriculum hiện chỉ có routing/prompt. Trong code được truy vết không có audio pronunciation analyzer hoặc progress tracker bền vững; prompt yêu cầu không khẳng định đã phân tích audio và không bịa tiến độ.

## Kiểm thử

| Lệnh | Kết quả |
|---|---|
| `HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 python -m unittest discover -s tests -p test_brain_router.py -v` | 7 test methods, pass; kiểm tra 27 trường hợp/subcase gồm 15 mẫu yêu cầu, pronunciation, fallback và dispatch RAG cho cả 5 câu kiến thức + 5 câu chitchat |
| `HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 python -m unittest discover -s tests -p test_llm_language.py -v` | 9/9 pass; kiểm tra regression ngôn ngữ/prompt. Không có Ollama khả dụng nên không gọi inference thật |
| `python -m py_compile server/llm/brain_router.py server/llm/engine.py tests/test_brain_router.py` | Pass |
| `git diff --check -- server/llm/brain_router.py server/llm/engine.py tests/test_brain_router.py` | Pass |

Các bài test router thay `OllamaTextClient.ensure_ready` và stub RAG trước khi import engine; do đó chúng không khởi chạy LLM hay embedding model. Test ngôn ngữ đọc cache local 53 records/384 chiều; log cho biết package `sentence-transformers` không có, và các test không cần vector inference vẫn pass.

## Latency

Benchmark rule classifier chạy 20.000 lần phân loại (200 batch × 100 câu), local Python, warm process. Thời gian chỉ đo `IntentRouter.classify()`, không gồm LLM, RAG, TTS hoặc Brain.

| Đo lường | Mean | Median | P95 |
|---|---:|---:|---:|
| Rule classification mỗi câu | 0.011105 ms | 0.011021 ms | 0.013240 ms |
| RAG calls cho 5 câu chitchat trước thay đổi | 0 (marker gate cũ đã bỏ qua) | — | — |
| RAG calls cho 5 câu chitchat sau thay đổi | 0 (được test với stub) | — | — |

Không có số đo end-to-end hoặc bằng chứng latency retrieval được tiết kiệm so với baseline cũ: marker gate hiện hữu đã tránh RAG cho các câu chitchat mẫu. Router mới cung cấp phân loại và prompt chuyên biệt; không thể tuyên bố giảm thời gian đáp tổng thể hoặc đạt <300 ms nếu không đo với LLM đang chạy.

## Working tree và giới hạn

Các file mới của task: `server/llm/brain_router.py`, `tests/test_brain_router.py`, `TASK14_INTENT_ROUTING_REPORT.md`. Có chỉnh `server/llm/engine.py`. Những file production và dữ liệu đã dirty trước task được giữ nguyên ngoài các thay đổi có chủ đích ở `engine.py`; không stage, commit hoặc xóa file. Không truy cập `learning`.

Chưa xác minh chất lượng phân loại trên tập hội thoại thật, latency LLM end-to-end, hành vi với Ollama đang chạy, phân tích audio phát âm hoặc trạng thái học lưu trữ. Cần chạy thử hội thoại thực tế và rà các câu có nhiều ý định trước khi xem router là production-ready.
