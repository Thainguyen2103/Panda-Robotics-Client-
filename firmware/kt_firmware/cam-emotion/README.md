# cam-emotion — Camera robot + AI cảm xúc của Thái + mặt robot trên màn TFT

Bạn đứng trước robot, làm một biểu cảm (cười, nhăn mặt, ngạc nhiên…). Camera trên đầu robot
chụp lại, AI nhận diện cảm xúc **của Thái** đoán bạn đang thể hiện cảm xúc gì, rồi **màn hình
robot vẽ khuôn mặt tương ứng**. Cùng lúc, laptop mở một cửa sổ cho thấy AI đang "nhìn" gì và
chấm điểm từng cảm xúc bao nhiêu phần trăm.

> Thư mục này **không sửa một dòng code nào của Thái**. Nó gọi thẳng engine nhận diện trong
> `Panda-Robotics-Client-/server/vision/`. Muốn hiểu sâu cách AI quyết định cảm xúc, đọc
> `docs/vision.md` của Thái trong repo nhóm (bản tóm tắt tiếng Việt: `ai.md` mục 10 trong repo
> riêng MOON của Khoa).

---

## 1. Toàn cảnh: input → xử lý → output

```
 ┌─────────────── ESP32-S3 (đầu robot) ───────────────┐          ┌──────────────── Laptop ────────────────┐
 │                                                     │          │                                         │
 │  Camera OV5640 ──► ảnh JPEG 640×480 (~12KB/ảnh) ────┼── USB ──►│  emotion_viewer.py                      │
 │                                                     │  4Mbaud  │   1. tách từng ảnh JPEG ra khỏi dòng byte│
 │                                                     │          │   2. AI của Thái: tìm mặt → FER+ +       │
 │                                                     │          │      MediaPipe → nhãn cảm xúc            │
 │  Màn TFT 320×240 ◄── vẽ mặt robot + chữ ◄───────────┼── USB ◄──│   3. đổi nhãn → tên mặt robot            │
 │                       (vd mặt "happy" + "VUI")      │  "face   │   4. cửa sổ: video + khung mặt + % cảm xúc│
 └─────────────────────────────────────────────────────┘  happy   └─────────────────────────────────────────┘
                                                          VUI\n"
```

| | Input | Output |
|---|---|---|
| **Toàn hệ thống** | Khuôn mặt người trước camera robot | Mặt robot trên TFT nhại lại cảm xúc + cửa sổ phân tích trên laptop |
| **ESP32 — phần camera** | Ánh sáng vào cảm biến OV5640 | Gói `PNDA` + độ dài + JPEG, gửi qua USB liên tục (~16 ảnh/giây) |
| **Laptop — AI** | Ảnh 640×480 (BGR) | `emotion` (1 trong 8 nhãn hoặc `unknown`), % từng cảm xúc, khung mặt, mức hoạt động của các cơ mặt |
| **Laptop — gửi lệnh** | Nhãn cảm xúc | 1 dòng chữ `face <tên mặt> <chú thích>\n` gửi ngược xuống board |
| **ESP32 — phần màn hình** | Dòng lệnh `face ...` | Khuôn mặt động (~33 khung/giây) + dòng chú thích dưới mặt |

---

## 2. Vì sao lại chia việc như thế

