#pragma once
#include <Arduino.h>

// Kết nối WiFi lần đầu (blocking, có timeout) + cấu hình MQTT broker. Gọi 1 lần trong setup().
void networkSetup();

// Gọi mỗi vòng loop(). KHÔNG bao giờ chặn lâu: nếu đang mất WiFi/MQTT thì chỉ thử kết nối
// lại tối đa 1 lần mỗi vài giây rồi return ngay, để nút bấm/OLED vẫn phản hồi được.
void networkLoop();

// true khi cả WiFi lẫn MQTT đều đang kết nối — dùng để quyết định có publish được không.
bool networkIsReady();

// Publish 1 message; tự bỏ qua (không làm gì) nếu networkIsReady() == false.
void networkPublish(const char *topic, const char *payload);
