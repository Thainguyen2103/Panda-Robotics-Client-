# Moon Live Voice trên dashboard

Dashboard chỉ còn một khu vực **Live Voice**. Khi phiên được kích hoạt, Moon trò
chuyện liên tục cho tới khi người dùng bấm **Kết thúc**; không còn luồng cũ yêu
cầu gọi wakeword trước từng câu hỏi. Camera, OLED, điều khiển và Monitor vẫn giữ
nguyên. OLED chỉ thể hiện trạng thái/biểu cảm phù hợp.

## Gemini Live + Fish Voice

Live Voice gửi PCM mono
16 kHz qua WebSocket cùng origin `/live/ws`; Node giữ API key và mở phiên Gemini
Live. Gemini hiểu audio trực tiếp, không chạy Groq/Whisper STT và không dùng
pipeline Voice của Brain. Chế độ mặc định lấy transcript nội bộ của chính câu
trả lời Gemini rồi tạo MP3 bằng Fish Audio để giữ cùng giọng Moon; transcript
này không hiển thị trên dashboard. Vì phải chờ đủ câu rồi mới gọi Fish, phản hồi
chậm hơn Gemini Native và sử dụng quota Fish. OLED chỉ nhận một trong 11 biểu cảm
qua function call `set_expression`.

Menu **Giọng trả lời** có hai lựa chọn:

- **Fish Voice** (mặc định): cùng `FISH_VOICE_ID` và `FISH_TTS_MODEL` với TTS hiện có.
- **Gemini Native**: phát PCM trực tiếp bằng giọng `Kore`, nhanh hơn và không gọi Fish.

Ở Fish Voice, bridge vẫn giữ audio Gemini của từng câu trong bộ nhớ. Nếu Fish
 timeout/lỗi hoặc trình duyệt không giải mã được MP3, câu đó tự chuyển sang giọng
Gemini thay vì im lặng; câu kế tiếp vẫn thử Fish như bình thường.

### Hai cách kích hoạt

Menu **Cách kích hoạt** có hai lựa chọn dùng chung một phiên Live Voice:

- **Bật trực tiếp**: bấm nút để Moon bắt đầu nghe và trò chuyện ngay.
- **Chờ “Hey Moon” rồi trò chuyện**: microphone trước tiên chỉ chạy bộ nhận
  wakeword. Khi nhận đúng “Hey Moon”, dashboard phát hai tiếng tick xác nhận và
  chuyển chính microphone đó sang hội thoại liên tục. Sau lần kích hoạt này không
  cần gọi Moon lại; bấm **Kết thúc** để đóng phiên.

Sau khi bấm chế độ chờ, giữ im lặng trong lúc giao diện báo **Đang đo tiếng
nền**. Chỉ gọi “Hey Moon” khi dòng trạng thái đổi thành **Sẵn sàng**; giai đoạn
hiệu chuẩn wakeword kéo dài khoảng 0,9 giây.

Wakeword chỉ là cổng kích hoạt, không còn tự thu một câu rồi gửi qua pipeline cũ.
Chế độ chờ giữ audio ngoài Gemini/Brain cho tới khi wakeword được xác nhận.
`brain.py` không mở microphone/wakeword nền riêng; nếu không, hai pipeline sẽ
cùng nghe và Brain có thể trả lời trong khi thẻ Live Voice vẫn đang chờ.

Gemini dùng VAD tự động với ngưỡng nhạy cho hội thoại. Dashboard còn có một lớp
dự phòng: khi đã nghe tiếng nói và gặp khoảng 0,9 giây im lặng, nó gửi tín hiệu
kết thúc luồng audio hiện tại để Gemini chốt câu và bắt đầu trả lời; microphone
vẫn tiếp tục dùng cho câu kế tiếp.

Khi kết thúc một phiên và đổi từ Fish Voice sang Kore (hoặc ngược lại), hàng đợi
phát và mốc thời gian AudioContext được đặt lại trước phiên mới để audio không bị
lên lịch ở một thời điểm cũ rồi tạo cảm giác mất tiếng.

### So sánh Gemini Live và Brain Pipeline

Menu **Hệ thống xử lý** trong cùng thẻ Live Talk cho phép thử hai kiến trúc bằng
cùng microphone:

- **Gemini Live — audio native**: Gemini nghe và tạo câu trả lời; có thể chọn
  Fish Voice hoặc giọng Gemini Native.
