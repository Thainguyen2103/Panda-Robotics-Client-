# Phân công phần Firmware nhúng — Khoa & Thắng

> Bổ sung chi tiết cho bảng "Lộ trình theo tuần" trong [PROJECT.md](PROJECT.md) — file đó
> chỉ ghi ai làm gì tuần nào (tag `-Thắng` / `-Khoa & Thắng`), file này giải thích **vì sao
> chia như vậy** và **cách 2 người cùng sửa code mà không giẫm chân nhau**.

## 1. Vì sao chia theo HEAD/BODY

Theo BOM phần cứng thật (xem `README.md`), robot có **2 board ESP32 riêng biệt**:

- **HEAD** (đầu): OLED ×2 (mắt/biểu cảm), mic INMP441 (I2S), loa, WiFi/MQTT — nơi robot
  "nói chuyện" và hiển thị.
- **BODY** (thân): motor DC + TB6612FNG, HC-SR04 (né vật cản), buzzer, nút bấm — nơi robot
  "di chuyển/phản ứng vật lý".

Đây là ranh giới tự nhiên, tách rời cả về phần cứng lẫn code, gần như không có phụ thuộc
chéo — hợp lý để chia việc công bằng và rõ ràng trách nhiệm:

| | Khoa | Thắng |
|---|---|---|
| Board phụ trách | HEAD | BODY |
| Module code (`firmware/kt_firmware/src/`) | `display.*`, `network.*`, `audio_i2s.*`, phần OLED/MQTT trong `main.cpp` | `motor.*`, `ultrasonic.*`, `buzzer.*` (mới tạo), phần motor/cảm biến trong `main.cpp` |
| Vai trò theo README | Firmware nhúng & AI | Vi điều khiển & Báo cáo |
| Trọng tâm | Tích hợp AI (STT/fuzzy-matching → OLED), kiến trúc firmware tổng thể (đã dựng ở Tuần 2–3) | Điều khiển động cơ, cảm biến, và **chủ trì tài liệu/báo cáo/video demo** cuối kỳ (Tuần 14–15) |

Khối lượng công việc 2 bên tương đương: Khoa đã làm trọn Tuần 2–3 một mình (lúc Thắng chưa
tham gia) và tiếp tục chủ lực Tuần 4–5, 11; Thắng chủ lực Tuần 6–8 (né vật cản, động cơ) và
chủ trì Tuần 14 (báo cáo) — các tuần còn lại (9, 10, 12, 13, 15) làm chung theo đúng ranh
giới HEAD/BODY ở trên.

## 2. Quy ước đặt tên file — để git ít conflict, dễ biết ai đụng gì

Trong `Panda-Robotics-Client-/firmware/kt_firmware/src/`:

- File đã có (Khoa): `main.cpp`, `pins.h`, `display.*`, `input.*`, `network.*`, `audio_i2s.*`.
- File Thắng sẽ tạo mới: `motor.h`/`motor.cpp` (điều khiển L298N/TB6612FNG + PWM),
  `ultrasonic.h`/`ultrasonic.cpp` (HC-SR04), `buzzer.h`/`buzzer.cpp`.
- **`pins.h`**: định nghĩa GPIO tập trung, cả 2 người đều động vào — khi thêm chân mới, mỗi
  người tự thêm đúng phần mình (không xoá/sửa chân người kia đã khai báo), và nhắn cho nhau
  biết đã thêm chân gì để tránh trùng số GPIO.
- **`main.cpp`**: điểm duy nhất cả 2 cùng sửa thường xuyên (setup()/loop() gọi cả module HEAD
  lẫn BODY) — xem mục 4 bên dưới về cách tránh conflict ở đây.

## 3. Git — mỗi người 1 nhánh, làm chung 1 thư mục (đã quyết định 08/09/2026)

Đã ghi chi tiết đầy đủ ở `gitrule.md` (local, không push) — tóm tắt lại phần liên quan đến
phân công:

```bash
git clone https://github.com/Thainguyen2103/Panda-Robotics-Client-.git
cd Panda-Robotics-Client-
git checkout develop && git pull origin develop
git checkout -b feature/thang-motor-control      # Thắng
git checkout -b feature/khoa-<task>              # Khoa (đã có nhánh feature/khoa-w3-i2s-module)
```

- Cả 2 làm trong cùng `firmware/kt_firmware/`, nhưng **nhánh riêng, PR riêng vào `develop`**.
- Vì chia module theo bảng ở mục 2 (file khác nhau phần lớn), khi mở PR gần như không đụng
  conflict — chỉ cần cẩn thận ở `main.cpp` và `pins.h`.

## 4. Cách 2 người vẫn hiểu và sửa được code của nhau (không làm việc kiểu "hộp đen")

Mục tiêu: dù chia việc theo module, **cuối kỳ cả 2 phải đủ hiểu để tự sửa cả 2 phần** khi
tích hợp cuối (Tuần 9–13) hoặc khi 1 người vắng mặt lúc bảo vệ đồ án. Quy tắc:

- Mỗi module mới (`motor.*`, `ultrasonic.*`, `buzzer.*`, ...) bắt buộc có **comment ngắn ở
  đầu file** nêu: module này làm gì, hàm public nào để gọi từ `main.cpp`, và tham số/đơn vị
  đo (vd tốc độ PWM 0–255, khoảng cách cm) — không cần giải thích dài, chỉ cần đủ để người
  còn lại đọc là gọi được hàm mà không cần hỏi.
- Trước khi mở PR vào `develop`, người còn lại nên đọc lướt qua diff 1 lần (review nhanh
  ngay trên GitHub) — không phải để bắt lỗi kỹ thuật sâu, mà để cả 2 luôn biết code hiện tại
  trông như thế nào.
- Tuần 9 (chuyển sang phần cứng thật, nếu có) và Tuần 12–13 (kiểm thử/code freeze) là các
  mốc bắt buộc **ngồi chung xem lại toàn bộ `main.cpp`** — đây là lúc 2 module HEAD/BODY
  thật sự chạy chung 1 vòng `loop()`, cần cả 2 cùng hiểu điểm nối để không phá code của nhau.
- Tuần 14 (Thắng chủ trì viết tài liệu kỹ thuật) là dịp tổng hợp lại toàn bộ kiến trúc thành
  văn bản — cả 2 cùng đọc lại tài liệu này 1 lượt trước khi bảo vệ, coi như "ôn lại" phần
  của người kia.