| Quyết định | Lý do |
|---|---|
| **AI chạy trên laptop, không chạy trên ESP32** | Mô hình FER+ nặng 35MB, MediaPipe cần hàng trăm MB RAM và CPU mạnh. ESP32-S3 chỉ có 8MB PSRAM, CPU 240MHz, nên không kham nổi. Đây cũng đúng kiến trúc của nhóm: robot là "thin client", não AI chạy trên máy tính. |
| **Ảnh đi qua dây USB, không qua WiFi** | Đã thử WiFi ở `cam-selftest`: lag, đứng hình khi quay camera nhanh. USB ổn định, không cần mạng, cắm là chạy. |
| **Tốc độ Serial 4.000.000 baud** (không phải 115200) | 115200 baud ≈ 11KB/giây, chưa được 1 ảnh/giây. 4M baud ≈ 400KB/giây, dư sức cho ~16 ảnh/giây. Đã thử 5M: chip USB CH343 trên board truyền sai bit nên dừng ở 4M. |
| **Bật PSRAM** (`memory_type = qio_opi` trong `platformio.ini`) | Thiếu dòng này firmware coi như board không có PSRAM, camera tụt về 320×240 và rất mờ. Đây là lỗi đã tìm ra ở `cam-selftest`. |
| **Camera và màn hình chạy trên 2 nhân CPU khác nhau** | Gửi 1 ảnh qua USB mất ~30ms. Nếu làm chung một vòng lặp, cứ mỗi lần gửi ảnh mặt robot sẽ khựng lại. Tách ra: nhân 0 lo camera, nhân 1 lo vẽ mặt, nên cả hai cùng mượt. |
| **Ảnh mặc định "tự nhiên"** (không làm nét) | FER+ được train trên ảnh chụp bình thường. Ảnh làm nét quá tay (như ở `cam-selftest`) đẹp với mắt người nhưng tạo viền giả và nhiễu quanh chân mày, khiến AI khó đọc cơ cau mày (cảm xúc "giận"). Bấm `E` để so sánh 2 kiểu. |
| **Laptop tự tắt phần nhận tư thế, bàn tay, đồ vật** của Thái | Các phần đó cần thư viện `torch` + YOLO (vài GB) và không liên quan cảm xúc. Thái đã để sẵn công tắc trong `config/settings.py`; ở đây chỉ gạt công tắc lúc chạy, không sửa file của Thái. |

---

## 3. Phần cứng và nối dây

Board **ESP32-S3-N16R8** (16MB flash, 8MB PSRAM), camera **OV5640** cắm vào khe cáp FPC trên
board, màn **TFT ILI9341 2.4"** nối theo "Sơ đồ 3/3" của trang hướng dẫn lắp ráp:

| Màn TFT | GPIO ESP32-S3 |
|---|---|
| CS | 1 |
| DC | 2 |
| RST | 14 |
| SDI (MOSI) | 38 |
| SCK | 39 |
| VCC + LED | 3V3 (nối cầu VCC với LED ngay trên module vì board chỉ có **1 chân 3V3**) |
| GND | GND |

Camera dùng GPIO 4–13 và 15–18 qua khe FPC (không phải nối dây). Không cắm thêm gì vào các
chân này. Dây USB-C cắm vào cổng **COM** của board (cổng có chip CH343, hiện là `COM3`).

---

## 4. Cấu trúc thư mục

```
cam-emotion/
├── platformio.ini          # cấu hình build firmware (PSRAM, thư viện màn hình)
├── src/
│   ├── main.cpp            # camera + giao tiếp USB + nhận lệnh "face ..."
│   ├── face.cpp / face.h   # vẽ 15 khuôn mặt robot (chép nguyên từ tft-selftest)
├── tools/
│   ├── emotion_viewer.py   # chương trình trên laptop: đọc ảnh, chạy AI của Thái, vẽ cửa sổ, gửi lệnh
│   └── requirements.txt    # thư viện Python (đúng phiên bản Thái dùng)
├── chay-cam-xuc.bat        # bấm đúp để chạy (tự cài môi trường + tự tải mô hình lần đầu)
├── models/                 # 3 file mô hình AI (KHÔNG đưa lên git, .bat tự tải)
└── .venv/                  # môi trường Python riêng (KHÔNG đưa lên git, .bat tự tạo)
```

Yêu cầu: `emotion_viewer.py` import code của Thái (`server/vision`, `config/settings.py`), nên
nó tự dò ngược lên các thư mục cha để tìm repo nhóm. Hai cách đặt đều chạy được:
- `Panda-Robotics-Client-/firmware/kt_firmware/cam-emotion/` (nằm sẵn trong repo nhóm), hoặc
- `MOON/cam-emotion/` với `MOON/Panda-Robotics-Client-/` nằm cạnh.