- **Brain Pipeline — STT → LLM → Fish**: VAD chia câu, Groq Whisper nhận diện,
  `brain.py` xử lý bằng LLM hiện tại và Fish phát giọng. Sau khi được bật trực
  tiếp hoặc bằng wakeword, đây là một phiên liên tục.

Ô **Nhận diện gần nhất** cho biết hệ thống nghe được gì. Ô **Độ trễ** hiển thị
thời gian STT và thời gian từ lúc chốt câu tới lúc bắt đầu trả lời. Nên hỏi cùng
một bộ 10–20 câu ở cả hai chế độ, cùng vị trí micro và mức tiếng ồn. Brain
Pipeline tự dừng mic khi xử lý/TTS và mở lại sau 1,2 giây để tránh nghe tiếng loa.

Thêm key vào file không được Git theo dõi `config/secrets.py`:

```python
SECRETS = {
    # các key hiện có...
    "GEMINI_API_KEY": "key-cua-ban",
    "FISH_AUDIO_API_KEY": "key-fish-cua-ban",
}
```

Sau đó chạy lại `start.bat`, mở dashboard, chọn cách kích hoạt rồi bấm nút bắt
đầu. Có thể
đặt biến môi trường `GEMINI_API_KEY`/`FISH_AUDIO_API_KEY` thay cho file. Fish Voice
đọc `FISH_VOICE_ID` và `FISH_TTS_MODEL` trong `config/settings.py`; có thể đặt
`FISH_VOICE_ID` và `FISH_LIVE_TTS_MODEL` bằng biến môi trường. Mặc định Gemini
dùng model `gemini-3.8-live` và voice nội bộ `Kore`; có thể đổi bằng
`GEMINI_LIVE_MODEL` và `GEMINI_LIVE_VOICE` trước khi chạy Node.

Live Voice dùng Web Lock `moon-voice-microphone`, vì vậy chỉ một tab được giữ
mic. Khi wakeword đã được nhận, socket chờ được đóng trước khi socket hội thoại
được mở; trình duyệt không xin lại quyền hay mở microphone lần thứ hai.
AEC, khử nhiễu và AGC của trình duyệt được bật để giảm việc Moon tự nghe loa.
Khi người dùng nói chen, client xóa ngay hàng đợi audio cũ. Khi phát xong, OLED
trở lại `neutral`. API key không được đưa vào HTML/JavaScript trình duyệt, log
hoặc MQTT.

Một số driver/Chrome noise suppression tạo frame im lặng toàn bit `0`; Gemini
đóng phiên với mã `1007` nếu nhận request audio kiểu này. Bridge chỉ thay đúng
frame digital-silence đó bằng dither ±1 LSB không nghe thấy để VAD vẫn nhận được
nhịp im lặng; mọi frame có tín hiệu được chuyển nguyên vẹn.

Không bật `enableAffectiveDialog` trong setup: endpoint có thể chấp nhận bắt tay
nhưng đóng mã `1007` ngay khi audio đầu tiên tới trên một số project/quota. Moon
vẫn chọn biểu cảm OLED bằng system prompt và function call `set_expression`.

Kiểm thử cầu nối không gọi API và không dùng quota:

