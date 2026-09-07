#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// ================================================================
//  CẤU HÌNH PHẦN CỨNG & HỆ THỐNG PANDA ROBOT
// ================================================================

// Bật cờ này khi nạp vào ESP32 thật có WiFi & MQTT Broker
// Tắt cờ này khi chạy mô phỏng Wokwi hoặc Serial Monitor
// #define USE_MQTT

#ifdef USE_MQTT
  const char* WIFI_SSID = "WIFI_NAME";
  const char* WIFI_PASS = "WIFI_PASSWORD";
  const char* MQTT_HOST = "192.168.1.10";
  const int   MQTT_PORT = 1883;
#endif

// Bật cờ này nếu robot có lắp servo tay vẫy
// #define HAS_ARM

// ================================================================
//  QUY HOẠCH CHÂN GPIO (ĐÃ TỐI ƯU TRÁNH XUNG ĐỘT SPI)
// ================================================================

// 1. Màn hình màu ILI9341 TFT-LCD (Giao tiếp SPI)
#define TFT_CS    5    // VSPI Chip Select
#define TFT_RST   4    // Hardware Reset
#define TFT_DC    2    // Data / Command
#define TFT_MOSI  23   // SPI Data In (SDI)
#define TFT_SCK   18   // SPI Clock (SCK)
#define TFT_MISO  19   // SPI Data Out (SDO)

// 2. Cảm biến siêu âm HC-SR04 (Đổi sang 13/12 để nhường 4/5 cho SPI)
#define PIN_TRIG  13
#define PIN_ECHO  12
#define PIN_POT   34   // Núm xoay giả lập khoảng cách trên Wokwi

// 3. Còi Buzzer & Nút nhấn
#define PIN_BUZZ  15   // Đổi sang 15 để nhường 18 cho SPI SCK
#define PIN_BTN   35   // Nút bấm tương tác (Input only)

// 4. Mạch điều khiển động cơ L298N / TB6612FNG
#define PIN_PWMA  25   // Tốc độ bánh trái
#define PIN_AIN1  26   // Hướng bánh trái 1
#define PIN_AIN2  27   // Hướng bánh trái 2
#define PIN_PWMB  32   // Tốc độ bánh phải
#define PIN_BIN1  33   // Hướng bánh phải 1
#define PIN_BIN2  14   // Hướng bánh phải 2

// 5. Servo tay (nếu bật HAS_ARM)
#define PIN_SERVO 21

// ================================================================
//  KÍCH THƯỚC MÀN HÌNH & VÙNG ĐỆM FRAME-BUFFER
// ================================================================
#define SCREEN_W  320
#define SCREEN_H  240

// Canvas chỉ bao vùng chuyển động của mắt: 170 × 100 × 2 = 34KB RAM.
// Ở 60 FPS cần truyền 2.04MB/s, nằm an toàn dưới SPI 40MHz (~5MB/s lý thuyết).
#define CANVAS_W  170
#define CANVAS_H  100
#define CANVAS_X  75   // (320 - 170) / 2
#define CANVAS_Y  70   // (240 - 100) / 2

// 60 FPS chính xác theo microsecond; blink đóng nhanh, giữ sâu rồi mở mềm.
#define FACE_FRAME_US          16667UL
#define FACE_MOTION_SPEED      1.75f
#define FACE_BLINK_CLOSE_MS    70UL
#define FACE_BLINK_HOLD_MS     70UL
#define FACE_BLINK_OPEN_MS     110UL
#define FACE_BLINK_MS          (FACE_BLINK_CLOSE_MS + FACE_BLINK_HOLD_MS + FACE_BLINK_OPEN_MS)
#define FACE_MIN_EYE_OPEN      3

// ================================================================
//  BẢNG MÀU 16-BIT RGB565 CHUẨN DASHBOARD WEB
// ================================================================
#define COLOR_BG        0x0823 // #080c18 - Nền Dark Navy sâu thẳm
#define COLOR_BLACK     0x0000 // Đen tuyệt đối
#define COLOR_CYAN      0x067F // #00d2ff - Accent Cyan đặc trưng
#define COLOR_CYAN_DIM  0x0338 // Cyan nhạt cho viền glow
#define COLOR_GREEN     0x2EB6 // #2ed573 - Xanh lá hearing & sonar
#define COLOR_RED       0xF9C7 // #ff3838 - Đỏ sad & REC dot
#define COLOR_ORANGE    0xFD40 // #ffaa00 - Cam ngạc nhiên surprised
#define COLOR_PURPLE    0xA4DF // #a29bfe - Tím sleepy & AI Core
#define COLOR_PINK      0xF9B0 // #ff3385 - Hồng tình yêu love heart
#define COLOR_CUTE_PINK 0xFBAC // #ff7675 - Hồng cute ấm áp
#define COLOR_YELLOW    0xFE75 // #fdcb6e - Vàng sao quay dizzy
#define COLOR_TEAL      0x0455 // #0088aa - Xanh đậm tức giận angry
#define COLOR_WHITE     0xFFFF // Trắng tinh khôi
#define COLOR_DARK_GRAY 0x18E3 // Xám đen bóng tròng kính
#define COLOR_GLOW_LINE 0x4D3F // Viền kính

#endif // CONFIG_H
