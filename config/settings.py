# config/settings.py
import os

# ─── API keys: nạp từ config/secrets.py (KHÔNG push) hoặc biến môi trường ────
# Xem secrets.example.py để biết cách tạo secrets.py
try:
    from config.secrets import SECRETS as _SEC
except Exception:
    _SEC = {}


def _key(name: str) -> str:
    return _SEC.get(name, "") or os.environ.get(name, "")

# MQTT Broker Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# Topics (theo Phụ lục B đề cương)
TOPIC_MOVE   = "panda/cmd/move"
TOPIC_ARM    = "panda/cmd/arm"
TOPIC_FACE   = "panda/cmd/face"
TOPIC_TEXT   = "panda/cmd/text"
TOPIC_BUZZ   = "panda/cmd/buzz"
TOPIC_STATUS = "panda/status"
TOPIC_VOICE_LOG     = "panda/log/voice"
TOPIC_VOICE_PARTIAL = "panda/log/voice_partial"
TOPIC_AI_THINKING   = "panda/ai/thinking"
TOPIC_AI_RESPONSE   = "panda/ai/response"
TOPIC_AI_STATE      = "panda/ai/state"
TOPIC_AI_TOPIC      = "panda/ai/topic"        # chủ đề câu hỏi → emoji OLED
TOPIC_BROWSER_AUDIO = "panda/ai/voice_audio"   # push-to-talk từ dashboard (base64 webm)
TOPIC_BROWSER_CLIP  = "panda/ai/clip"          # clip PCM từ live-mic trình duyệt
TOPIC_MIC_LIVE      = "panda/ai/mic_live"      # trạng thái live-mic on/off
TOPIC_CAMERA = "panda/camera"

# AI Models Configuration
WEBCAM_INDEX = 0
YOLO_MODEL   = "yolov8n-pose.pt" # pose model
EMOTION_MODEL = "emotion-ferplus-8.onnx"

# Webcam index or an ESP32-CAM MJPEG / RTSP URL.
VISION_SOURCE = os.environ.get("PANDA_CAMERA_SOURCE", str(WEBCAM_INDEX))
VISION_WIDTH = 640
VISION_HEIGHT = 480
VISION_AI_FPS = 10
VISION_STREAM_FPS = 12
VISION_POSE_FPS = 5
VISION_IDENTITY_FPS = 1
VISION_EMOTION_FPS = 3
VISION_FACE_WIDTH = 320
VISION_FACE_DETAILS_ENABLED = True
VISION_FACE_DETAILS_MODEL = "face_landmarker.task"
VISION_HEAD_NOD_DEGREES = 8.0
VISION_HEAD_SHAKE_DEGREES = 10.0
VISION_DRAW_SKELETON = True
VISION_HANDS_ENABLED = True
VISION_HANDS_MODEL = "hand_landmarker.task"
VISION_HANDS_FPS = 5
VISION_OBJECTS_ENABLED = True
VISION_OBJECTS_MODEL = "yolov8n.pt"
VISION_OBJECTS_FPS = 1
VISION_EAR_CLOSED = 0.19
VISION_EAR_OPEN = 0.23
VISION_EYES_CLOSED_SEC = 1.5
# Approximate distance until calibrated: assumed camera HFOV and face width.
VISION_CAMERA_HFOV = 60.0
VISION_FACE_WIDTH_CM = 14.0
# Calibration: known distance_cm * detected_face_width_px / frame_width_px.
VISION_DISTANCE_SCALE_CM = float(os.environ.get("PANDA_DISTANCE_SCALE_CM", "0")) or None
VISION_POSE_ENABLED = True
VISION_POSE_SIZE = 320
VISION_DEVICE = "cpu"  # CUDA: "0"
VISION_CV_THREADS = 2
VISION_STALE_SEC = 2.0
VISION_FACE_THRESHOLD = 0.8
VISION_IDENTITY_THRESHOLD = 0.363
VISION_EMOTION_THRESHOLD = 0.55
VISION_EMOTION_MARGIN = 0.15
VISION_MIN_FACE_SIZE = 60
VISION_KEYPOINT_THRESHOLD = 0.5
TOPIC_VISION_STATUS = "panda/vision/status"

# Other constants
FPS_LIMIT = 15

# ─── Fish Audio TTS ───────────────────────────────────────────────────────────
# Lấy API key tại: https://fish.audio/app/api-keys/  (điền vào config/secrets.py)
FISH_AUDIO_API_KEY = _key("FISH_AUDIO_API_KEY")

