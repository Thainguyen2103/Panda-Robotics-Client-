# body-test — thử phần thân: 2 bánh + cảm biến vật cản

> Tên thư mục hơi lệch với nội dung: `so-do-noi-day.html` trong thư mục này thật ra là sơ đồ
> nối dây dùng chung cho **cả THÂN lẫn ĐẦU** (1 breadboard, test lắp tổng thể) — không chỉ
> riêng phần thân. Mic INMP441 nằm ở nửa ĐẦU của sơ đồ đó (board ESP32-S3, chạy `head-demo`),
> không phải ở board thân (ESP32 DevKit C) mà file `main.cpp` trong thư mục này điều khiển.

Nối dây đúng sơ đồ breadboard BODY trong `bao-cao/moon-lap-rap.html`
(TB6612: PWMA 25, AIN1 26, AIN2 27, PWMB 32, BIN1 33, BIN2 14, STBY→3V3 · HC-SR04: TRIG 13, ECHO 18 qua 1kΩ/2,2kΩ).

1. Cắm USB board **ESP32 DevKit C**, mở thư mục `body-test` trong VS Code → **Upload**.
2. **Kê đế lên** cho bánh quay trên không.
3. Bấm đúp **`chay-test.bat`**.

| Phím (giữ) | Việc |
|---|---|
| **L** | bánh trái quay |
| **R** | bánh phải quay |
| L + R | cả 2 bánh (xe đi thẳng) |
| **+ / -** | nhanh / chậm (mặc định 150/255) |
| **Q** / Esc | thoát (bánh dừng) |

**WiFi (khi thân cắm sạc dự phòng, điều khiển từ `head-demo`):** chép `src/wifi_secrets.example.h`
thành `src/wifi_secrets.h`, điền WiFi **2.4GHz** (hotspot laptop/điện thoại), Upload. Board vẫn
nhận lệnh qua dây USB như cũ; WiFi chỉ thêm đường thứ 2 (UDP: lệnh cổng 4211, trạng thái cổng 4210).
Bật hotspot trước hay cấp nguồn board trước đều được: board tự thử nối lại WiFi mỗi 8 giây.
**Nạp code qua WiFi (OTA)** sau khi đã nạp bản này 1 lần bằng dây: `pio run -e ota -t upload`
(lần đầu Windows hỏi tường lửa cho python → Allow; không tìm thấy `panda-body.local` thì sửa
`upload_port` trong `platformio.ini` thành IP board). Đang nạp thì bánh tự khoá.

Luật an toàn chạy **trên board**:
- Vật cản gần hơn **12cm** → cấm đi thẳng (giữ L+R cũng không quay), nhưng vẫn rẽ được (giữ 1 phím, chỉ 1 bánh quay) để xe xoay mặt khỏi vật cản. Vật ra xa hơn **16cm** thì đi thẳng lại được.
- Mất lệnh từ laptop quá **0,5 giây** (tắt chương trình, rút cáp) → dừng.

| Hiện tượng | Sửa |
|---|---|
| Giữ L mà bánh **lùi** | `src/main.cpp`: đổi `INVERT_LEFT` thành `true` (bánh phải: `INVERT_RIGHT`), nạp lại |
| Giữ L mà bánh **phải** quay | Dây motor cắm nhầm AO ↔ BO: đổi chỗ 2 cặp dây motor |
| Bánh không quay, chữ vẫn báo "chay duoc" | STBY chưa lên 3V3, VM chưa có 5V, hoặc GND chưa chung |
| HC-SR04 luôn "khong co vat" | Kiểm tra VCC 5V, chia áp ECHO, chân TRIG 13 / ECHO 18 |
| Board tự khởi động lại khi bánh quay | Nguồn USB yếu: giảm tốc độ (`-`), có tụ 1000µF, sau này dùng pin |
