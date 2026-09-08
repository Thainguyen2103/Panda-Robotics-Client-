# Moon Voice Lab

Chạy riêng để đánh giá wakeword và STT; không khởi động Brain, MQTT, camera,
LLM, TTS hoặc firmware. Giữ microphone trình duyệt mở liên tục cả khi gọi STT.

## Chạy trên Windows

Dùng Python **3.12 hoặc 3.13** để có wheel WebRTC VAD sẵn, không cần C++ Build Tools.
Từ thư mục gốc project:

```powershell
py -3.12 -m venv .voice-venv
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-voice.txt
# Nếu chưa có config/secrets.py, sao chép config/secrets.example.py và điền GROQ_API_KEY.
.\start-voice.bat
```

Mở [Voice Lab](http://localhost:8765) trong Chrome/Edge, bấm **Bật microphone**,
cho phép dùng mic. Có thể đổi thiết bị sau khi dừng. Không chạy `start.bat` cho
bài test này vì lệnh đó khởi động toàn bộ Brain.

## Hai chế độ wakeword

- **Porcupine**: phát hiện âm học trên máy, báo wake ngay khi engine phát hiện,
  không đợi STT. Cài `pip install pvporcupine` bằng Python trong `.voice-venv`;
  tạo keyword **Moon** trong [Picovoice Console](https://console.picovoice.ai/),
  tải model đúng hệ điều hành/kiến trúc về `server/moon.ppn`;
  điền `PICOVOICE_ACCESS_KEY` trong `config/secrets.py`. Có thể dùng biến môi trường
  `MOON_PPN_PATH` trỏ đến model. Đổi tên file model Panda không biến nó thành model Moon.
- **Whisper dự phòng**: dùng ngay khi có Groq key, không cần `.ppn`. Gửi một lượt
  STT sau 450ms ngắt câu; thời gian wake còn phụ thuộc mạng/API. Chỉ khớp từ Moon
  hoàn chỉnh, không coi “muốn/môn/món” là tên robot. Không dùng prompt mớm tên,
  fuzzy matching hay LLM sửa lời nói. Chế độ này có thể bỏ sót nếu Whisper viết
  sai tên, và không có độ trễ tức thì như mô hình âm học.

Trang luôn hiện chế độ thực tế. Key/model có cấu hình nhưng lỗi sẽ báo lỗi;
không âm thầm giả vờ đang chạy Porcupine.

## Những gì cần quan sát

1. Nói “Moon”, xem số lần wake tăng và trạng thái **Đã nghe Moon**.
2. Nói “Hôm nay tôi muốn học tiếng Anh”. Text xuất hiện trong ô câu nói;
   nhật ký giữ bản STT nguyên văn, độ dài audio và thời gian API xử lý.
3. Thử nói liền “Moon, hôm nay trời đẹp quá”; không cần mở lại mic.
4. Thử 20 lần mỗi điều kiện: phòng yên, bật quạt, nói nhỏ, cách mic 0.5–1m.
   Ghi số wake đúng/bỏ sót/nhận nhầm, thời gian cảm nhận và lỗi text.
5. Để im lặng 60 giây, gõ bàn phím, rồi nói câu không có Moon. Kiểm tra wake giả.
6. Sau wake không nói: khoảng 8 giây sau trở lại chờ. Thử dừng/bật lại mic,
   từ chối quyền mic, ngắt mạng và khôi phục mạng.

Âm thanh được gửi tới Groq để STT; không lưu file audio, không gửi qua MQTT.
Nhật ký tối đa 60 mục nằm trong trang. Tắt mic đóng socket và hủy yêu cầu STT
đang chờ. Thu âm dùng DSP của trình duyệt (AEC/NS/AGC), PCM mono 16kHz,
WebRTC VAD, pre-roll 300ms, onset 3/5 frame, tối thiểu 180ms giọng nói.
Câu sau wake kết thúc sau 850ms im lặng, giới hạn 15 giây mỗi đoạn.
Hàng đợi giới hạn 3 đoạn; mạng quá chậm sẽ báo lỗi và dừng thay vì phát text cũ.

Tinh chỉnh `VOICE_*`, `WAKE_SENSITIVITY` trong `config/settings.py` rồi restart.
Độ nhạy cao hơn có thể tăng nhận nhầm. VAD không tách được giọng người dùng khỏi
TV hoặc người khác nói gần mic; cần đánh giá bằng mic và môi trường thật.

## Kiểm thử tự động

```powershell
.\.voice-venv\Scripts\python.exe -m unittest discover -s tests -p "test_voice*.py" -v
node tests/test_voice_worklet.cjs
node tests/test_vision_ui.cjs
# Khi có Playwright và Edge, chạy server rồi test mic giả (không gửi audio cloud):
node tests/test_voice_browser.cjs
```

Test xác minh segmentation, tiếng click/im lặng, wake token, STT chậm/lỗi,
timeout, reblocking Porcupine, WebSocket và resampling 16/44.1/48kHz.
Kết quả mock/synthetic không phải chứng nhận độ chính xác wake/STT ngoài đời.

Tên hiển thị, persona AI và cấu hình đã chuyển sang Moon. `panda/*` vẫn là
hợp đồng MQTT để tương thích firmware hiện tại; thư mục firmware không sửa.
Biến môi trường vision mới: `MOON_CAMERA_SOURCE`, `MOON_DISTANCE_SCALE_CM`.

Tham khảo: [Groq STT và confidence metadata](https://console.groq.com/docs/speech-to-text),
[Porcupine frame length, sample rate và sensitivity](https://picovoice.ai/docs/api/porcupine-python/).