# Tùy chọn: Reference ID của giọng muốn dùng (để trống = giọng mặc định)
# Tìm giọng Việt đẹp tại: https://fish.audio/  → copy Reference ID
FISH_VOICE_ID = "381620020029495883d03b63850c862f"

# Model TTS: 's2.1-pro-free' = miễn phí (khuyên dùng) | 's2.1-pro' / 's2-pro' / 's1' = trả phí
FISH_TTS_MODEL = "s2.1-pro-free"

# ─── DeepSeek API (LLM) ─────────────────────────────────────────────────────
# Lấy key tại: https://platform.deepseek.com/api_keys
# Để trống nếu hết credit → tự động fallback sang Groq LLM bên dưới
DEEPSEEK_API_KEY = _key("DEEPSEEK_API_KEY")   # ← hết credit, dùng Groq thay thế
GROQ_LLM_MODEL   = "openai/gpt-oss-120b"  # Model Groq: phản hồi trực tiếp, tiếng Việt chuẩn, không bị kẹt think tags

# Model cho tác vụ NHỎ (sửa lỗi ASR, caption OLED, chọn cảm xúc):
# groq/compound-mini = nhanh, trả lời trực tiếp không reasoning leak (đo 1.6s vs 2-4s của gpt-oss)
QUICK_MODEL = "groq/compound-mini"

# ─── Groq API (Whisper STT) ──────────────────────────────────────────────────
# ─── STT (Speech-to-Text) ────────────────────────────────────────────────────
# Groq Whisper large-v3-turbo — chính xác nhất, ~0.1s/clip, MIỄN PHÍ
# Lấy key tại: https://console.groq.com/keys  (điền vào config/secrets.py)
GROQ_API_KEY = _key("GROQ_API_KEY")

# Ngôn ngữ nhận dạng giọng nói (STT):
#   "vi" = tiếng Việt (KHUYẾN DỤNG cho Panda — chính xác nhất và nhanh gấp đôi,
#          đã đo: 0.48s so với 1.02s của auto; auto hay đoán nhầm sang tiếng khác
#          với clip ngắn: "Panda ơi" → "Bonne t'en la vie!")
#   None = tự động phát hiện (chỉ dùng nếu cần hội thoại tiếng Anh thật sự)
#   "en" = luôn tiếng Anh
STT_LANGUAGE = "vi"

# ─── Tinh chỉnh STT/VAD (kiểu Anki Vector) ────────────────────────────────────
# Model Groq Whisper: large-v3-turbo = nhanh + chính xác nhất trên Groq
STT_MODEL = "whisper-large-v3-turbo"

# Model cho pass CÂU HỎI: turbo nhanh (~1s) — độ chính tả đã có lớp sửa lỗi ASR lo
STT_MODEL_QUESTION = "whisper-large-v3-turbo"

# Khử ồn tĩnh (quạt/điều hòa) trước khi gửi audio lên Groq —
# tương đương lớp Noise Suppression mà Google Dịch dùng trong trình duyệt.
# ⚠️ CHỈ BẬT khi tín hiệu THÔ và MẠNH (giọng ≥0.3 RMS — đã tắt Enhance Voice
# Recognition): spectral gating xóa ồn quạt mà KHÔNG nuốt giọng.
# Nếu mic lại bị hãng bóp (giọng yếu 0.03–0.06) → trả về False kẻo nuốt giọng.
DENOISE_BEFORE_STT = True

# Ngưỡng năng lượng RMS tối thiểu để coi là tiếng nói (lọc ồn nền: quạt, điều hòa).
# Tăng lên (vd 0.05) nếu môi trường quá ồn gây false-trigger; giảm (0.02) nếu nói nhỏ.
VAD_NOISE_FLOOR = 0.03

# Hệ số nhân ồn nền cho ngưỡng thích nghi: 2.0 = nhạy (giọng xa), 3.0 = chống ồn mạnh.
VAD_AMBIENT_MULT = 2.0

# Độ phẳng phổ tối đa để coi là giọng nói (0→1).
# Giọng nói có hài âm ≈ 0.1–0.4; tiếng quạt/gió/phím ≈ 0.6–0.9.
# Giảm xuống (0.45) nếu quạt vẫn lọt; tăng lên (0.65) nếu giọng bạn bị gạt nhầm.
SPEECH_FLAT_MAX = 0.55

