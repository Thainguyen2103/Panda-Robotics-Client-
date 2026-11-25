# head-demo — đầu robot nói chuyện: camera + màn hình + loa

Bản demo cho thầy xem phần **đầu robot** chạy cùng **AI của Thái và Ngọc Anh**:

- **Màn hình** (giống `cam-emotion`): camera robot nhìn mặt bạn, AI cảm xúc của Thái đoán bạn
  đang vui/buồn/giận/ngạc nhiên…, màn robot vẽ khuôn mặt tương ứng.
- **Loa + mic**: bấm **phím cách (Space)**, nói vào **mic robot** (INMP441 trên đầu, dây nối ở
  mục 3). AI của nhóm nghe, hiểu, trả lời, và **giọng trả lời phát ra loa robot**. Trong lúc đó
  mặt robot đổi theo: **đang nghe → đang nghĩ → đang nói**. Chưa gắn mic thật thì chạy
  `chay-demo.bat --laptop-mic` để quay lại nói vào mic laptop như bản cũ.

> Không sửa dòng code nào của nhóm. Chương trình chỉ import và gọi các hàm có sẵn trong
> `Panda-Robotics-Client-/server/` (chương trình tự tìm: repo nhóm nằm cạnh thư mục này trong `MOON/`, hoặc thư mục này
> nằm sẵn trong repo nhóm ở `firmware/kt_firmware/head-demo/`).

---

## 1. Luồng chạy

```
 Bạn nói ──► MIC ROBOT (INMP441, I2S_NUM_0 trên ESP32-S3)
                │  micTask (main.cpp): đọc I2S, gửi PCM 16-bit lên laptop qua dây USB
                │  (khung "PNDM", chỉ gửi khi laptop bật bằng lệnh "mic on")
                ▼
             Voice._listen_robot_mic() (tools/head_demo.py): tự dừng khi im lặng ~1,5 giây
                │  Gemini Transcribe            (cùng model + cấu hình với dashboard: web/gemini-transcribe-bridge.js)
                ▼  đổi giọng nói thành chữ, tự nhận tiếng Việt / Anh / Nhật
             câu hỏi (chữ)
                │  engine.chat()                 (server/llm/engine.py — Ngọc Anh)
                ▼  từ điển / RAG bài học / LLM trả lời như gia sư cho bé
             câu trả lời (chữ)
                │  tools/moon_tts.py — 1 trong 2 giọng (bấm V để đổi):
                │    • Fish Audio s2.1-pro-free (giống web/fish-tts.js, giọng FISH_VOICE_ID / _JP)
                │    • giọng Gemini Kore (giống chế độ native của web/gemini-live-bridge.js)
                ▼
             MP3 ──► giải mã thành PCM 16-bit 16kHz (miniaudio)
                │  dây USB: "pcm <n>\n" + n byte, gửi đúng nhịp phát (32KB/giây)
                ▼
 ESP32-S3: bể chứa 32KB ──► audioTask ──► I2S ──► MAX98357 ──► LOA
```

Cùng lúc, camera vẫn gửi ảnh lên laptop, AI cảm xúc vẫn chạy. Khi robot đang nghe/nghĩ/nói thì
mặt robot theo trạng thái trò chuyện; xong thì quay lại "nhại" cảm xúc của bạn.

| Mặt robot | Khi nào | Chữ dưới mặt |
|---|---|---|
| `hearing` | đang ghi âm câu bạn nói | DANG NGHE... |
| `thinking` | AI đang nghĩ câu trả lời | DANG NGHI... |
| `speaking` | loa đang phát | MOON DANG NOI, hoặc từ vựng (vd `CAT / NE-KO`) nếu bạn hỏi từ vựng |
| mặt cảm xúc | lúc không trò chuyện | VUI, BUON, GIAN… như cam-emotion |

## 2. Vì sao làm như vậy

