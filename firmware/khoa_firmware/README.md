# khoa_firmware — Demo firmware ESP32 (mô phỏng Wokwi)

Phần firmware nhúng do Khoa (vai trò "Firmware nhúng") phụ trách, phát triển độc lập bằng
PlatformIO + Wokwi (chưa cần phần cứng thật). Đây là bản demo minh hoạ luồng
**ESP32 → OLED → WiFi/MQTT → Web dashboard**, sẽ tiếp tục mở rộng qua các tuần và
tích hợp dần với phần AI/backend ở `server/` cùng repo.

## Chạy thử (không cần phần cứng)

1. Cài VS Code + extension **PlatformIO IDE** + **Wokwi for VS Code**.
2. Mở thư mục này (`firmware/khoa_firmware/`) trong VS Code.
3. Build: `pio run`.
4. `F1` → `Wokwi: Start Simulator` để mô phỏng ESP32 + OLED SSD1306 + 2 nút bấm.
5. Mở `web-dashboard/index.html` bằng trình duyệt để xem dashboard nhận dữ liệu realtime qua MQTT.

## Cấu trúc

```
src/
├── main.cpp        # setup()/loop(), điều phối các module bên dưới
├── pins.h          # định nghĩa chân GPIO tập trung
├── display.h/.cpp  # OLED SSD1306 — 14 biểu cảm (đồng bộ với firmware/panda_firmware.ino
│                     ở thư mục cha) + hiển thị từ vựng
├── input.h/.cpp    # đọc 2 nút bấm (debounce + edge detect)
├── network.h/.cpp  # WiFi + MQTT (connect/reconnect/publish, non-blocking)
└── audio_i2s.h/.cpp# học I2S (mic INMP441 — Wokwi chưa mô phỏng I2S thật)
web-dashboard/
└── index.html      # dashboard tĩnh, subscribe MQTT-over-WebSocket bằng mqtt.js
```

## Lưu ý tích hợp

- Biểu cảm OLED (`neutral/happy/sad/angry/surprised/sleepy/wink/love/cool/cute/dizzy/
  questioning/thinking/speaking`) được port từ `firmware/panda_firmware/panda_firmware.ino`
  (cùng toạ độ mắt `L=32, R=76, Y=17, W=20, H=30`) để tương thích khi ghép chung.
- Demo hiện đang publish/subscribe trên broker công cộng `broker.hivemq.com` với topic
  riêng cho mục đích demo (khác namespace `panda/cmd/*` / `panda/status` mà `server/brain.py`
  dùng) — sẽ đổi sang namespace + broker thật khi tích hợp end-to-end.
- 2 nút bấm hiện đang giả lập kết quả chấm đúng/sai, thay cho STT/fuzzy-matching thật —
  sẽ được thay thế khi ghép với pipeline AI thật ở `server/`.
