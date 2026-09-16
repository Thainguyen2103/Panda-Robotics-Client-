# Moon Voice trên dashboard

Test trực tiếp trong dashboard hiện tại, ô **Moon Voice**. Microphone →
WebSocket cùng origin `/voice/ws` → Python Voice → STT; không gửi audio tới
MQTT hoặc Brain/LLM. Giữ microphone mở liên tục cả khi gọi STT.
Các phần điều khiển, camera, OLED và Monitor của dashboard vẫn giữ nguyên.

## Live Talk: Gemini Native Audio

Mục **Live Talk** là chế độ riêng nằm dưới Moon Voice. Chế độ này gửi PCM mono
16 kHz qua WebSocket cùng origin `/live/ws`; Node giữ API key và mở phiên Gemini
Live. Gemini nhận audio và trả audio PCM 24 kHz trực tiếp, không chạy pipeline
STT → LLM → TTS của Brain. Dashboard không hiện transcript; OLED chỉ nhận một
trong 11 biểu cảm qua function call `set_expression`.

Thêm key vào file không được Git theo dõi `config/secrets.py`:

```python
SECRETS = {
    # các key hiện có...
    "GEMINI_API_KEY": "key-cua-ban",
}
```

Sau đó chạy lại `start.bat`, mở dashboard và bấm **Bắt đầu Live Talk**. Có thể
đặt biến môi trường `GEMINI_API_KEY` thay cho file. Mặc định dùng model
`gemini-3.8-live` và voice `Kore`; có thể đổi bằng `GEMINI_LIVE_MODEL` và
`GEMINI_LIVE_VOICE` trước khi chạy Node.

Live Talk và Moon Voice dùng chung Web Lock `moon-voice-microphone`, vì vậy chỉ
một chế độ hoặc một tab giữ mic. Khi bật Live Talk, mic wake-word cũ tự dừng.
AEC, khử nhiễu và AGC của trình duyệt được bật để giảm việc Moon tự nghe loa.
Khi người dùng nói chen, client xóa ngay hàng đợi audio cũ. Khi phát xong, OLED
trở lại `neutral`. API key không được đưa vào HTML/JavaScript trình duyệt, log
hoặc MQTT.

Một số driver/Chrome noise suppression tạo frame im lặng toàn bit `0`; Gemini
đóng phiên với mã `1007` nếu nhận request audio kiểu này. Bridge chỉ thay đúng
frame digital-silence đó bằng dither ±1 LSB không nghe thấy để VAD vẫn nhận được
nhịp im lặng; mọi frame có tín hiệu được chuyển nguyên vẹn.

Kiểm thử cầu nối không gọi API và không dùng quota:

```powershell
node tests/test_gemini_live_bridge.cjs
```

## Chạy trên Windows

Dùng Python **3.12 hoặc 3.13** để có wheel WebRTC VAD sẵn, không cần C++ Build Tools.
Từ thư mục gốc project:

```powershell
npm --prefix web install
py -3.12 -m venv .voice-venv
.\.voice-venv\Scripts\python.exe -m pip install -r requirements-voice.txt
# Nếu chưa có config/secrets.py, sao chép config/secrets.example.py và điền GROQ_API_KEY.
.\start-voice.bat
```

