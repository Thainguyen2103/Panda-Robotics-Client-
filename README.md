# 🐼 Panda Robotics — "Moon"

Robot bạn đồng hành hỗ trợ trẻ em học tiếng Anh — dự án PBL4, Đại học Đà Nẵng.
Panda nghe được (wake-word "Panda" + câu hỏi tiếng Việt/Anh), nhìn được (nhận diện
chủ nhân + cảm xúc), trả lời bằng giọng nói tự nhiên và "diễn" toàn bộ cảm xúc lên
màn OLED theo phong cách robot Vector (Anki).

## ✨ Tính năng nổi bật

- **Giọng nói**: wake-word 3 lớp (Whisper dual-pass + cứu hộ fuzzy/phonetic), VAD
  streaming chống ồn quạt/TV, chống hallucination, sửa lỗi ASR bằng LLM.
- **Não cloud**: Groq Whisper (STT) → Groq LLM (trả lời) → Fish Audio (TTS streaming
  từng câu) — độ trễ wake→tiếng đầu tiên ~2-3s.
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
 mic / mic trình duyệt ─→ voice.py (VAD + Whisper) ─→ brain.py
 camera / ESP32-CAM    ─→ vision.py (YuNet/SFace/FER)     │
                                                           ├─→ llm.py (Groq)
 dashboard web (OLED ảo, nút điều khiển) ←─ MQTT broker ←─┤
 robot ESP32 (OLED thật, motor, buzz)    ←─ MQTT broker ←─┴─→ tts.py (Fish Audio)
```

## 📁 Cấu trúc thư mục

```
config/      settings.py (mọi hằng số), secrets.example.py (mẫu key)
server/      brain.py (điều phối), voice.py (STT), llm.py, tts.py,
             vision.py (CV), topics.py (24 chủ đề), mqtt_bridge.py,
             virtual_robot.py (robot ảo để test không cần phần cứng)
web/         server.js + public/ (dashboard OLED mô phỏng, idle behaviors)
firmware/    panda_firmware.ino (ESP32, chạy được trên Wokwi lẫn chip thật)
tools/       bench_topics.py, dev_mic_bridge.py
```

## 🚀 Chạy thử (không cần phần cứng)

```powershell
# 1. Python env
cd server; python -m venv venv; .\venv\Scripts\activate
pip install -r requirements.txt

# 2. Key API
copy config\secrets.example.py config\secrets.py   # rồi điền key

# 3. Model files (xem bảng dưới) vào thư mục server/

# 4. Chạy tất cả
.\start.bat          # brain + web dashboard
# Dashboard: http://localhost:3000
```

Nói **"Panda"** rồi hỏi bất kỳ điều gì bằng tiếng Việt — OLED diễn cảm xúc,
icon chủ đề và trả lời bằng giọng nói.

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
| `master_face.npy` | Đăng ký rõ ràng bằng `tools/enroll_face.py`; không tự lấy người đầu tiên (dữ liệu sinh trắc — không push) |

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

- `config/secrets.py` (key thật) và `master_face.npy` (sinh trắc) nằm trong `.gitignore`.
- Chia sẻ code = chia sẻ `secrets.example.py`.
- Model weights không push (repo nhẹ, tránh bản quyền nhị phân).

## 👥 Đội ngũ

Dự án PBL4 — Đại học Đà Nẵng. Vai trò: AI + hiển thị (voice/LLM/CV/OLED),
firmware + cơ khí, báo cáo & truyền thông.
