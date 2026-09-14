#pragma once

// Định nghĩa tập trung toàn bộ chân GPIO dùng trong demo — tách riêng để các module
// (display/input/network/audio_i2s) không phải khai báo trùng lặp số chân rải rác nhiều nơi.

// ---------------------------------------------------------------------------
// Màn hình TFT ILI9341 2.4" 320x240 (SPI) — thay cho OLED SSD1306 128x64 (I2C).
//
// PHẢI dùng đúng bộ chân VSPI PHẦN CỨNG của ESP32 (SCK=18, MISO=19, MOSI=23): nếu chọn
// chân khác, thư viện SPI buộc phải "đập bit" bằng phần mềm (bit-bang) — chậm hơn hàng
// chục lần, không đủ để bắn khung hình 62KB mỗi 30ms cho animation.
//
// Bộ chân này khớp 1:1 với Config.h trong firmware của bạn AI
// (Panda-Robotics-Client-/firmware/panda_firmware/Config.h) để 2 bên nạp chung 1 mạch
// phần cứng thật mà không phải đấu lại dây.
//
// Lưu ý phần cứng thật: GPIO2 là chân strapping (quyết định chế độ boot). Nối vào D/C
// vẫn an toàn vì màn hình chỉ NHẬN tín hiệu từ ESP32, không tự kéo chân này lên/xuống.
// ---------------------------------------------------------------------------
#define TFT_CS 5
#define TFT_RST 4
#define TFT_DC 2
#define TFT_MOSI 23
#define TFT_SCK 18
#define TFT_MISO 19

// Kích thước SAU khi gọi setRotation(1) -> màn nằm ngang.
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240

// 2 nút bấm mô phỏng kết quả chấm đúng/sai (thay cho STT/AI thật).
// Chỉ còn đúng 2 nút: nút thứ 3 "đổi biểu cảm" đã bỏ vì bây giờ khi không ai bấm gì,
// robot tự luân chuyển biểu cảm (xem handleIdleFaces() trong main.cpp).
#define PIN_BTN_CORRECT 25
#define PIN_BTN_WRONG 26

// Mic I2S (INMP441 thật sẽ gắn ở Tuần 9) — chọn 32/33/34 để không đụng chân SPI của màn
// hình (2/4/5/18/19/23) và 2 nút bấm (25/26) ở trên.
// GPIO34 CHỈ đọc được (input-only, không có driver output) trên ESP32 — hợp lý để làm chân
// SD vì hướng đi của SD luôn là ESP32 NHẬN dữ liệu từ mic, không bao giờ gửi ra.
#define PIN_I2S_SCK 32
#define PIN_I2S_WS 33
#define PIN_I2S_SD 34