Nên `git pull` nhánh `develop` của repo nhóm trước để dùng bản AI mới nhất.

---

## 5. Cách chạy (từng bước)

1. **Cắm board** vào laptop bằng dây USB.
2. **Nạp firmware**: mở thư mục `cam-emotion` trong VS Code → thanh PlatformIO → **Upload**.
   *Không* bấm Monitor (xem lỗi thường gặp ở mục 9 vì sao).
   - Nếu kẹt ở `Connecting....`: giữ nút **BOOT**, bấm-nhả **RST**, giữ BOOT thêm 1–2 giây rồi thả.
3. Màn robot hiện **mặt ngủ** + chữ `CHO LAPTOP...` là firmware đã chạy.
4. **Bấm đúp `chay-cam-xuc.bat`**.
   - Lần đầu: tự tạo `.venv`, cài thư viện (vài phút) và tải 3 mô hình (~39MB). Các lần sau mở ngay.
   - Cửa sổ đen hiện `Mo hinh AI da nap: face, emotion, face_details` là AI đã sẵn sàng.
5. Cửa sổ video mở ra. Ngồi trước robot, làm biểu cảm, rồi nhìn mặt robot đổi theo.

**Phím tắt trong cửa sổ video:**

| Phím | Tác dụng |
|---|---|
| `E` | Đổi kiểu ảnh: **tự nhiên** (cho AI, mặc định) ↔ **làm nét** (cho mắt người) |
| `Q` hoặc `Esc` | Thoát |

---

## 6. Cơ chế chi tiết

### 6.1. Phía ESP32 (`src/main.cpp`, `src/face.cpp`)

**Khởi động (`setup()`):**
1. Mở Serial 4M baud, bộ đệm gửi 32KB (để nhét cả 1 ảnh vào hàng đợi, phần cứng tự đẩy dần).
2. Bật màn TFT, vẽ mặt `sleepy` + chữ `CHO LAPTOP...`.
3. Kiểm tra PSRAM. Không có thì báo `LOI PSRAM` lên màn và dừng.
4. Bật camera ở 640×480, JPEG chất lượng 10, 2 bộ đệm ảnh trong PSRAM, xung nhịp 24MHz, xoay
   ảnh 180° (camera lắp ngược). Hỏng thì hiện mặt `dizzy` + `LOI CAMERA`.
5. Đặt ảnh kiểu "tự nhiên", rồi tạo task `cameraTask` chạy riêng trên **nhân 0**.

**Hai việc chạy song song:**

| | Nhân 0 — `cameraTask()` | Nhân 1 — `loop()` |
|---|---|---|
| Lặp mãi | Lấy ảnh mới nhất → gửi qua USB → trả bộ đệm cho camera | Đọc lệnh từ laptop → vẽ khung hình mặt tiếp theo |
| Tốc độ | Theo khả năng camera/USB (~16 ảnh/giây) | ~33 khung hình mặt/giây (`FRAME_US = 30ms`) |

**Khoá Serial (`serialLock`):** 1 ảnh được gửi bằng 3 lệnh `write` (dấu, độ dài, dữ liệu).
Nếu nhân kia chen 1 dòng log vào giữa, laptop đọc sai độ dài và hỏng ảnh. Vì vậy ai muốn ghi
Serial phải "cầm khoá" trước (mutex của FreeRTOS), ghi xong mới trả.

**`CAMERA_GRAB_LATEST`:** nếu USB gửi chậm hơn camera chụp, ảnh cũ bị bỏ qua chứ không xếp
hàng, nên video không bị trễ dần so với thực tế.

