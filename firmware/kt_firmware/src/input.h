#pragma once
#include <Arduino.h>

// Kết quả đọc được của 1 lượt inputPoll(): None nếu không có nút nào vừa được bấm.
enum class ButtonEvent
{
  None,
  Correct,
  Wrong
};

// Cấu hình pinMode cho cả 2 nút. Gọi 1 lần trong setup().
void inputSetup();

// Gọi mỗi vòng loop(). Trả về đúng 1 sự kiện cho lần bấm mới nhất (đã tự debounce +
// edge-detect bên trong), hoặc None nếu không có gì mới.
ButtonEvent inputPoll();