```powershell
node tests/test_gemini_live_bridge.cjs
node tests/test_gemini_live_fish.cjs
node tests/test_fish_tts.cjs
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

Mở [Dashboard](http://localhost:3000) trong Chrome/Edge. Lần đầu cần bấm nút bắt
đầu để cấp quyền microphone. Chọn **Bật trực tiếp** hoặc **Chờ “Hey Moon” rồi
trò chuyện**; có thể đổi thiết bị sau khi kết thúc phiên.
Chỉ một tab Moon được giữ microphone. Nếu `start.bat` mở tab mới trong khi tab
cũ vẫn nghe, tab mới sẽ báo đang dùng mic ở tab khác thay vì tranh mic và làm
ngắt phiên wakeword.
Mỗi wake thật phát một tick xác nhận, sau đó tick thứ hai báo phiên hội thoại đã
sẵn sàng. Không chạy `start.bat` cho bài test tự động vì lệnh đó khởi động toàn
bộ Brain.

## Hai engine wakeword

- **Porcupine**: phát hiện âm học trên máy, báo wake ngay khi engine phát hiện,
  không đợi STT. Cài `pip install pvporcupine` bằng Python trong `.voice-venv`;
  tạo keyword **Moon** trong [Picovoice Console](https://console.picovoice.ai/),
  tải model đúng hệ điều hành/kiến trúc về `models/voice/moon.ppn`;
  điền `PICOVOICE_ACCESS_KEY` trong `config/secrets.py`. Có thể dùng biến môi trường
  `MOON_PPN_PATH` trỏ đến model. Đổi tên file model Panda không biến nó thành model Moon.
- **Whisper dự phòng**: dùng ngay khi có Groq key, không cần `.ppn`. Pass
  tiếng Việt làm nhận dạng chính. `Moon` chính xác hoặc cụm gọi rõ “Hey Moon”
  được kích hoạt ngay; các cách Whisper thường ghi thành “Hey múa/mưa” cũng
  được nhận ngay vì có tiền tố gọi rõ. Biến thể kém chắc chắn như `Mun` đứng một
  mình mới chạy pass tiếng Anh và bị giới hạn bốn giây, nên giao diện không thể
  kẹt ở **Đang xác minh**. Các câu Việt bình thường như “trời mưa”, cùng các từ
  “muốn/môn/món”, không kích hoạt Moon. Dashboard hiện kết quả pass đầu trong
  mục chẩn đoán để tinh chỉnh theo mic/giọng thật.

### Ngôn ngữ phản hồi

Brain/LLM và Gemini Live đều xét ngôn ngữ của **lượt nói mới nhất**, không lấy
ngôn ngữ trong lịch sử làm mặc định. Câu tiếng Việt được đáp bằng tiếng Việt;
câu tiếng Anh được đáp bằng tiếng Anh. Với câu code-switch, Moon chọn ngôn ngữ
chính nhưng giữ hoặc dùng thuật ngữ tiếng Anh khi tự nhiên và rõ nghĩa hơn cách
dịch gượng ép. Moon không lặp câu trả lời thành hai bản dịch trừ khi người dùng
yêu cầu dịch. Bước sửa lỗi STT chỉ sửa cách viết và không được dịch câu.

Dashboard luôn hiện chế độ thực tế. Key/model có cấu hình nhưng lỗi sẽ báo lỗi;
không âm thầm giả vờ đang chạy Porcupine.

## Những gì cần quan sát

1. Chọn chế độ chờ, bấm bắt đầu, nói “Hey Moon” và nghe hai tiếng tick. Trạng
   thái phải chuyển từ **Chờ Moon** sang **Đang nghe** mà không quay về mặc định.
2. Hỏi nhiều câu liên tiếp mà không gọi Moon lại; phiên chỉ dừng khi bấm
   **Kết thúc** hoặc có lỗi kết nối.
3. Chọn bật trực tiếp và xác nhận Gemini/Brain được kết nối mà không mở socket
   wakeword.
4. Thử 20 lần mỗi điều kiện: phòng yên, bật quạt, nói nhỏ, cách mic 0.5–1m.
   Ghi số wake đúng/bỏ sót/nhận nhầm, thời gian cảm nhận và lỗi text.
5. Để im lặng 60 giây, gõ bàn phím, rồi nói câu không có Moon. Kiểm tra wake giả.
6. Sau wake không nói, phiên vẫn ở chế độ hội thoại liên tục. Thử kết thúc/bật
   lại, từ chối quyền mic, ngắt mạng và khôi phục mạng.

Trong thời gian chờ wakeword, audio được gửi tới Voice service để Porcupine hoặc
Groq xác nhận từ khóa. Sau khi thức, Gemini Live nhận audio trực tiếp; riêng Brain
Pipeline dùng Groq STT rồi chuyển text qua MQTT tới Brain/LLM và Fish. Raw audio
không đi qua MQTT. Khi Brain/Fish đang phát câu trả lời, luồng thu tạm nghỉ và mở
lại sau khi loa im để hạn chế Moon tự nghe chính mình. Bấm **Kết thúc** sẽ đóng
socket, dừng track microphone và hủy dữ liệu đang chờ.

Thu âm dùng AEC/khử nhiễu của trình duyệt, high-pass 120 Hz và PCM mono 16 kHz.
AGC bị tắt trong giai đoạn chờ để tránh tiếng động lớn giả làm wakeword; sau khi
chuyển sang hội thoại vẫn tái sử dụng track đang mở. Voice service dùng WebRTC
VAD, pre-roll và các ngưỡng trong `config/settings.py`.

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
Transcript gần nhất hiện trong thẻ Live Voice và Activity Log. Khi Live Voice
chạy, dashboard bỏ qua trạng thái MQTT có thể ghi đè phiên; sau khi kết thúc,
dashboard tiếp tục theo Brain qua MQTT. OLED chỉ hiển thị trạng thái và biểu cảm.
Kiểm tra hồi quy giao diện: `node tests/test_voice_display.cjs` (cần Playwright).