**Vẽ mặt (`face.cpp`):** giữ nguyên kỹ thuật của `firmware-demo`: vẽ mắt vào một canvas
240×130 trong RAM rồi đẩy lên màn 1 lần bằng `drawRGBBitmap()` để không nhấp nháy. Dòng chú
thích dưới mặt chỉ vẽ lại khi chữ thay đổi. `faceSetExpression()` bỏ qua lệnh trùng với mặt
đang hiện, nhờ vậy laptop gửi lặp lại cũng không làm hoạt ảnh bị giật về đầu.

### 6.2. Giao thức trên dây USB

**Board → laptop** (liên tục):

```
 'P' 'N' 'D' 'A' │ độ dài (4 byte, little-endian) │ dữ liệu JPEG (bắt đầu FF D8)
 └── dấu nhận dạng ┘
```

Xen giữa các gói ảnh có thể có dòng chữ `[cam] ...` (log). Laptop dò chuỗi `PNDA` để tách:
phần trước dấu là chữ log, phần sau là ảnh. Gói có độ dài vô lý (0 hoặc > 400KB) bị bỏ qua.

**Laptop → board** (mỗi lệnh 1 dòng, kết thúc `\n`):

| Lệnh | Ví dụ | Board làm gì |
|---|---|---|
| `face <tên> <chú thích>` | `face happy VUI` | Đổi mặt + đổi chữ dưới mặt |
| `cam natural` | | Ảnh tự nhiên (sắc nét 0, tương phản 0, bật lọc nhiễu) |
| `cam enhanced` | | Ảnh làm nét (sắc nét +2, tương phản +1, tắt lọc nhiễu) |

Board ghép từng ký tự vào bộ đệm tới khi gặp `\n` chứ không dùng `readStringUntil()`, vì hàm đó
có thể đứng chờ tới 1 giây, làm mặt robot đứng hình.

### 6.3. Phía laptop (`tools/emotion_viewer.py`)

Ba luồng chạy song song (giống cách Thái tách trong `server/vision/runtime/camera.py`):

| Luồng | Làm gì | Vì sao tách riêng |
|---|---|---|
| `reader` | Đọc byte từ USB, tách gói `PNDA`, giải nén JPEG, **chỉ giữ ảnh mới nhất** | Đọc USB phải liên tục, không được chờ AI |
| `ai_worker` | Chạy `VisionEngine.process(ảnh)` của Thái, tối đa 10 lần/giây | AI chậm (theo số đo của Thái: trung vị ~80ms/lần), không được làm giật video |
| chính | Vẽ cửa sổ, gửi lệnh `face ...` xuống board, nhận phím bấm | Giao diện cần phản hồi tức thì |

Gửi lệnh khi cảm xúc **thay đổi**, và **nhắc lại mỗi 2 giây** để board kịp cập nhật nếu vừa bị
reset.

### 6.4. AI của Thái làm gì với 1 ảnh (tóm tắt, chi tiết ở `docs/vision.md` của repo nhóm)

Thái **không tự train** mô hình. Hệ thống ghép 3 mô hình đã train sẵn và luật tự viết:

1. **YuNet** (OpenCV) tìm khung mặt. Không thấy mặt, hoặc mặt nhỏ hơn 60px, thì kết quả là `unknown`.
2. **MediaPipe Face Landmarker** (Google) đo **52 cơ mặt**, mỗi cơ từ 0 đến 1 (cười, cau mày, há miệng…), chạy mỗi ảnh.
3. **FER+** (Microsoft, train trên ~35.000 ảnh mặt) nhìn ảnh mặt xám 64×64 và cho ra xác suất 8 cảm xúc, khoảng 3 lần/giây.
4. **Luật của Thái** (`ExpressionState`) chọn nhãn cuối theo thứ tự ưu tiên: FER+ chắc chắn, rồi FER+ kết hợp cơ mặt cùng đồng ý, rồi chỉ cơ mặt. Nhãn phải **giữ ổn định** 0,18–0,65 giây (tuỳ cảm xúc) mới được công nhận.

### 6.5. Bảng đổi nhãn AI → mặt robot

