# head-demo — đầu robot nói chuyện: camera + màn hình + loa

Bản demo cho thầy xem phần **đầu robot** chạy cùng **AI của Thái và Ngọc Anh**:

- **Màn hình** (giống `cam-emotion`): camera robot nhìn mặt bạn, AI cảm xúc của Thái đoán bạn
  đang vui/buồn/giận/ngạc nhiên…, màn robot vẽ khuôn mặt tương ứng.
- **Loa + mic**: **cứ nói** vào **mic robot** (INMP441 trên đầu, dây nối ở mục 3), không cần bấm
  phím (nghe tự động, xem mục 4). AI của nhóm nghe, hiểu, trả lời, và **giọng trả lời phát ra loa robot**. Trong lúc đó
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
| LLM qua **API miễn phí** (Gemini Flash-Lite), không dùng `qwen3.5:2b` local nữa | Nhóm tập trung vào computer vision nên thầy cho phép phần AI còn lại gọi API. qwen 2b chạy local vừa chậm vừa trả lời kém. `tools/llm_online.py` vẫn dùng nguyên `server/llm/engine.py` của Ngọc Anh (bài học RAG, đóng vai, sửa lỗi ngữ pháp...), chỉ đổi "bộ óc" và dùng prompt dành cho model mạnh. |
| Mắt robot: **mặt + cảm xúc chạy local**, chỉ khi bé hỏi về đồ vật mới **gửi 1 ảnh lên API** | Camera chạy 13 hình/giây, còn bản API miễn phí chỉ cho khoảng 15 lần/phút, 500 lần/ngày. Gọi API liên tục thì vài phút là hết lượt. Model local nhanh, miễn phí, và ảnh không ra khỏi laptop. API (`tools/vision_api.py`) lo phần model local không làm được: nhận ra đồ vật bé đưa lên, gọi tên bằng 3 thứ tiếng. |
| **Nghe tự động**: cứ nói là robot nghe, không cần bấm phím hay gọi "Moon ơi" | Robot rảnh thì mic luôn mở. Tiếng to hơn ồn nền của phòng kéo dài ít nhất 0,3 giây thì tính là bắt đầu nói, và robot giữ lại 0,6 giây trước đó để không mất chữ đầu câu. Ngừng 1,5 giây thì chốt câu. Câu ngắn dưới 0,5 giây (ho, gõ bàn) bị bỏ, không tốn lượt Gemini. Lúc robot đang nghĩ/nói và 0,8 giây sau đó thì không nghe, để robot không tự nghe tiếng loa của mình. Phòng ồn quá thì bấm **M** để tắt và quay về bấm Space. |

## 3. Chuẩn bị (1 lần)

1. **Phần cứng:** board ESP32-S3 + camera + màn TFT (nối như `cam-emotion`) + MAX98357 + loa
   (BCLK 47, LRC 48, DIN 21, VIN 5V, GND) + **mic INMP441** (SCK 41, WS 40, SD 42, VDD 3V3,
   GND, L/R→GND để chọn kênh trái). Sơ đồ đầy đủ + lý do chọn 3 chân 40/41/42:
   `body-test/so-do-noi-day.html` mục 02b.
