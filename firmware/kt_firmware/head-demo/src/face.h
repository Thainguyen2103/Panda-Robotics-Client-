#pragma once
#include <Arduino.h>

// Mặt robot trên màn TFT ILI9341 (chân SPI theo "Sơ đồ 3/3": CS=1 DC=2 RST=14 MOSI=38 SCK=39).
bool faceBegin();                             // false = thiếu RAM cho canvas vẽ mắt
void faceSetExpression(const char *expression); // 1 trong 15 tên chung (xem ai.md)
void faceSetCaption(const char *text);        // chữ ASCII dưới mặt, vd "VUI 87%"
void faceTick();                              // gọi liên tục trong loop(), tự giữ ~33 khung/giây