Robot có 15 khuôn mặt (bộ tên chung với nhóm AI, giống `firmware/panda_firmware`), không có sẵn mặt cho mọi
cảm xúc nên một số được mượn mặt gần nghĩa nhất:

| AI của Thái thấy | Mặt robot | Chữ trên TFT |
|---|---|---|
| `neutral` | `neutral` | BINH THUONG |
| `happy` | `happy` | VUI |
| `surprised` | `surprised` | NGAC NHIEN |
| `sad` | `sad` | BUON |
| `angry` | `angry` | GIAN |
| `disgust` (ghê tởm) | `dizzy` | GHE |
| `fear` (sợ) | `questioning` | SO |
| `contempt` (khinh) | `cool` | KHINH |
| `unknown` (có mặt nhưng chưa chắc) | `thinking` | CHUA RO |
| không thấy mặt | `sleepy` | KHONG THAY AI |

Bảng này nằm ở `ROBOT_FACE` trong `emotion_viewer.py`, muốn đổi thì sửa ở đó. Khác với bản
"mirror" của Thái trong `brain.py`: bản của Thái chỉ nhại 4 cảm xúc (vui/buồn/giận/ngạc nhiên),
phải giữ 1,5 giây mới đổi, và **mặc định đang tắt**. Ở đây nhại đủ 8 cảm xúc để dễ test.

---

## 7. Đọc cửa sổ trên laptop

```
┌──────────── Video 640×480 ────────────┐┌──── Bảng bên phải ────┐
│      ┌──────┐ "Vui"                    ││ Camera 16 khung/s      │
│      │ mặt  │  ← khung xanh = mặt AI   ││ AI 80 ms/lan           │
│      └──────┘    đang theo dõi         ││ -> Man hinh: happy     │
│                                        ││ KET LUAN: Vui          │
│ ┌ Dải chữ vàng (chẩn đoán) ──────────┐ ││ Điểm hợp nhất (8 thanh)│
│ │ Anh: TU NHIEN — phim E de doi      │ ││ Dấu hiệu cơ mặt (7)    │
│ │ GIAN can: cau may 0.31/0.42 THIEU  │ │└────────────────────────┘
│ │ Goc nhin doc (pitch): -22 do       │ │
└────────────────────────────────────────┘
```

| Mục | Ý nghĩa |
|---|---|
| **KET LUAN** + `nguồn` | Nhãn cuối của Thái. Nguồn `fer` = FER+ tự chắc; `fer+landmarks` = FER+ và cơ mặt cùng đồng ý; `landmarks` = chỉ dựa cơ mặt |
| **Điểm hợp nhất** | 75% FER+ + 25% cơ mặt. Chỉ để tham khảo độ tin cậy, **không** phải thứ quyết định nhãn |
| **Dấu hiệu cơ mặt** | Mức hoạt động 7 tổ hợp cơ mặt. Cảm xúc nào mãi không nhận thì nhìn thanh này để biết đang thiếu cơ nào |
| **GIAN can** | 2 điều kiện luật "giận" của Thái: cau mày ≥ 0,42 **và** nheo mắt/mím môi ≥ 0,12 |
| **Goc nhin doc** | Lệch quá 15° nghĩa là camera đang nhìn chéo lên/xuống mặt. Nên đặt robot ngang tầm mắt |

---

## 8. Cách test từng cảm xúc

Ngồi cách robot **40–100cm**, **đủ sáng từ phía trước**, nhìn thẳng, chỉ 1 người trong khung.
Làm biểu cảm hơi "quá lố" như diễn kịch.

| Muốn robot hiện | Làm thế này | Độ khó |
|---|---|---|
| Vui | Cười tươi thấy răng | Dễ |
| Ngạc nhiên | Há miệng **cùng lúc** mở to mắt, nhướng mày | Dễ |
| Bình thường | Mặt thả lỏng | Dễ |
| Giận | Cau mày kéo **thấp và sát**, nheo mắt hoặc mím chặt môi, **giữ ~1 giây** | Vừa |
| Buồn | Nhướng **đầu trong** chân mày (hình "/ \\"), trễ 2 khoé miệng, **giữ ~1 giây** | Khó nhất |
| Ghê | Nhăn mũi, nhếch môi trên | Vừa |
| Sợ | Nhướng mày, trợn mắt, há/kéo căng miệng | Khó |
| Khinh | Nhếch **1 bên** khoé miệng | Vừa |