Mở [Dashboard](http://localhost:3000) trong Chrome/Edge. Lần đầu cần bấm
**Bật microphone** để cấp quyền, giữ im lặng 1.8 giây để đo nền rồi mới gọi Moon.
Các lần tải trang sau mic tự bật khi quyền vẫn được cấp; bấm **Dừng mic** để tắt
tự động. Có thể đổi thiết bị sau khi dừng.
Chỉ một tab Moon được giữ microphone. Nếu `start.bat` mở tab mới trong khi tab
cũ vẫn nghe, tab mới sẽ báo đang dùng mic ở tab khác thay vì tranh mic và làm
ngắt phiên wakeword.
Nút **Thử tiếng tick** kiểm tra loa; mỗi wake thật phát tiếng tick 80ms. Không chạy `start.bat` cho
bài test này vì lệnh đó khởi động toàn bộ Brain.

## Hai chế độ wakeword

- **Porcupine**: phát hiện âm học trên máy, báo wake ngay khi engine phát hiện,
  không đợi STT. Cài `pip install pvporcupine` bằng Python trong `.voice-venv`;
  tạo keyword **Moon** trong [Picovoice Console](https://console.picovoice.ai/),
  tải model đúng hệ điều hành/kiến trúc về `server/moon.ppn`;
  điền `PICOVOICE_ACCESS_KEY` trong `config/secrets.py`. Có thể dùng biến môi trường
  `MOON_PPN_PATH` trỏ đến model. Đổi tên file model Panda không biến nó thành model Moon.
- **Whisper dự phòng**: dùng ngay khi có Groq key, không cần `.ppn`. Pass
  tiếng Việt làm nhận dạng chính. Nếu kết quả rỗng hoặc là một biến thể hẹp
  mà Whisper hay ghi cho Moon (Mun/Mùn/Muôn), server chạy thêm pass tiếng Anh
  trên cùng audio và chỉ wake khi pass này xác nhận token Moon. Các từ Việt thật
  “muốn/môn/món” bị loại trước bước xác minh. Dashboard hiện kết quả
  pass đầu trong mục chẩn đoán để tinh chỉnh theo mic/giọng thật.

Dashboard luôn hiện chế độ thực tế. Key/model có cấu hình nhưng lỗi sẽ báo lỗi;
không âm thầm giả vờ đang chạy Porcupine.

## Những gì cần quan sát

1. Nói “Moon”, nghe tiếng tick, xem số lần wake tăng, sau đó
   chờ dòng **Moon đang nghe — hãy nói câu hỏi**.
2. Nói “Hôm nay tôi muốn học tiếng Anh”. Text xuất hiện trong ô câu nói;
   nhật ký giữ bản STT nguyên văn, độ dài audio và thời gian API xử lý.
3. Thử nói liền “Moon, hôm nay trời đẹp quá”; không cần mở lại mic.
4. Thử 20 lần mỗi điều kiện: phòng yên, bật quạt, nói nhỏ, cách mic 0.5–1m.
   Ghi số wake đúng/bỏ sót/nhận nhầm, thời gian cảm nhận và lỗi text.
5. Để im lặng 60 giây, gõ bàn phím, rồi nói câu không có Moon. Kiểm tra wake giả.
6. Sau wake không nói: khoảng 12 giây sau trở lại chờ. Thử dừng/bật lại mic,
   từ chối quyền mic, ngắt mạng và khôi phục mạng.

Âm thanh được gửi tới Groq để STT; không lưu file và không gửi raw audio qua
MQTT. Khi chạy đầy đủ bằng `start.bat`, text câu hỏi đã xác nhận được chuyển qua
MQTT tới Brain để chạy LLM, TTS và OLED. `start-voice.bat` chỉ khởi động web +
Voice service nên vẫn dùng được để test STT độc lập, nhưng không có câu trả lời AI.
Trong lúc Moon phát câu chào hoặc TTS, mic web tự tạm nghỉ và bỏ mọi audio/STT
đang chờ; sau khi loa im 1.2 giây mic mới nghe lại để tránh Moon tự gọi chính mình.
Nhật ký tối đa 60 mục nằm trong trang. Tắt mic đóng socket và hủy yêu cầu STT
đang chờ. Thu âm dùng AEC/NS của trình duyệt, tắt AGC để tránh khuếch đại quạt,
lọc high-pass 150Hz và hiệu chuẩn nền 1.8 giây, PCM mono 16kHz,
WebRTC VAD, pre-roll 300ms, onset 3/5 frame, tối thiểu 180ms giọng nói.
Câu sau wake kết thúc sau 1,2 giây im lặng, giới hạn 15 giây mỗi đoạn.
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
node tests/test_voice_bridge.cjs
node tests/test_gemini_live_bridge.cjs
```

Test xác minh segmentation, tiếng click/im lặng, wake token, STT chậm/lỗi,
timeout, reblocking Porcupine, WebSocket và resampling 16/44.1/48kHz.
Kết quả mock/synthetic không phải chứng nhận độ chính xác wake/STT ngoài đời.

Tên hiển thị, persona AI và cấu hình đã chuyển sang Moon. `panda/*` vẫn là
hợp đồng MQTT để tương thích firmware hiện tại; thư mục firmware không sửa.
Biến môi trường vision mới: `MOON_CAMERA_SOURCE`, `MOON_DISTANCE_SCALE_CM`.

Tham khảo: [Groq STT và confidence metadata](https://console.groq.com/docs/speech-to-text),
[Porcupine frame length, sample rate và sensitivity](https://picovoice.ai/docs/api/porcupine-python/).

Sau cập nhật chống nhiễu: ngưỡng RMS bằng tối thiểu cấu hình hoặc 2.2 lần nền
(percentile 80). Đổi quạt/vị trí cần dừng và bật mic để đo lại. Giọng nhỏ hơn
ngưỡng có thể bị bỏ sót; xem mức nền/ngưỡng trên trang để điều chỉnh vị trí mic.
Text không có Moon khi standby chỉ hiện ở ô chẩn đoán “Bỏ qua”, không vào
nhật ký câu nhận diện. Đây là phân loại kết quả, không phải bằng chứng đã
khử hết tiếng ồn. Kết quả chứa segment confidence thấp bị từ chối.

`start-voice.bat` chạy web dashboard; Node tự khởi động Python Voice khi
port 8765 chưa có service. Port 8765 chỉ là backend nội bộ; đường `/` cũ
chuyển tới dashboard 3000. Không còn trang test Voice riêng.
Text câu sau wake hiện ở **Bạn đã nói**, OLED mô phỏng và Activity Log.
Transcript thô/chẩn đoán nằm trong mục mở rộng ngay dưới các nút mic.

Khi bật mic web, dashboard bỏ qua AI/state/thinking/response từ MQTT để
không ghi đè phiên test. Khi mic web chưa bật hoặc đã dừng, dashboard theo
Brain qua MQTT và hiển thị đầy đủ câu hỏi → suy nghĩ → nói → standby. OLED hiển thị transcript 6 giây rồi về mắt; câu đầy đủ
vẫn giữ trong khung Bạn đã nói. Chữ dài xuống dòng, có thể cuộn trong OLED.
Kiểm tra hồi quy giao diện: `node tests/test_voice_display.cjs` (cần Playwright).

Dòng Nguồn hiển thị cho biết bên nào đang điều khiển OLED. Khi nhận xong câu
hỏi, Voice tạm nghỉ mic để Brain điều khiển OLED, gọi LLM/TTS và tránh tự nghe
tiếng loa; Brain về standby thì mic web tự nghe lại. Nếu Brain không phản hồi
trong 60 giây, dashboard tự trả mic về chế độ chờ Moon.
