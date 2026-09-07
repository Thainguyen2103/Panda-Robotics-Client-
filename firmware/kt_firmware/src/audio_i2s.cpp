// Module học I2S (Tuần 3) — mục đích là HỌC cơ chế, KHÔNG phải xử lý âm thanh thật.
//
// QUAN TRỌNG cần hiểu trước khi đọc code bên dưới:
// Wokwi (tính đến 09/2026) CHƯA mô phỏng được linh kiện mic I2S thật (INMP441) — theo
// docs.wokwi.com/guides/esp32, I2S đang ở trạng thái "in progress". Vì vậy KHÔNG có cách
// nào gắn mic ảo vào diagram.json và nhận dữ liệu âm thanh thật trong trình mô phỏng.
//
// Module này vẫn có giá trị học tập vì:
//   1. Khởi tạo I2S đúng chân/thông số như khi gắn INMP441 thật (Tuần 9 khi có phần cứng
//      thật chỉ cần cắm dây, không phải viết lại code).
//   2. Dạy đúng API thật của Arduino-ESP32 (I2S.begin/available/read) thay vì code giả.
//   3. Dữ liệu đọc được sẽ luôn là 0/nhiễu vì không có mic thật gửi tín hiệu vào chân SD —
//      đây là kết quả ĐÚNG NHƯ MONG ĐỢI trong Wokwi, không phải lỗi code.
#include "audio_i2s.h"
#include "pins.h"
#include <I2S.h>

static bool i2sReady = false;
static unsigned long lastLogMs = 0;
static const unsigned long LOG_INTERVAL_MS = 3000;

bool audioI2sSetup()
{
  // sd/outSd/inSd dùng chung 1 chân vì ta chỉ NHẬN (RX) từ mic, không bao giờ gửi dữ liệu
  // ra I2S — không cần chân data-out riêng.
  I2S.setAllPins(PIN_I2S_SCK, PIN_I2S_WS, PIN_I2S_SD, PIN_I2S_SD, PIN_I2S_SD);

  // 16000Hz / 16-bit là cấu hình được chính thư viện I2S của Arduino-ESP32 khuyến nghị
  // (xem cảnh báo log_w trong I2S.cpp nếu dùng thông số khác) — INMP441 thật hỗ trợ tốt mức này.
  i2sReady = I2S.begin(I2S_PHILIPS_MODE, 16000, 16) != 0;

  Serial.print("[i2s] Khoi tao mic I2S (SCK=");
  Serial.print(PIN_I2S_SCK);
  Serial.print(" WS=");
  Serial.print(PIN_I2S_WS);
  Serial.print(" SD=");
  Serial.print(PIN_I2S_SD);
  Serial.print("): ");
  Serial.println(i2sReady ? "OK" : "THAT BAI");

  return i2sReady;
}

void audioI2sLoop()
{
  if (!i2sReady)
  {
    return;
  }

  unsigned long now = millis();
  if (now - lastLogMs < LOG_INTERVAL_MS)
  {
    return;
  }
  lastLogMs = now;

  int available = I2S.available();
  Serial.print("[i2s] I2S.available() = ");
  Serial.print(available);
  Serial.println(" byte (0 la binh thuong: Wokwi chua mo phong mic that gui du lieu vao chan SD)");
}
