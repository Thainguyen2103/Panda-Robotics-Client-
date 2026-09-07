#pragma once

// Định nghĩa tập trung toàn bộ chân GPIO dùng trong demo — tách riêng để các module
// (display/input/network/audio_i2s) không phải khai báo trùng lặp số chân rải rác nhiều nơi.

// OLED (I2C) — dùng chân I2C mặc định của ESP32 (Wire mặc định), không cần khai báo lại
// trong diagram.json vì thư viện Wire tự biết SDA=21/SCL=22 trên board esp32dev.
#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22
#define OLED_I2C_ADDRESS 0x3C
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

// 2 nút bấm mô phỏng kết quả chấm đúng/sai (thay cho STT/AI thật).
#define PIN_BTN_CORRECT 25
#define PIN_BTN_WRONG 26

// Nút thứ 3: mỗi lần bấm chuyển sang biểu cảm OLED kế tiếp (xem display.h) — cách test
// 14 biểu cảm không cần gõ lệnh Serial, dùng khi Serial Monitor của VS Code không nhận input.
#define PIN_BTN_FACE 27

// Mic I2S (INMP441 thật sẽ gắn ở Tuần 9) — chọn 32/33/34 để không đụng chân I2C (21/22)
// và 2 nút bấm (25/26) ở trên.
// GPIO34 CHỈ đọc được (input-only, không có driver output) trên ESP32 — hợp lý để làm chân
// SD vì hướng đi của SD luôn là ESP32 NHẬN dữ liệu từ mic, không bao giờ gửi ra.
#define PIN_I2S_SCK 32
#define PIN_I2S_WS 33
#define PIN_I2S_SD 34
