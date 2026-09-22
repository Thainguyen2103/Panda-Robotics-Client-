# 🌙 Moon Robotics

Robot bạn đồng hành hỗ trợ trẻ em học tiếng Anh và tiếng Nhật — dự án PBL4,
Đại học Đà Nẵng. Moon nghe và trò chuyện bằng tiếng Việt, Anh, Nhật; nhìn được
chủ nhân, cảm xúc và cử chỉ; trả lời bằng giọng nói tự nhiên và thể hiện trạng
thái trên màn OLED theo phong cách robot Vector (Anki).

## ✨ Tính năng nổi bật

- **Live Voice trên dashboard**: bật hội thoại trực tiếp hoặc chờ wakeword Moon,
  sau đó nói chuyện nhiều lượt tới khi bấm **Kết thúc**. Chỉ một tab được giữ
  microphone và mic tạm dừng khi Moon đang phát âm thanh để chống tự nghe.
- **Hai pipeline để thử nghiệm**:
  - **Brain Pipeline**: Gemini Transcribe Live (STT Việt/Anh/Nhật) → Qwen local
    qua Ollama → Fish Audio.
  - **Gemini Live**: Gemini xử lý audio trực tiếp; đầu ra dùng Fish Voice hoặc
    giọng Gemini Native. API key chỉ nằm ở backend.
- **LLM local + kho bài học**: `moon-tutor` dùng Qwen 3.5 2B Q4, ưu tiên tốc độ
  và không tốn quota sinh văn bản. RAG cung cấp 48 bài học Nhật–Anh–Việt đã xác
  thực; Gemini mặc định chỉ dùng cho STT/Live Voice.
- **Điều phối ngôn ngữ theo ý định**: Moon phân biệt ngôn ngữ của câu hỏi với từ
  ngoại ngữ đang được hỏi. Ví dụ `こんにちは nghĩa là gì?` được trả lời bằng
  tiếng Việt, còn `What does こんにちは mean?` được trả lời bằng tiếng Anh.
- **Phân loại 24 chủ đề** (hybrid: keyword 0ms + LLM enum fallback, benchmark 15/15)
  → OLED hiển thị icon + caption + màu riêng từng chủ đề.
- **Thị giác máy**: YuNet (face) + SFace (chủ nhân đã đăng ký) + FER+ (biểu cảm) +
  YOLOv8-pose (khớp cánh tay, giơ/vẫy tay), MediaPipe (góc đầu và tín hiệu biểu cảm). Tối ưu cho người
  đối diện, thấy đầu–vai–tay; bổ sung 21 mốc bàn tay, tổ hợp cử chỉ, hướng nhìn/mắt,
  khoảng cách và đồ vật. Xem [hướng dẫn tín hiệu CV mới](docs/vision-signals.md).
- **Màn hình cảm xúc**: 11 biểu cảm + 4 trạng thái AI + 25 hành vi idle tự chủ,
  biểu cảm kết thúc chọn theo ngữ cảnh hội thoại.
- **Kiến trúc MQTT tách rời**: não (Python) ↔ dashboard (web) ↔ thân robot (ESP32)
  không phụ thuộc nhau — robot thật là thin-client, não chạy trên cloud/VPS.

## 🏗 Kiến trúc

```
 mic trình duyệt ─┬→ Gemini Live (audio trực tiếp) ───────────────┐
                  └→ Gemini Transcribe Live (VI/EN/JA) → brain.py │
 camera / ESP32-CAM → vision/ (face/body/hands/pipeline)          │
                                                                ├→ Fish Audio / loa
 brain.py → llm_language.py → llm.py → Qwen/Ollama + learning/ ──┘
 dashboard web (OLED ảo, nút điều khiển) ↔ MQTT ↔ robot ESP32
```

## 📁 Cấu trúc thư mục

```
config/      settings.py (cấu hình và đường dẫn), secrets.example.py (mẫu key)
server/      brain.py (điều phối), llm.py, llm_language.py, tts.py, mqtt_bridge.py
server/voice/  audio/, speech/, wake/, runtime/ (chia theo chức năng)
server/vision/ face/, body/, hands/, pipeline/, runtime/
server/learning/  48 bài học, RAG ba tầng và Modelfile cho Qwen
models/      voice/ và vision/ (model local, không commit)
data/private/ dữ liệu sinh trắc local, không commit
web/         server.js + public/ (dashboard OLED mô phỏng, idle behaviors)
firmware/    panda_firmware.ino (ESP32, chạy được trên Wokwi lẫn chip thật)
tools/       supported utilities, local diagnostics and archived one-off patches
```

Xem [sơ đồ module Voice/Vision](docs/voice-vision-structure.md) trước khi thêm
model, tín hiệu hoặc transport mới.

## 🎙️ Test Live Voice trên dashboard

Chạy `start.bat`, mở <http://localhost:3000>, chọn **Hệ thống xử lý**, rồi chọn
**Bật trực tiếp** hoặc **Chờ “Hey Moon” rồi trò chuyện**. Với Brain Pipeline,
Gemini chỉ chuyển giọng nói thành văn bản; Qwen local tạo câu trả lời và Fish
đọc câu trả lời đó. Sau khi wakeword được xác nhận, có thể hỏi nhiều lượt mà
không cần gọi Moon lại.

Wake âm học tức thời cần model Moon `.ppn` và Picovoice key; nếu chưa có,
dashboard dùng STT dự phòng. `start-voice.bat` chỉ phù hợp để kiểm tra transport
và STT khi không cần Brain trả lời. Xem [hướng dẫn Voice](docs/voice.md) và
[hướng dẫn Qwen/RAG](server/learning/README.md).

