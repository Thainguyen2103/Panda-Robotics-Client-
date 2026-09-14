#pragma once
#include <Arduino.h>

// Khởi tạo I2S ở chế độ nhận (RX) với chân/thông số giống mic INMP441 thật.
// Trả về true nếu driver khởi tạo thành công (KHÔNG có nghĩa là đã nhận được âm thanh thật
// — xem giải thích chi tiết trong audio_i2s.cpp và WEEKLY_LOGIC.md).
bool audioI2sSetup();

// Gọi mỗi vòng loop(). Định kỳ đọc thử dữ liệu I2S và log ra Serial để quan sát cơ chế.
void audioI2sLoop();
