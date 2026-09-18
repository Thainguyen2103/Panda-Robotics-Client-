# 🐼 Panda Tutor — Trợ Lý AI Học Tiếng Nhật - Anh - Việt Cho Trẻ Em (7–10 Tuổi)

Tài liệu cấu hình **Ollama Modelfile (Qwen 2.5)** kết hợp với **RAG (Retrieval-Augmented Generation)** dành riêng cho Robot giáo dục Panda:
- ✅ **Chống ảo giác tối đa**: Nhiệt độ thấp (`temperature 0.2`), tuân thủ 100% tài liệu bài học.
- ✅ **Hiển thị LED / Màn hình**: Luôn có **Chữ Hán (Kanji)** chuẩn tiếng Nhật + Hiragana + Romaji.
- ✅ **Cơ sở dữ liệu phong phú**: 40 bài học mẫu với các chủ đề gần gũi cho trẻ em 7–10 tuổi.
- ✅ **Hệ thống thuần Text**: Đầu vào và đầu ra đều là Text, hỗ trợ hàm trích xuất nhanh chữ Hán cho màn hình LED và hàm kiểm tra sẵn sàng cho module TTS.

---

## 🌟 1. Luồng Hoạt Động Của Hệ Thống

```
┌─────────────────────────────────┐
│       Văn bản từ bé             │
│  "Panda ơi, con mèo tiếng Nhật" │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 📚 RAG Engine (rag_engine.py + data.json)                  │
│ - Truy xuất từ vựng, Chữ Hán (Kanji), Romaji, tiếng Anh     │
│ - Chuẩn bị ngữ cảnh chính xác 100% đưa vào prompt           │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 🧠 Ollama: Qwen 2.5 (Model: panda-tutor)                    │
│ - Nhiệt độ 0.2 chống ảo giác (Anti-Hallucination)           │
│ - Đầy đủ Chữ Hán (Kanji) + Hiragana + Romaji + Tiếng Anh    │
│ - Giọng điệu thân thiện, khích lệ trẻ 7-10 tuổi             │
└───────────────┬─────────────────────────────────────────────┘
                │
                ├─────────────────────────────────────────────┐
                ▼                                             ▼
┌───────────────────────────────┐             ┌───────────────────────────────┐
│ 📟 Màn Hình LED / OLED Robot  │             │ 🔊 Module Chuyển Giọng Nói    │
│ get_led_display_info()        │             │ (TTS - Text to Speech)        │
│ {                             │             │ check_tts_ready(text)         │
│   "kanji": "猫",              │             │ Chuẩn hóa không bị vấp từ     │
│   "hiragana": "ねこ",         │             │                               │
│   "romaji": "Neko",           │             │                               │
│   "english": "Cat"            │             │                               │
│ }                             │             │                               │
└───────────────────────────────┘             └───────────────────────────────┘
```

---

## 📁 2. Cấu Trúc Thư Mục `server/llm/`

```
server/llm/
├── Modelfile         # Cấu hình Ollama: Nhiệt độ 0.2 chống ảo giác, bắt buộc chữ Hán Kanji
├── data.json         # Kho 40 bài học mẫu: Kanji, Hiragana, Romaji, English, ví dụ, câu đố
├── rag_engine.py     # Bộ máy truy xuất RAG siêu nhẹ (đối soát Kanji, từ khóa, chủ đề)
├── panda_tutor.py    # Bộ điều phối chính: Text Input -> RAG -> Ollama -> Text Output
└── README.md         # Hướng dẫn chi tiết
```

---

## 🚀 3. Hướng Dẫn Cài Đặt & Sử Dụng

### Bước 1: Khởi tạo lại Model trên Ollama

Sau khi cập nhật Modelfile, chạy lệnh:
```bash
cd server/llm
ollama create panda-tutor -f Modelfile
```

### Bước 2: Kiểm tra Bộ Máy RAG (40 bài học)
```bash
python rag_engine.py
```

### Bước 3: Chạy thử Trợ Lý Robot Panda
```bash
python panda_tutor.py
```

---

## 🛠️ 4. Các Hàm Hỗ Trợ Cho Nhóm Dự Án

Trong file `panda_tutor.py`, đã chuẩn bị sẵn các hàm tiện ích để kết nối với các bạn trong nhóm:

### 1. Trích xuất thông tin chữ Hán hiển thị màn hình LED
```python
from panda_tutor import get_led_display_info

info = get_led_display_info("Con mèo tiếng Nhật")
# Kết quả trả về:
# {
#   "kanji": "猫",
#   "hiragana": "ねこ",
#   "romaji": "Neko",
#   "english": "Cat",
#   "vietnamese": "Con mèo",
#   "topic": "Động vật (Animals / 動物)"
# }
# Bạn phụ trách LED chỉ việc lấy info["kanji"] để vẽ lên ma trận LED!
```

### 2. Chuẩn hóa cho bạn làm phần Giọng Nói (TTS)
```python
from panda_tutor import check_tts_ready

text_for_tts = check_tts_ready(panda_reply)
# Loại bỏ sạch các ký hiệu đặc biệt, dấu sao, gạch đầu dòng để loa đọc mượt mà
```