## 🚀 Chạy thử (không cần phần cứng)

Yêu cầu khuyên dùng trên Windows: Python 3.12/3.13, Node.js, Ollama và MQTT broker
ở `localhost:1883`. Python 3.14 hiện chưa có wheel WebRTC VAD phù hợp trong môi
trường của dự án.

```powershell
# Chạy các lệnh tại thư mục gốc repository
py -3.12 -m venv server\venv
.\server\venv\Scripts\python.exe -m pip install -r server\requirements.txt -r requirements-voice.txt
.\server\venv\Scripts\python.exe -m pip install fish-audio-sdk pyttsx3
npm --prefix web install

# Tạo file key local; config/secrets.py đã được gitignore
Copy-Item config\secrets.example.py config\secrets.py

# Qwen local ưu tiên tốc độ
ollama pull qwen3.5:2b-q4_K_M
ollama create moon-tutor -f server\learning\Modelfile

# Điền GEMINI_API_KEY và FISH_AUDIO_API_KEY vào config/secrets.py, rồi chạy
.\start.bat
# Dashboard: http://localhost:3000
```

`GEMINI_API_KEY` dùng cho STT Việt/Anh/Nhật và Gemini Live;
`FISH_AUDIO_API_KEY` dùng cho giọng Moon. `GROQ_API_KEY`, DeepSeek và Picovoice
chỉ cần khi chủ động dùng các đường dự phòng tương ứng. Các file model Vision
được đặt trong `models/vision/` theo bảng bên dưới.

Sau khi thay đổi key, model hoặc cấu hình, cần dừng tiến trình cũ và chạy lại
`start.bat`.

## ✅ Kiểm thử nhanh

```powershell
# Language router, Qwen provider và RAG
.\server\venv\Scripts\python.exe -m unittest tests.test_llm_language tests.test_llm_grounded_learning tests.test_learning_rag tests.test_ollama_llm_provider

# Toàn bộ Python tests
.\server\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# Bridge/UI không gọi API thật
node tests/test_gemini_live_bridge.cjs
node tests/test_gemini_transcribe_bridge.cjs
node tests/test_fish_tts.cjs
node tests/test_vision_ui.cjs
```

## 🔑 MQTT topics (hợp đồng giữa các module)

| Topic | Hướng | Nội dung |
|---|---|---|
| `panda/cmd/move\|arm\|buzz\|face\|text` | brain → robot | lệnh hành động / biểu cảm |
| `panda/status` | robot → brain | `{dist, btn}` sonar + nút |
| `panda/ai/state\|thinking\|response\|topic` | brain → dashboard | trạng thái AI + chủ đề |
| `panda/ai/clip`, `panda/ai/mic_live` | mic → brain | clip giọng / mic trực tiếp |
| `panda/camera` | vision → dashboard | JPEG base64 |
| `panda/vision/status` | vision → dashboard | danh tính, biểu cảm, cử chỉ, tình trạng mô hình |

## 📦 Model assets (KHÔNG nằm trong repo — tải riêng)

| File | Nguồn |
|---|---|
| `face_detection_yunet_2023mar.onnx` | [opencv_zoo](https://github.com/opencv/opencv_zoo) |
| `face_recognition_sface_2021dec.onnx` | [opencv_zoo](https://github.com/opencv/opencv_zoo) |
| `emotion-ferplus-8.onnx` | ONNX Model Zoo |
| `face_landmarker.task` | MediaPipe, xem [hướng dẫn CV](docs/vision.md) |
| `res10_300x300_ssd_iter_140000.caffemodel` + `deploy.prototxt` | OpenCV dnn samples |
| `haarcascade_frontalface_default.xml` | OpenCV data |
| `yolov8n.pt`, `yolov8n-pose.pt` | Ultralytics (tự tải khi chạy lần đầu) |
| `master_face.npy` | `data/private/`; đăng ký bằng `tools/enroll_face.py` (dữ liệu sinh trắc — không push) |

## 🔩 Phần cứng (robot thật — thin client)

- **Head**: ESP32-S3 WROOM N16R8 + OV3660 (mắt, stream MJPEG) · INMP441 (tai) ·
  MAX98357 + loa 8Ω (miệng) · SSD1306 128×64 (mặt).
- **Body**: ESP32 DevKit C · TB6612FNG · kit 2WD · HC-SR04 · buzzer · nút nhấn.
- **Power**: 2×18650 + TP4056 + MT3608.
- Firmware mẫu + sơ đồ mô phỏng Wokwi: `firmware/panda_firmware/`
  (`wokwi.toml` + `diagram.json` sẵn sàng; bật `#define USE_MQTT` khi nạp thật).

## 🧪 Mô phỏng trước khi lắp

1. **Wokwi** (firmware + mạch ảo): mở project từ `diagram.json`, paste firmware,
   gõ lệnh Serial `face happy / move forward / buzz on`.
2. **virtual_robot.py**: robot ảo tầng MQTT — mọi hành vi não bộ test không cần chip.

## 🔒 Bảo mật

- `config/secrets.py`, model local và `data/private/master_face.npy` nằm trong `.gitignore`.
- Chia sẻ code = chia sẻ `secrets.example.py`.
- Model weights không push (repo nhẹ, tránh bản quyền nhị phân).

## 👥 Đội ngũ

Dự án PBL4 — Đại học Đà Nẵng. Vai trò: AI + hiển thị (voice/LLM/CV/OLED),
firmware + cơ khí, báo cáo & truyền thông.