| Quyết định | Lý do |
|---|---|
| Âm thanh đi qua **dây USB** chung với ảnh | Dây 4Mbaud ≈ 400KB/giây. Ảnh dùng ~200KB/giây, giọng nói chỉ cần 32KB/giây, còn dư. Không cần WiFi. |
| Gửi âm thanh **đúng nhịp phát** (đi trước ~0,35 giây) | Bể chứa trên board chỉ 32KB (≈1 giây). Gửi một lần hết cả câu thì bể tràn, mất tiếng. |
| Board có **task âm thanh riêng** | `i2s_write()` đứng chờ loa phát. Nếu chạy trong `loop()` thì mặt robot đứng hình lúc robot nói. |
| Phát **stereo** (2 kênh cùng 1 mẫu) | Giống bài `hw-tests/speaker-only` đã test tốt. Chế độ mono `ONLY_LEFT` trên ESP32-S3 có lúc xếp sai khung, gây méo. |
| Nghe bằng **Gemini Transcribe** | Giống hệt dashboard của nhóm (model `gemini-3.5-transcribe-live`, 3 thứ tiếng, từ vựng riêng Moon/Kanji…), nên kết quả nhận dạng giống khi Thái demo trên web. |
| LLM **local** của Ngọc Anh (Ollama) | Đúng thiết kế trong `settings.py` của nhóm: LLM chạy trên laptop, không phụ thuộc mạng/quota. Chỉ khi chạy `--llm-online` mới dùng Groq/Gemini dự phòng. |
| Bấm **Space** để nói, không dùng từ gọi "Moon ơi" | Lớp học ồn, bấm phím chắc ăn hơn. Robot cũng không tự nghe lại tiếng loa của mình. |

## 3. Chuẩn bị (1 lần)

1. **Phần cứng:** board ESP32-S3 + camera + màn TFT (nối như `cam-emotion`) + MAX98357 + loa
   (BCLK 47, LRC 48, DIN 21, VIN 5V, GND) + **mic INMP441** (SCK 41, WS 40, SD 42, VDD 3V3,
   GND, L/R→GND để chọn kênh trái). Sơ đồ đầy đủ + lý do chọn 3 chân 40/41/42:
   `body-test/so-do-noi-day.html` mục 02b.
