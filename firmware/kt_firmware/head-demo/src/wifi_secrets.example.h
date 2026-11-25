// Chép file này thành "wifi_secrets.h" (cùng thư mục src/) rồi điền WiFi.
// wifi_secrets.h KHÔNG đưa lên git (.gitignore). Laptop phải vào CÙNG mạng WiFi này
// (thường là Mobile hotspot của chính laptop — dùng chung với board thân body-test).
// Lưu ý: ESP32 chỉ bắt được WiFi 2,4GHz (không bắt được mạng 5GHz).
// Để trống WIFI_SSID = chỉ chạy qua dây USB như trước.
#define WIFI_SSID "ten-wifi"
#define WIFI_PASS "mat-khau-wifi"
