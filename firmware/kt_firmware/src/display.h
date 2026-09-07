#pragma once
#include <Arduino.h>

// Khởi tạo màn hình OLED. Gọi 1 lần trong setup().
void displaySetup();

// Đổi biểu cảm hiện tại và vẽ lại ngay. Tên hợp lệ (đồng bộ với server/virtual_robot.py
// và firmware/panda_firmware.ino của bạn AI trong nhóm, topic MQTT panda/cmd/face):
//   neutral, happy, sad, angry, surprised, sleepy, wink, love, cool, cute, dizzy,
//   questioning, thinking, speaking
// Tên không nhận diện được -> vẽ như "neutral" (không báo lỗi, không crash).
void displaySetExpression(const char *expression);

// Cập nhật từ vựng + bộ đếm đúng/sai hiển thị phía trên/dưới mặt (không đổi biểu cảm).
void displaySetStats(const char *word, int correctCount, int wrongCount);

// Gọi mỗi vòng loop(): vẽ lại khung hình kế tiếp cho 2 biểu cảm ĐỘNG (thinking/speaking).
// Với biểu cảm tĩnh thì hàm này không làm gì (không tốn CPU vẽ lại liên tục vô ích).
void displayLoop();
