# kt_firmware — Demo firmware ESP32 (mô phỏng Wokwi)

Thư mục dùng chung cho phần "Firmware nhúng" (Khoa + bạn nhúng thứ 2), phát triển bằng
PlatformIO + Wokwi (chưa cần phần cứng thật). Đây là bản demo minh hoạ luồng
**ESP32 → màn hình → WiFi/MQTT → Web dashboard**, sẽ tiếp tục mở rộng qua các tuần và
tích hợp dần với phần AI/backend ở `server/` cùng repo. Mỗi người làm trên nhánh
`feature/<tên riêng>-...` của mình rồi PR vào `develop`, không có nhánh chung.

## Chạy thử (không cần phần cứng)

1. Cài VS Code + extension **PlatformIO IDE** + **Wokwi for VS Code**.
2. Mở thư mục này (`firmware/kt_firmware/`) trong VS Code.
3. Build: `pio run`.
4. `F1` → `Wokwi: Start Simulator` để mô phỏng ESP32 + màn TFT ILI9341 + 2 nút bấm.
5. Mở `web-dashboard/index.html` bằng trình duyệt để xem dashboard — **xem lưu ý về MQTT
   bên dưới trước khi dùng**.

## Cách tương tác

Màn hình có 2 chế độ loại trừ nhau, mỗi nút phụ trách một chế độ:

| Nút | Chân | Công dụng |
|---|---|---|
| Nút 1 | GPIO 25 | **Đổi biểu cảm** — lần lượt đi qua 15 biểu cảm. Đang xem từ vựng mà bấm nút này thì quay về khuôn mặt. |
| Nút 2 | GPIO 26 | **Hiện từ vựng** — che khuôn mặt, hiện từ cần học chiếm trọn màn (Kanji rất to ở giữa, Kana dưới, tiếng Anh trên). Bấm tiếp = sang từ kế tiếp trong 9 từ demo. |

Hai lệnh gõ được qua Serial Monitor: `face <tên>` (ví dụ `face love`) và
`word <anh> <kanji> <kana>` (ví dụ `word cat 猫 ねこ`).

## Cấu trúc

```
src/
├── main.cpp        # setup()/loop(), điều phối các module bên dưới
├── pins.h          # định nghĩa chân GPIO tập trung
├── display.h/.cpp  # TFT ILI9341 — 15 biểu cảm có animation (đồng bộ với
│                     firmware/panda_firmware/) + màn hiển thị từ vựng Anh/Nhật
├── input.h/.cpp    # đọc 2 nút bấm (debounce + edge detect)
├── network.h/.cpp  # WiFi + MQTT (connect/reconnect/publish, non-blocking)
└── audio_i2s.h/.cpp# học I2S (mic INMP441 — Wokwi chưa mô phỏng I2S thật)
web-dashboard/
└── index.html      # dashboard tĩnh, subscribe MQTT-over-WebSocket bằng mqtt.js
```

## Hiển thị tiếng Nhật (Kana + Kanji)

Font dựng sẵn của `Adafruit_GFX` chỉ có ASCII nên không vẽ được chữ Nhật. Phần này dùng
thư viện `U8g2_for_Adafruit_GFX` + font `u8g2_font_b16_t_japanese2` (~90KB flash). 3 điểm
cần biết trước khi sửa `display.cpp`:

1. Mỗi chữ Nhật chiếm **3 byte** UTF-8 → không dùng `String::length()` để căn giữa, phải
   đo bằng `getUTF8Width()`.
2. `u8g2.drawUTF8()` nhận toạ độ **baseline**, khác `tft.setCursor()` nhận góc trên-trái.
3. `getFontAscent()` trả về chiều cao chữ **'A' Latin** (10px) trong khi nét Kanji cao tới
   14px trên baseline — dùng nó làm mép trên sẽ cắt cụt đầu chữ. Hàm `drawUtf8Centered()`
   vẽ vào một `GFXcanvas1` rộng rãi rồi dò lại vị trí nét chữ thật để tránh lỗi này.

Chữ nằm ngoài tập con Kanji của font sẽ hiện ra **khoảng trắng, không báo lỗi**; code có
log cảnh báo ra Serial, cách khắc phục là đổi `FONT_JP` sang `u8g2_font_b16_t_japanese3`
(tốn thêm ~71KB flash).

## Lưu ý tích hợp

- Biểu cảm (`neutral/happy/sad/angry/surprised/sleepy/wink/love/cool/cute/dizzy/
  questioning/hearing/thinking/speaking`) và bảng chân SPI của màn được giữ khớp với
  `firmware/panda_firmware/` để 2 firmware nạp chung một mạch thật mà không phải đấu lại dây.
- **WiFi/MQTT đang TẮT** bằng cờ `-D ENABLE_MQTT=0` trong `platformio.ini` (để vòng test
  phần hiển thị chạy nhẹ, không phải chờ WiFi 15 giây mỗi lần khởi động). Ở trạng thái này
  firmware không publish gì, các message lẽ ra gửi đi được in ra Serial. Đổi cờ thành `1`
  để bật lại mạng.
- Demo publish trên broker công cộng `broker.hivemq.com` với topic riêng
  `panda/demo/khoa/word` (khác namespace `panda/cmd/*` / `panda/status` mà `server/brain.py`
  dùng) — sẽ đổi sang namespace + broker thật khi tích hợp end-to-end.
- Bản demo **không còn chấm điểm đúng/sai** (trước đây 2 nút giả lập việc này). Điểm số thật
  sẽ do `server/` tính từ kết quả STT/fuzzy-matching rồi gửi xuống. `web-dashboard/index.html`
  vẫn đang nghe 2 topic cũ `panda/demo/khoa/result` và `.../progress` nên hiện không nhận
  được gì — cần cập nhật khi quay lại làm phần dashboard.
- Khi ghép với AI thật: cho topic nhận từ vựng gọi thẳng `displaySetWord(english, kanji, kana)`
  trong `display.h` — đó là cửa duy nhất để đổi từ đang hiển thị, không cần sửa `display.cpp`.
