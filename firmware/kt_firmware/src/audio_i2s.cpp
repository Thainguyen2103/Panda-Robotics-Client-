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
//
// CỜ BẬT/TẮT (bổ sung 08/09/2026): mặc định TẮT khi chạy Wokwi, xem platformio.ini.
// Lý do: trong Wokwi module này luôn đọc ra 0 byte (không có mic ảo), tức không cho thêm
// thông tin gì lúc chạy, nhưng I2S.begin() lại chiếm khá nhiều RAM: riêng task nền của
// thư viện đã xin 20.000 byte stack, cộng thêm 2 ring buffer và các DMA buffer. Bản demo
// giờ còn phải nuôi thêm 62KB khung đệm màn hình TFT, nên RAM đã chật hơn trước nhiều.
// Tắt ở đây KHÔNG mất giá trị học tập: toàn bộ code + giải thích bên dưới vẫn giữ nguyên,
// chỉ cần đổi cờ thành 1 là chạy lại đúng như cũ khi có mic INMP441 thật (Tuần 9).
#ifndef ENABLE_I2S_MIC
#define ENABLE_I2S_MIC 0
#endif

#include "audio_i2s.h"
#include "pins.h"

#if ENABLE_I2S_MIC
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

#else // ENABLE_I2S_MIC == 0 -> bản mô phỏng: không khởi tạo I2S, không chiếm RAM

bool audioI2sSetup()
{
  Serial.println("[i2s] Da TAT (ENABLE_I2S_MIC=0) — bat lai trong platformio.ini khi co mic that");
  return false;
}

void audioI2sLoop() {}

#endif // ENABLE_I2S_MIC