2. **Gemini key** (bắt buộc cho phần nghe, miễn phí): vào https://aistudio.google.com/apikey →
   tạo key → dán vào file **`head-demo/gemini-key.txt`** (chỉ 1 dòng). Hoặc xin Thái key nhóm
   đang dùng cho dashboard (`GEMINI_API_KEY` trong `config/secrets.py`).
   Tuỳ chọn: **`groq-key.txt`** (https://console.groq.com/keys) để LLM trả lời nhanh hơn.
   Các file key **không** đưa lên git.
3. **LLM local của Ngọc Anh (Ollama)**: `settings.py` của nhóm chạy LLM ngay trên laptop bằng
   Ollama, model `qwen3.5:2b` (chạy trên card NVIDIA, không gửi câu hỏi lên mạng).
   - Cài Ollama: https://ollama.com/download → bản Windows.
   - Tải model (1 lần, ~2GB): mở cmd, gõ `ollama pull qwen3.5:2b`.
   - Mỗi lần demo: mở app Ollama (biểu tượng ở khay hệ thống) **trước** khi chạy `.bat`.
   - Chưa bật Ollama thì dải chữ báo `CHUA BAT OLLAMA`. Muốn tạm dùng LLM online (Groq/Gemini)
     thì chạy `chay-demo.bat --llm-online`.
4. **Giọng robot (TTS)**: có **`fish-key.txt`** (API key tài khoản https://fish.audio → API Keys)
   thì dùng Fish Audio, không thì dùng giọng Gemini (cùng `gemini-key.txt`). File gồm:
   ```
   sk-fish-xxxxxxxx              ← dòng 1: API key
   ID_Model = 9335xxxxxxxx       ← tuỳ chọn: ID giọng trong tài khoản Fish
   ```
   Không ghi `ID_Model` thì dùng `FISH_VOICE_ID` / `FISH_VOICE_ID_JP` trong `config/settings.py` của nhóm. Chọn cứng: `chay-demo.bat --tts fish` hoặc `--tts gemini`.
5. **Internet**: phần nghe (Gemini Transcribe) và giọng đọc (Fish/Gemini) chạy online.

## 4. Chạy

1. Cắm board, mở thư mục `head-demo` trong VS Code → **Upload** (không bấm Monitor).
2. Bấm đúp **`chay-demo.bat`**. Lần đầu tự cài thư viện (vài phút).
3. Cửa sổ hiện ra: video + cảm xúc như cam-emotion, dải chữ "GIONG NOI" ở dưới.

| Phím (bấm khi cửa sổ đang được chọn) | Việc |
|---|---|
| **Space** | Bắt đầu nói. Nói xong ngừng ~1 giây là robot tự xử lý |
| **V** | Đổi giọng robot Fish Audio ↔ Gemini |
| **T** | Thử loa: robot nói "Xin chào, mình là Moon…" (không cần mic) |
| **+ / -** | To / nhỏ giọng robot |
| **Q** hoặc Esc | Thoát |

Thử loa không cần camera: `.venv\Scripts\python.exe tools\head_demo.py --say "Xin chào"`.

## 4a. Chạy KHÔNG DÂY (qua WiFi)

Cả đầu và thân đều nối laptop qua WiFi → robot chạy tự do, chỉ cần nguồn (sạc dự phòng).
Ảnh camera, mic, loa, mặt robot đi qua WiFi bằng **đúng giao thức** như dây USB.

1. **1 lần đầu, cần dây data**: tạo `src/wifi_secrets.h` (chép từ `src/wifi_secrets.example.h`,
   điền tên + mật khẩu Mobile hotspot của laptop, phải là 2,4GHz) rồi **Upload** bằng dây như mục 4.
2. Từ đó về sau: bật Mobile hotspot → cắm sạc dự phòng cho board đầu (và board thân) → chạy
   `chay-demo.bat` **không cắm dây**. Chương trình không thấy dây → tự chuyển WiFi, tự tìm board
   (dòng `[WIFI] tim thay board dau: 192.168.137.xx`). Board bật trước hay hotspot bật trước đều
   được: board tự thử nối lại WiFi mỗi 8 giây.
   - Muốn ép dùng WiFi dù đang cắm dây: `.venv\Scripts\python.exe tools\head_demo.py --wifi`
     (thêm IP sau `--wifi` nếu không tự tìm được).
3. **Nạp code qua WiFi (OTA)**, không cần dây nữa: `pio run -e ota -t upload` trong thư mục
   `head-demo` (đóng `chay-demo.bat` trước). Lần đầu Windows hỏi tường lửa cho python → Allow.
   Lỗi không tìm thấy `panda-head.local` → sửa `upload_port` trong `platformio.ini` thành IP board.
   Đang nạp thì màn robot hiện "DANG NAP CODE".

Phím lái thân (mục 4c) và giọng nói "run/back/left/right/stop" dùng như cũ — thân đã chạy WiFi
sẵn (body-test).

## 4c. Lái thân như xe điều khiển (bàn phím + tay cầm điện thoại)

**Cần nạp lại `body-test`** (bản có số lùi + phanh). Firmware cũ không hiểu tốc độ âm: lùi sẽ
đứng yên, xoay chỉ quay 1 bánh.

| Phím (cửa sổ camera hoặc cửa sổ đen) | Việc |
|---|---|
| **W** | Tiến (tăng tốc dần trong ~0,5 giây như xe thật) |
| **S** | Lùi (cảm biến chỉ nhìn phía trước — lùi thì tự nhìn đường) |
| **A / D** | Xoay trái / phải tại chỗ (2 bánh quay ngược chiều) |
| **L** | Phanh: bánh đứng ngay (firmware nối tắt motor), không lăn thêm |
| **E / R** | Tăng / giảm tốc độ (±25, từ 80 tới 255) |
| **, / .** | Đi thẳng mà xe lệch: `,` kéo sang trái, `.` kéo sang phải (mỗi lần 2%, tự lưu vào `body-trim.txt`) |

Bấm 1 lần là chạy tiếp tới khi bấm phím khác / L, gặp vật cản khi đang tiến, hoặc quá 10 giây.

**Chỉnh xe đi thẳng (làm 1 lần):** bấm W cho xe chạy ~1 m. Xe trôi sang **phải** → bấm `,` vài
lần; trôi sang **trái** → bấm `.`. Lặp lại tới khi đi thẳng. Cửa sổ hiện "lech: giam banh trai 4%"...
Hai motor TT rẻ tiền không bao giờ quay đều nhau nên gần như xe nào cũng cần chỉnh.

**Tay cầm điện thoại:** điện thoại vào **cùng hotspot** của laptop, mở địa chỉ in ở cửa sổ đen
(thường là `http://192.168.137.1:8080`, cũng hiện ở góc cửa sổ camera). Trang có camera, nút
▲ ▼ ◀ ▶ (**giữ để chạy, thả là phanh**), PHANH, tăng/giảm tốc, chỉnh lệch, "Nói với Moon".
Điện thoại mất sóng / khoá màn hình → sau 0,5 giây thân tự phanh. Lần đầu Windows hỏi tường lửa
cho python → tick **cả Private lẫn Public** rồi Allow (thiếu Public thì điện thoại không mở được
trang). Tắt tay cầm: `chay-demo.bat --no-remote`. Trang không cần internet và không đưa lên mạng:
chỉ ai vào hotspot của laptop mới lái được robot.

## 4b. Điều khiển phần thân bằng giọng nói ("run" / "left" / "right" / "stop")

Cắm thêm board thân **ESP32 DevKit C** (đã nạp firmware `MOON/body-test`) vào một cổng USB
khác, **tắt `chay-test.bat`** của body-test (2 chương trình không mở chung 1 cổng được), rồi chạy
`chay-demo.bat` như thường. Demo tự tìm board thân (chip CP2102/CH340) và in cổng ra cửa sổ đen.

| Bấm SPACE rồi nói | Robot |
|---|---|
| "run", "go", "chạy đi", "tiến lên", "đi thẳng" | 2 bánh chạy tới, nói "Moon chạy đây!", mặt vui "MOON DANG CHAY" |
| "back", "lùi", "lùi lại" | 2 bánh quay lùi, nói "Moon lùi lại đây!" |
| "left", "trái", "rẽ trái" | 2 bánh quay ngược chiều → xe xoay tại chỗ sang trái, mặt "MOON RE TRAI" |
| "right", "phải", "rẽ phải" | ngược lại "left", mặt "MOON RE PHAI" |
| "stop", "dừng lại", "thôi" | dừng, nói "Moon dừng lại rồi." |
| câu dài / câu hỏi khác | hỏi AI như bình thường |

- Lệnh chỉ nhận ở câu **ngắn** (≤ 4 từ), nên câu hỏi kiểu "con mèo chạy tiếng Anh là gì?" vẫn đi
  vào AI, không làm xe chạy.
- Rẽ trái/phải là **xoay tại chỗ** (2 bánh quay ngược chiều, chậm hơn chạy thẳng 25%).
- **Vật cản < 12cm** khi đang đi thẳng: board thân tự dừng bánh ngay, mặt robot "VAT CAN!", loa nói
  "Có vật cản phía trước, Moon dừng lại nhé!". Bỏ vật ra xe **không** tự chạy lại, phải nói "run" lần
  nữa. Lúc đang bị chặn vẫn nói "left"/"right" được để xe xoay mặt khỏi vật cản rồi "run" tiếp.
- Chạy (hoặc rẽ) quá **10 giây** tự dừng (tránh xe lao khỏi bàn).
- Phím dự phòng (lớp ồn, nói không nhận): xem bảng phím ở mục 4c (W/S/A/D, L phanh).
- Muốn chỉ chạy phần đầu: `chay-demo.bat --no-body`.

**Chỉ có 1 dây USB → thân cắm sạc dự phòng, điều khiển qua WiFi:**
1. Laptop bật **Mobile hotspot** (Settings → Network → Mobile hotspot, băng tần **2.4 GHz**), hoặc
   dùng hotspot điện thoại cho cả laptop lẫn board. ESP32 không bắt được WiFi 5GHz, WiFi trường
   thường chặn các máy thấy nhau.
2. `body-test/src/`: chép `wifi_secrets.example.h` thành `wifi_secrets.h`, điền tên + mật khẩu
   hotspot, cắm dây vào board thân → **Upload** (Serial Monitor in `# WiFi OK ... IP ...`).
3. Rút dây khỏi thân, cắm thân vào sạc dự phòng; cắm dây đó vào board đầu → `chay-demo.bat`.
   Lần đầu Windows hỏi tường lửa cho Python → tick cả **Private** và **Public** → Allow.
4. Cửa sổ đen in `[THAN] tim thay board than qua WiFi: 192.168.x.x` là xong.

## 5. Gợi ý câu hỏi khi demo

| Hỏi | Robot làm gì |
|---|---|
| "Xin chào Moon, bạn là ai?" | Giới thiệu bản thân |
| "Con mèo tiếng Nhật là gì?" | Đọc 猫 (neko), màn hiện `CAT / NE-KO` |
| "Quả táo tiếng Anh là gì?" | Đọc "apple" |
| "Kể cho mình một câu đố vui" | Lấy từ kho câu đố của Ngọc Anh |

## 6. Lỗi thường gặp

| Hiện tượng | Cách sửa |
|---|---|
| Dải chữ báo `THIEU GEMINI KEY` | Tạo `gemini-key.txt` (mục 3). Camera + màn vẫn chạy bình thường. |
| `Loi Gemini (...)` | Key sai/hết hạn, hoặc mạng chặn Gemini. Thử key khác hoặc mạng khác (phát WiFi điện thoại). |
| Bấm Space, báo `Khong nghe ro` | Đọc dòng `[mic] ... nguong ..., to nhat ...` trong cửa sổ đen. `KHONG thay tieng noi` → nói to/gần mic hơn (cách 10–30 cm), hoặc giảm `MIN_VOICE_LEVEL` trong `tools/mic_clean.py`. Có tiếng nói mà Gemini vẫn trả `''` → nghe thử 2 file `debug_mic_last.wav` (thô) / `debug_mic_last_clean.wav` (bản gửi Gemini) trong `head-demo/`. |
| Mic rè/lốp bốp, Gemini chép sai chữ | Có dòng `[mic] CANH BAO: ... so bi tran` → board còn firmware cũ, nạp lại `head-demo`. Không có dòng đó mà vẫn rè → ấn chặt dây mic (chân module INMP441 phải **hàn**, cắm hờ là rè), không sờ vào mạch lúc đang nói. |
| `TTS loi - ...` | Mất mạng, key Fish sai/hết lượt free (bấm V đổi sang giọng Gemini). |
| Robot nói rè/vấp | Giảm âm lượng (`-`); kiểm tra dây loa (lần trước rè do dây jumper hỏng). |
| `KHONG MO DUOC CONG` | Đóng Serial Monitor rồi chạy lại. |
| Mặt robot đứng ở `CHO LAPTOP...` | Chưa chạy `.bat`, hoặc `.bat` báo lỗi (đọc cửa sổ đen). |

## 7. Giới hạn

- Robot đã có mic (INMP441 → `Voice._listen_robot_mic()`). Mic laptop vẫn còn dùng được qua cờ
  `--laptop-mic` để so sánh/debug khi nghi ngờ mic robot có vấn đề.
- Màn robot chỉ hiện chữ không dấu (font ASCII); Kanji/Kana cần font tiếng Nhật như
  `firmware-demo/display.cpp`.
- Vẫn phải cắm dây USB vào laptop. Bản cuối cùng chuyển sang WiFi + MQTT theo thiết kế của nhóm.
