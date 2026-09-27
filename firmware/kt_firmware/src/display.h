#pragma once
#include <Arduino.h>

// Khởi tạo màn hình TFT ILI9341 + vẽ khung nền. Gọi 1 lần trong setup().
void displaySetup();

// Đổi biểu cảm hiện tại (reset lại animation từ khung 0). Nếu đang ở chế độ từ vựng thì
// hàm này cũng đưa màn hình quay về chế độ khuôn mặt. Tên hợp lệ — đồng bộ với
// server/virtual_robot.py và firmware/panda_firmware của bạn AI (topic MQTT panda/cmd/face):
//   neutral, happy, sad, angry, surprised, sleepy, wink, love, cool, cute, dizzy,
//   questioning, hearing, thinking, speaking
// Tên không nhận diện được -> vẽ như "neutral" (không báo lỗi, không crash).
void displaySetExpression(const char *expression);

// Chuyển sang CHẾ ĐỘ TỪ VỰNG: che khuôn mặt, hiện từ cần học chiếm trọn màn hình
// (Kanji rất to ở giữa, Kana phía dưới, tiếng Anh phía trên).
//   english — chữ Latin, ví dụ "dog" (bắt buộc)
//   kanji   — chữ Hán tiếng Nhật, ví dụ "犬" (để "" nếu từ đó không có Kanji)
//   kana    — cách đọc bằng Kana, ví dụ "いぬ" (để "" nếu không muốn hiện)
// Cả 3 tham số là chuỗi UTF-8. Nếu kanji rỗng thì kana được vẽ to thay chỗ của kanji.
// Đây là cửa DUY NHẤT để đổi từ vựng: hiện tại được gọi từ main.cpp (nút bấm + lệnh
// Serial), sau này khi bật lại MQTT thì topic panda/cmd/word gọi đúng hàm này.
//
// Quay lại khuôn mặt bằng cách gọi displaySetExpression() — không có hàm riêng để thoát.
void displaySetWord(const char *english, const char *kanji, const char *kana);

// Gọi mỗi vòng loop(): dựng khung hình kế tiếp của biểu cảm hiện tại rồi bắn lên màn.
// Tự giới hạn tốc độ khung hình bên trong, gọi bao nhiêu lần cũng không hại.
void displayLoop();