---

## 9. Lỗi thường gặp

| Hiện tượng | Nguyên nhân → cách sửa |
|---|---|
| Cửa sổ đen báo `KHONG MO DUOC CONG` | Serial Monitor (hoặc `xem-camera.bat` của `cam-selftest`) đang giữ cổng USB. Đóng nó rồi chạy lại. |
| Bấm Monitor thấy toàn ký tự rác | **Bình thường**: dây USB đang chở dữ liệu ảnh. Xem log ở cửa sổ đen của `.bat`. |
| Upload báo `could not open port` | Cửa sổ `chay-cam-xuc.bat` đang mở và giữ cổng. Tắt nó trước khi Upload. |
| Màn robot hiện `LOI PSRAM` | `platformio.ini` thiếu `board_build.arduino.memory_type = qio_opi`. |
| Màn robot hiện mặt chóng mặt + `LOI CAMERA` | Cáp FPC camera lỏng. Rút điện, cắm lại chặt, khoá nẹp. |
| Màn robot cứ hiện `CHO LAPTOP...` | Chưa chạy `.bat`, hoặc `.bat` báo lỗi (đọc cửa sổ đen). |
| Cửa sổ đen báo `THIEU mo hinh` | Tải mô hình hỏng. Xoá file trong `models/` rồi chạy lại `.bat`. |
| Lỗi `Khong tim thay repo Panda-Robotics-Client-` | `cam-emotion/` không nằm trong repo nhóm, cũng không có repo nhóm nằm cạnh (xem mục 4). |
| Nhận "giận"/"buồn" kém hơn webcam laptop | Xem dải chữ vàng: nếu `GIAN can` báo THIEU thì đặt robot **ngang tầm mắt**, tăng sáng, thử phím `E` để so 2 kiểu ảnh. |
| Video giật, ít khung/giây | Tắt bớt chương trình nặng trên laptop. AI dùng CPU, không dùng card đồ hoạ. |

---

## 10. Hiện trạng và giới hạn

- **Đã kiểm chứng:** firmware build thành công. Camera + USB 4M baud đã đo ở `cam-selftest`:
  640×480, ~16,5 ảnh/giây, không mất gói. Engine của Thái nạp và chạy được trên laptop. Logic đổi
  nhãn và giao diện cửa sổ đã chạy thử.
- **Chưa đo trên bản ghép này:** số ảnh/giây khi camera **và** màn hình cùng chạy, và độ chính xác
  từng cảm xúc trên camera robot. Thái cũng ghi rõ: **chưa có bộ dữ liệu gán nhãn để đo độ chính xác**.
  Kết quả là "biểu cảm nhìn thấy", không phải cảm xúc thật trong lòng.
- **Chỉ 1 người, 1 robot, cần laptop cắm dây.** Không có nhận diện chủ nhân (thiếu mô hình SFace,
  không cần cho cảm xúc).

## 11. Bước tiếp theo — ghép vào hệ thống thật

Khi robot chạy WiFi + MQTT như thiết kế của nhóm:
1. Bỏ đường USB. ESP32 gửi ảnh lên server, `server/vision` của Thái xử lý như hiện tại.
2. `brain.py` publish tên mặt lên topic `moon/cmd/face` (bật `EMOTION_MIRROR = True`). Từ
   27/09/2026 toàn bộ topic MQTT của nhóm đã đổi tiền tố `panda/` → `moon/`.
3. Firmware chỉ cần nhận topic đó và gọi `faceSetExpression(tên)`. Phần vẽ mặt trong `face.cpp`
   giữ nguyên.