2. **Gemini key** (bắt buộc cho phần nghe, miễn phí): vào https://aistudio.google.com/apikey →
   tạo key → dán vào file **`head-demo/gemini-key.txt`** (chỉ 1 dòng). Hoặc xin Thái key nhóm
   đang dùng cho dashboard (`GEMINI_API_KEY` trong `config/secrets.py`).
   Tuỳ chọn: **`groq-key.txt`** (https://console.groq.com/keys), thêm một nguồn dự phòng nữa
   khi Gemini hết lượt. Các file key **không** đưa lên git.
3. **LLM (phần "suy nghĩ")**: mặc định gọi API miễn phí, dùng chung `gemini-key.txt`, không cần
   cài thêm gì. Nếu một nguồn hết lượt miễn phí, quá tải hay lỗi thì tự chuyển sang nguồn kế tiếp
   (nguồn bị lỗi được nghỉ 60 giây):
   1. `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` → `gemini-flash-lite-latest`. Bản miễn phí
      giới hạn số lần gọi **theo từng model**, nên xoay vòng 3 model được gấp khoảng 3 lần số câu
      hỏi mỗi ngày. Mỗi câu mất khoảng 0,5–1,5 giây. (Bản Flash thường mạnh hơn, nhưng lúc thử
      tháng 11/2026 hay báo quá tải và phải chờ 7–25 giây, không hợp để nói chuyện.)
   2. Groq, nếu có `groq-key.txt`.
   3. Ollama `qwen3.5:2b` của Ngọc Anh, nếu đang bật app Ollama. Mất mạng vẫn trả lời được.

   Cửa sổ đen in ra nguồn nào vừa trả lời, ví dụ `[LLM] gemini-3.5-flash-lite tra loi sau 1.1s`.
   Muốn chạy hoàn toàn offline như bản cũ: mở Ollama rồi chạy `chay-demo.bat --llm local`
   (cài Ollama ở https://ollama.com/download, rồi `ollama pull qwen3.5:2b` một lần).
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
| *(không bấm gì)* | **Cứ nói**: robot tự nghe (mặt hiện "DANG NGHE..."), ngừng khoảng 1,5 giây là robot trả lời |
| **M** | Tắt/bật nghe tự động (phòng ồn quá, robot hay nghe nhầm thì tắt). Chạy `chay-demo.bat --ptt` thì tắt ngay từ đầu |
| **Space** | Bắt đầu nói (dùng khi đã tắt nghe tự động, hoặc muốn ép robot nghe ngay) |
| **V** | Đổi giọng robot Fish Audio ↔ Gemini |
| **T** | Thử loa: robot nói "Xin chào, mình là Moon…" (không cần mic) |
| **+ / -** | To / nhỏ giọng robot. Mặc định **x1.00**: mỗi câu được chỉnh về mức to hết cỡ mà chưa méo. Lên tới x2.00 thì to hơn chút nữa nhưng méo nhẹ. Đổi mặc định bằng `chay-demo.bat --volume 0.8` |
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
| **Giữ W** | Tiến. **Thả là phanh** (kiểu xe điều khiển, chỉ chạy khi đang giữ phím) |
| **Giữ W + A / W + D** | **Vừa tiến vừa rẽ** (cua vòng, bánh phía trong chậm còn 40%): đang chạy thẳng mà giữ thêm A thì xe cua luôn, **không dừng lại** |
| **Giữ S** (+ A / D) | Lùi (+ rẽ). Cảm biến chỉ nhìn phía trước, lùi thì tự nhìn đường |
| **Giữ A / D** (một mình) | Xoay trái / phải tại chỗ (2 bánh quay ngược chiều, lực ít nhất 140 để không khựng) |
| **L** | Phanh: bánh đứng ngay (firmware nối tắt motor), không lăn thêm |
| **E / R** | Tăng / giảm tốc độ (±25, từ 110 tới 255). **Mặc định 170** |

**Chạy nhanh và dứt khoát hơn (25/11):**
- Tốc độ mặc định 150 lên **170**. Xe tăng tốc 100 → 170 trong khoảng 0,12 giây (trước là
  90 → 150 trong 0,5 giây nên xe "ì ạch"). Đã thử mặc định 220 nhưng bị sụt áp (xem "Nguồn" bên
  dưới). Tách nguồn motor riêng xong thì bấm **E** để chạy nhanh hơn.
- **Đổi chiều đột ngột** (đang tiến mà bấm lùi): firmware phanh 80 ms rồi mới quay chiều mới,
  để motor không hút dòng gấp đôi.
- **Ngưỡng dừng trước vật cản tăng theo tốc độ:** 12 cm khi chạy ≤ 150, khoảng 14 cm ở 170,
  khoảng 22 cm ở 255. Chạy nhanh vẫn phanh kịp, chạy chậm vẫn đi sát vật được.
- Laptop gửi lệnh 25 lần/giây (trước 20), nên WiFi rớt vài gói thì xe không bị khựng.
- **Cần nạp lại `body-test`.**

**Nguồn: bấm chạy là thân mất WiFi vài giây = SỤT ÁP.** Khối pin (sơ đồ mục 02d: 2×18650 song
song → TP4056 → công tắc → **1 mạch MT3608** lên 5,1V) đang nuôi **tất cả** qua cùng 1 đường 5V:
ESP32-S3 đầu + camera + màn + loa, ESP32 thân, HC-SR04 **và 2 motor (chân VM của TB6612)**. Một
mạch MT3608 tăng từ 3,7V lên 5V chỉ cho ra khoảng 1A ổn định. Motor đứng yên mà bắt đầu quay
thì hút dòng rất lớn trong tích tắc, MT3608 không đáp kịp nên đường 5V tụt. ESP32 thân tưởng mất
điện, tự khởi động lại (brownout) và mất WiFi khoảng 2–5 giây. Loa robot nói to cũng góp thêm.
Firmware mới báo lý do khởi động: cửa sổ đen in
`[THAN] !!! board than vua TU KHOI DONG LAI: BROWNOUT` là đúng bệnh này. Cách sửa, từ dễ đến chắc:
1. **Kiểm tra tụ 1000µF** trên cả 2 breadboard: đã hàn/cắm, đúng chiều (chân dài vào +), sát
   chân VM. Thêm 1 tụ 1000µF ngay ở **VOUT của MT3608** thì càng tốt.
2. **Đo khi chạy:** đồng hồ để thang V DC, đo hàng 5V của thân rồi bấm W. Tụt dưới khoảng 4,3V
   là đủ để ESP32 reset. Vặn biến trở MT3608 lên 5,2V cũng đỡ một chút (đừng quá 5,3V).
3. **Chắc nhất: mạch MT3608 thứ 2 chỉ cho motor.** Sơ đồ đã ghi "KHUYẾN NGHỊ — boost riêng cho
   motor": VIN của MT3608 #2 lấy từ sau công tắc (cùng chỗ với #1), VOUT+ nối **VM** của TB6612,
   VOUT− nối GND chung, và **rút dây VM đang lấy từ hàng 5V**. Motor kéo sụt bao nhiêu cũng chỉ
   ảnh hưởng mạch #2, còn 2 board giữ được 5V. Có mạch riêng thì vặn #2 lên **6V** (motor TT chịu
   3–6V) để xe mạnh hơn hẳn.
   Cách tạm nếu chưa có MT3608 thứ 2: nối VM thẳng vào **sau công tắc** (pin 3,7–4,2V). Motor yếu
   hơn khoảng 20% nhưng không còn kéo sụt đường 5V của 2 board.
4. **Sạc đầy pin.** Pin càng yếu thì MT3608 càng phải hút nhiều dòng từ pin, nên càng dễ sụt áp.

**Phần mềm đang "chống đỡ" tạm (25/11), xoá khi đã tách nguồn motor:**
- Firmware thân **tắt mạch tự reset khi sụt áp** (`WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0)` trong
  `setup()`), nên thân chạy qua được những lần tụt áp ngắn thay vì mất WiFi 5–15 giây. Đổi lại,
  nếu tụt quá sâu thì chip có thể treo, nên firmware bật thêm **watchdog**: `loop()` đứng quá 5 giây
  là tự khởi động lại, motor không chạy mãi được.
- Xe tăng tốc mềm hơn: 80 → 170 trong khoảng 0,2 giây.
- Laptop chỉ báo "MAT LIEN LAC" khi 2,5 giây không nhận trạng thái (trước là 1,5 giây, hay báo
  nhầm khi WiFi chỉ chậm một chút).
| **, / .** | Đi thẳng mà xe lệch: `,` kéo sang trái, `.` kéo sang phải (mỗi lần 2%, tự lưu vào `body-trim.txt`) |

Phím chỉ có tác dụng khi **cửa sổ camera hoặc cửa sổ đen "MOON head-demo"** đang được chọn, nên
gõ chữ ở cửa sổ khác không làm xe chạy. Tay cầm điện thoại cũng vậy: **giữ ▲ rồi chạm thêm ◀**
(2 ngón) là cua trái. Xe tự dừng khi gặp vật cản lúc đang tiến, hoặc khi chạy quá 10 giây.

**Camera qua WiFi (25/11):** đầu robot gửi tối đa 10 hình/giây (trước khoảng 13) và nén 12 (trước
10), dữ liệu ít hơn khoảng 40% nên hotspot đỡ nghẽn khi đi xa. (Đã thử đổi độ nén ngay lúc laptop
nối WiFi: đầu robot crash và khởi động lại liên tục, nên đã bỏ cách đó.) Cần **nạp lại
`head-demo`** (qua WiFi được: `pio run -e ota -t upload`). Đầu robot tự khởi động lại thì cửa sổ đen
in `[WIFI] !!! board DAU vua TU KHOI DONG LAI: <ly do>`.

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

## 4d. Mắt robot: camera + API (tạm thời, chờ model của Thái/Anh)

Bé giơ một đồ vật hoặc tranh lên trước camera rồi hỏi, ví dụ **"Moon ơi đây là con gì?"**,
**"Cái này tiếng Nhật là gì?"**, **"What is this?"** hoặc "Moon nhìn thấy gì?". Robot chụp
khung hình lúc đó và gửi Gemini (mất khoảng 2 giây). Gemini trả về: có mấy người, nét mặt, bé
đang cầm gì, những đồ vật xung quanh (tên tiếng Việt / Anh / Nhật) và một câu mô tả cảnh. Mô tả
này được gắn vào câu hỏi gửi LLM, nên robot trả lời đúng thứ đang thấy và dạy luôn từ vựng. Cửa
sổ đen in dòng `[MAT] Camera của Moon đang thấy: ...`. Câu hỏi bình thường thì **không** gửi ảnh.

| Chạy | Mắt robot |
|---|---|
| `chay-demo.bat` | Mặc định: mặt và cảm xúc dùng model local của Thái, API chỉ dùng khi bé hỏi về đồ vật |
| `chay-demo.bat --vision api` | Bỏ hẳn model local: API phân tích mặt, cảm xúc và cảnh, 15 giây/lần (mặt robot đổi chậm). Panel bên phải hiện thêm dòng `Thay: ...`. Một giờ chạy tốn khoảng 240 lượt, tức khoảng nửa hạn mức một ngày của một model |
| `chay-demo.bat --vision-cloud off` | **Không bao giờ** gửi ảnh lên mạng, chỉ dùng model local (bé hỏi "đây là gì" thì robot không nhìn được) |

**Riêng tư:** với bản Gemini miễn phí, Google **được dùng dữ liệu gửi lên để cải thiện sản phẩm**.
Ảnh camera có mặt trẻ em nên cần hỏi thầy trước khi demo với trẻ thật. Nếu không được phép thì
chạy `--vision-cloud off`.

**Khi Thái/Anh xong model:** viết một class có hàm `process(frame)` trả về dict gồm
`face_detected`, `emotion`, `emotion_scores`, `face_box` (thêm `objects`, `holding`, `scene` nếu
có), giống `VisionEngine` của Thái và `ApiVision` ở `tools/vision_api.py`. Sau đó đưa class đó
vào `ai_worker()` trong `head_demo.py`. Phần còn lại (mặt robot, panel, LLM) không phải sửa.

## 4e. Brain: robot tự biểu cảm, tự di chuyển, tự bắt chuyện

`tools/moon_brain.py` nối tai, mắt, miệng và bánh xe lại với nhau. Mặc định bật, tắt bằng
`chay-demo.bat --brain off`. Đang chạy thì bấm **B** để bật/tắt riêng phần tự nói.

1. **Hành động theo câu trả lời.** LLM được phép thêm "thẻ lệnh" ở cuối câu, ví dụ
   `[face:love]`, `[move:dance]`, `[word:CAT|NEKO]`. Brain cắt thẻ ra (loa không đọc) rồi làm theo:
   đổi mặt robot trong lúc nói, hiện từ lên màn hình, cho bánh xe nhảy/xoay. Cách này không tốn
   thêm lượt API. Cửa sổ đen in dòng `[BRAIN] the lenh: face=... word=... move=...`.
   - Robot **chỉ di chuyển khi bé yêu cầu** ("nhảy đi", "xoay một vòng", "lại đây"...). Đã test
     7 câu: 4 câu thường không di chuyển, 3 câu yêu cầu thì di chuyển đúng.
   - Mỗi cử động ngắn (tối đa khoảng 2 giây) rồi tự phanh. Firmware thân vẫn tự dừng trước vật cản.
     Bấm phím hoặc tay cầm giữa chừng thì brain nhường ngay.
2. **Tự chủ động.** Phần này dùng camera local, không tốn lượt API:
   - Có người đứng trước camera khoảng 1,5 giây thì robot **tự chào**. Người đó đi khỏi hơn
     1 phút rồi quay lại thì chào lại (mỗi lần chào cách nhau ít nhất 2 phút).
   - Có người mà **45 giây** không ai nói gì thì robot **đố một từ** lấy từ kho bài học của Ngọc
     Anh (46 từ, ngẫu nhiên tiếng Anh hoặc tiếng Nhật). Bé cứ nói câu trả lời: LLM biết mình vừa đố
     gì nên khen khi đúng, nói đáp án khi sai.

## 4g. Tự đi dạo: chạy liên tục 10 phút, tự né vật cản

Code ở `tools/auto_drive.py`. **Chỉ cho chạy dưới sàn**: HC-SR04 không nhìn thấy mép bàn hay bậc
cầu thang.

**Bật** bằng một trong các cách sau:
- bấm phím **X**;
- nói "Moon ơi **tự đi dạo** đi" (hoặc "tự chạy", "khám phá", "chạy quanh phòng"...);
- bấm nút **🚗 Tự đi dạo** trên tay cầm điện thoại;
- hoặc nói theo cách khác như "Moon đi tham quan căn phòng đi": LLM tự hiểu và gắn `[move:explore]`.

**Tắt** bằng một trong các cách sau:
- bấm **X** lần nữa, hoặc bấm nút trên điện thoại lần nữa;
- nói "**dừng lại**" hoặc "thôi";
- **lái tay bất kỳ** (W/A/S/D, L, nút trên điện thoại): người cầm lái thì robot thôi tự đi;
- nhờ robot làm động tác khác (nhảy, xoay...);
- hết 10 phút thì robot tự dừng và nói "Hết giờ đi dạo rồi".

Cách né vật cản: HC-SR04 gắn cố định nhìn thẳng, nên muốn "nhìn" trái/phải thì phải xoay cả xe.
1. Robot đi thẳng ở tốc độ 160 (chậm hơn lúc lái tay để kịp phanh và bớt sụt áp).
2. Thấy vật gần hơn **30cm** thì phanh, xoay **trái ~60°** đo khoảng cách, rồi xoay sang **phải
   ~60°** đo tiếp. Mặt robot hiện "TIM DUONG...".
3. Bên nào trống hơn 45cm thì đi hướng đó (ưu tiên bên xa hơn).
4. Cả 2 bên đều bị chặn thì **lùi** 0,6 giây, quay đầu rồi thử lại.
5. Bị chặn **3 lần liền** (kẹt trong góc) thì dừng hẳn và nói "Moon bị kẹt rồi, bạn giúp Moon ra với!".
6. Đang chạy mà khoảng cách phía trước **đứng yên 2 giây** nghĩa là xe sượt hông vào góc tủ / chân
   ghế (HC-SR04 chỉ nhìn được một hình nón hẹp phía trước nên không thấy) và bánh quay mà xe không
   đi. Robot sẽ lùi rồi quay hướng khác.

Firmware thân vẫn tự phanh khi vật gần hơn khoảng 12cm. Đây là lớp bảo vệ thứ 2, phòng khi laptop
phản ứng chậm. Mất WiFi thì thân tự dừng sau 0,5 giây; mất hơn 20 giây thì chế độ tự đi tự tắt.

**Chỉnh:**
- `chay-demo.bat --auto-minutes 5`: đổi thời gian (mặc định 10 phút).
- `chay-demo.bat --auto-turn 0.6`: **góc xoay khi nhìn trái/phải**. Không có cảm biến đếm vòng bánh
  nên góc xoay tính bằng thời gian (mặc định 0,45 giây, khoảng 60°). Xe xoay ít quá (sàn trơn,
  thảm, pin yếu) thì tăng lên; xoay quá đà thì giảm.

**Giới hạn:**
- Không có cảm biến phía sau, nên khi lùi là lùi "mù" (chỉ 0,6 giây).
- Vật thấp hơn HC-SR04 hoặc nằm chéo hông xe thì robot không thấy trước, chỉ gỡ được nhờ bước 6.

Đã test trên mô phỏng (phòng 2,5m × 1,8m có thùng giữa phòng, robot ảo nhận đúng lệnh bánh như
thân thật):
- chạy 40 giây, né 6–9 lần, **không đâm thẳng lần nào**; lần sượt hông vào góc thùng lâu nhất
  1,8 giây thì tự gỡ;
- tắt giữa chừng thì bánh dừng ngay;
- nhốt trong hộp kín 40cm thì báo "bị kẹt" rồi dừng.

LLM thật: "Moon đi tham quan căn phòng một mình đi" → `explore`, "Con chó tiếng Anh là gì?" →
không di chuyển.

## 4f. Chế độ ĐUA XE: chỉ lái thân, nhanh hết mức

Bấm đúp **`dua-xe.bat`** (tắt `chay-demo.bat` trước). Chương trình chỉ nối với thân: không camera,
không AI, không giọng nói.

| | Chế độ thường (`chay-demo.bat`) | Đua xe (`dua-xe.bat`) |
|---|---|---|
| Tốc độ | 170 | **255** (E/R để chỉnh) |
| Xuất phát | 80 → 170 trong ~0,2 giây | **120 → 255 trong ~0,15 giây** |
| Tự phanh trước vật cản | Bật | **Tắt** (xe bạn chạy phía trước cũng bị tính là vật cản). Bấm **O** để bật lại |
| Chạy liên tục tối đa | 10 giây | 2 phút |

Lái: giữ **W/S/A/D** ở cửa sổ đen "MOON dua xe" (W+A = cua trái), hoặc dùng tay cầm điện thoại ở
địa chỉ in ra. **L** phanh, **Q** thoát.

**Đầu robot khi đua:**
- **Cách tốt nhất: rút dây nguồn lên đầu** (dây 2 sợi từ đế lên bo đầu). Đầu và thân không có dây
  tín hiệu nào nối nhau, nên rút ra thì thân vẫn chạy bình thường, và cả mạch MT3608 chỉ còn nuôi
  thân + motor, nên ít sụt áp nhất. **Tắt công tắc trước khi rút/cắm**, và quấn băng dính đầu dây
  vừa rút để 2 chân không chạm vào nhau hay chạm kim loại.
- Không rút dây cũng được: firmware `head-demo` mới **chỉ bật camera khi laptop kết nối**. Chạy
  `dua-xe.bat` thì đầu chỉ sáng màn hình chờ ("CHO LAPTOP (CAM TAT)"), WiFi để chế độ tiết kiệm
  điện, nên nhẹ hơn nhiều so với lúc chạy demo (cần nạp `head-demo` bản mới một lần).
- **Đừng vặn MT3608 cao hơn 5,2V cho nhanh.** Mạch này còn nuôi board đầu, loa MAX98357 (tối đa
  5,5V) và HC-SR04. Muốn motor chạy 6V thì dùng MT3608 thứ 2 chỉ cho motor (mục 4c "Nguồn").

## 5. Gợi ý câu hỏi khi demo

| Hỏi | Robot làm gì |
|---|---|
| "Xin chào Moon, bạn là ai?" | Giới thiệu bản thân |
| Giơ quả táo (hoặc tranh con mèo): "Moon ơi đây là gì?" | Nhìn camera, nói tên đồ vật + dạy từ tiếng Anh / Nhật |
| "Moon ơi nhảy cho mình xem đi!" | Nói vui + lắc trái phải (cần phần thân đang nối) |
| "Mình yêu Moon lắm" | Mặt chuyển sang "love" trong lúc trả lời |
| Đứng im trước robot 45 giây | Robot tự đố một từ tiếng Anh/Nhật |
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
