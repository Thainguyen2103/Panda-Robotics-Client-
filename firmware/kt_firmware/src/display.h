#pragma once
#include <Arduino.h>

// Khởi tạo màn hình TFT ILI9341 + vẽ khung nền. Gọi 1 lần trong setup().
void displaySetup();

// Đổi biểu cảm hiện tại (reset lại animation từ khung 0). Tên hợp lệ — đồng bộ với
// server/virtual_robot.py và firmware/panda_firmware của bạn AI (topic MQTT panda/cmd/face):
//   neutral, happy, sad, angry, surprised, sleepy, wink, love, cool, cute, dizzy,
//   questioning, hearing, thinking, speaking
// Tên không nhận diện được -> vẽ như "neutral" (không báo lỗi, không crash).
void displaySetExpression(const char *expression);

// Cập nhật từ vựng + bộ đếm đúng/sai ở viền trên/dưới màn (không đụng vùng mặt).
void displaySetStats(const char *word, int correctCount, int wrongCount);

// Gọi mỗi vòng loop(): dựng khung hình kế tiếp của biểu cảm hiện tại rồi bắn lên màn.
// Tự giới hạn tốc độ khung hình bên trong, gọi bao nhiêu lần cũng không hại.
void displayLoop();