# Im lặng (giây) để kết thúc 1 clip khi standby — nhỏ = phản hồi wake-word nhanh.
WAKE_SILENCE_SEC = 0.9

# Giới hạn độ dài câu hỏi (giây) — trần chống kẹt 20s khi phòng có tiếng TV/media
# (media to ngang giọng → VAD không thấy im lặng để chốt sớm)
QUESTION_MAX_SEC = 10.0

# Thời gian hiển thị câu hỏi trên OLED trước khi LLM chạy (giây) — giữ nhỏ để giảm lag
QUESTION_DISPLAY_SEC = 0.4

# ─── Chống vòng lặp chào hỏi (vision) ─────────────────────────────────────────
# Sau một lần chào, không chào lại trong khoảng này dù face detection nhấp nháy
GREET_COOLDOWN_SEC = 60.0
# Phải mất khuôn mặt LIÊN TỤC bao lâu mới coi là người đã rời đi (reset greeted)
PERSON_LOST_GRACE_SEC = 10.0


# ─── Wake-word on-device (Porcupine — tùy chọn, kiểu Anki Vector) ─────────────
# Bắt "Panda" bằng âm học trên máy, không phụ thuộc ngôn ngữ & không cần mạng.
# LƯU Ý: console.picovoice.ai hiện CHỈ nhận email công ty — người dùng cá nhân
# (Gmail...) không đăng ký được. Khi đó cứ để trống: hệ thống tự dùng
# fallback Whisper dual-pass + fuzzy matching (vẫn bắt tốt "Panda").
# Cách kích hoạt (nếu có email công ty): xem server/wakeword.py
PICOVOICE_ACCESS_KEY = ""
PANDA_PPN_PATH = ""   # để trống = mặc định server/panda.ppn


# ─── Wake-word ───────────────────────────────────────────────────────────────
# Groq Whisper large-v3-turbo nhận dạng rất chính xác nên chỉ cần
# các dạng phổ biến. Thêm vào nếu thấy bị sót trong thực tế.
PANDA_WAKE_WORDS = [
    # ── Chuẩn tiếng Anh & Việt ───────────────────────────────────────────
    "panda",
    "hey panda",
    "panda ơi",
    "này panda",
    "ê panda",
    "ơi panda",
    "pan đa",
    "pan đa ơi",
    "păng đa",
    "păng đa ơi",
    # ── Các biến thể phiên âm tiếng Việt Whisper hay nhận nhầm ───────────
    "hai phan ta",
    "hai phanta",
    "hai phan đa",
    "hai panda",
    "hai păng đa",
    "hai bạn nàng",
    "bạn nàng",
    "ban nang",
    "hây panda",
    "hê panda",
    "hây phan ta",
    "hê phan ta",
    "phan ta",
    "phan da",
    "phan đã",
    "phanta",
    "fanta",
    "phan đa",
    "fan đa",
    "panta",
    "pandas",
    "ban đa",
    "băng đa",
    "băn đa",
    # ── Tên thân thiện tiếng Việt ────────────────────────────────────────
    "gấu trúc ơi",
    "gấu trúc",
    "bé panda ơi",
    "bé panda",
    "bé gấu",
]


# Mirror cảm xúc người dùng lên OLED khi idle:
#   False = idle TỰ CHỦ (Panda tự diễn biểu cảm, không nhại theo mặt người dùng) ← mặc định
#   True  = OLED nhại cảm xúc người dùng (đồng cảm trực tiếp)
EMOTION_MIRROR = False

# Im lặng (giây) để kết thúc câu hỏi — endpointer nhanh kiểu Google
QUESTION_SILENCE_SEC = 1.6

# ─── Microphone ───────────────────────────────────────────────────────────────
# None = tự động dò và chọn micro có tín hiệu (khuyên dùng — bỏ qua mic bị mute).
# Để chọn thủ công, liệt kê thiết bị bằng lệnh:
#   python -c "import sounddevice; print(sounddevice.query_devices())"
# rồi điền index của micro mong muốn, ví dụ: MIC_DEVICE_INDEX = 2
MIC_DEVICE_INDEX = None

# Nguồn giọng nói cho não:
#   "auto"   = mic cục bộ + clip từ browser/robot qua MQTT   ← dev hiện tại
#   "local"  = chỉ mic cục bộ
#   "remote" = CHỈ clip qua MQTT — khi não lên cloud, hoặc khi test đường
#              robot bằng dev_mic_bridge (mic laptop giả lập mic robot)
MIC_SOURCE = "auto"
