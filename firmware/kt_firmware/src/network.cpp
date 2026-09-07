#include "network.h"
#include <WiFi.h>
#include <PubSubClient.h>

// Wokwi cung cấp sẵn 1 mạng WiFi ảo có Internet thật tên "Wokwi-GUEST", không mật khẩu.
static const char *WIFI_SSID = "Wokwi-GUEST";
static const char *WIFI_PASSWORD = "";

// Broker MQTT công cộng dùng để demo, không cần tự host. Đã đổi từ test.mosquitto.org
// sang broker.hivemq.com ở Tuần 2 sau khi gặp lỗi rc=-2 (TCP connect thất bại, không phải
// sai thông tin đăng nhập) — nghi do broker cũ bị quá tải khi đi qua gateway public của Wokwi.
static const char *MQTT_BROKER = "broker.hivemq.com";
static const int MQTT_PORT = 1883;
static const char *MQTT_CLIENT_ID = "panda-demo-khoa";

static WiFiClient espClient;
static PubSubClient mqtt(espClient);

// KHÔNG dùng while(...) { delay(...) } để retry vô hạn như bản Tuần 2 — cách đó chặn đứng
// toàn bộ loop() (OLED không vẽ được, nút bấm không đọc được) mỗi khi mất mạng giữa chừng.
// Thay vào đó chỉ lưu lại "lần thử gần nhất" và mỗi networkLoop() chỉ thử lại nếu đã đủ
// RETRY_INTERVAL_MS kể từ lần trước, còn lại thì return ngay cho phần code khác chạy tiếp.
static const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
static const unsigned long MQTT_RETRY_INTERVAL_MS = 5000;
static unsigned long lastWifiAttemptMs = 0;
static unsigned long lastMqttAttemptMs = 0;

static void tryConnectMqttOnce()
{
  Serial.print("[net] Dang ket noi MQTT...");
  if (mqtt.connect(MQTT_CLIENT_ID))
  {
    Serial.println(" OK");
  }
  else
  {
    Serial.print(" that bai, rc=");
    Serial.println(mqtt.state());
  }
}

void networkSetup()
{
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);

  // Lần đầu tiên vẫn chờ WiFi (blocking): trước khi có mạng thì chưa có việc gì khác để
  // làm nên chặn ở đây không sao. Có giới hạn thời gian (15s) để log rõ ràng thay vì
  // treo vô thời hạn nếu WiFi ảo Wokwi gặp sự cố — sau 15s vẫn để networkLoop() tự thử lại.
  Serial.print("[net] Dang ket noi WiFi (begin)");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000)
  {
    delay(300);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " OK" : " timeout, se thu lai trong loop()");
  lastWifiAttemptMs = millis();

  if (WiFi.status() == WL_CONNECTED)
  {
    tryConnectMqttOnce();
    lastMqttAttemptMs = millis();
  }
}

void networkLoop()
{
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED)
  {
    if (now - lastWifiAttemptMs >= WIFI_RETRY_INTERVAL_MS)
    {
      // reconnect() nhẹ hơn begin(): dùng lại SSID/password đã cấu hình ở networkSetup(),
      // không cần truyền lại thông tin đăng nhập mỗi lần rớt mạng giữa chừng.
      Serial.println("[net] WiFi mat ket noi, dang reconnect()...");
      WiFi.reconnect();
      lastWifiAttemptMs = now;
    }
    return; // chưa có WiFi thì chắc chắn chưa thử MQTT được, khỏi kiểm tra tiếp bên dưới
  }

  if (!mqtt.connected())
  {
    if (now - lastMqttAttemptMs >= MQTT_RETRY_INTERVAL_MS)
    {
      tryConnectMqttOnce();
      lastMqttAttemptMs = now;
    }
    return;
  }

  // Hàm xử lý nền của PubSubClient (giữ kết nối, nhận message subscribe nếu có) — PHẢI
  // gọi liên tục mỗi vòng loop(), kể cả khi không publish gì. Quên gọi thì kết nối MQTT
  // âm thầm bị treo dù code không báo lỗi ngay lúc đó.
  mqtt.loop();
}

bool networkIsReady()
{
  return WiFi.status() == WL_CONNECTED && mqtt.connected();
}

void networkPublish(const char *topic, const char *payload)
{
  if (!networkIsReady())
  {
    Serial.println("[net] Bo qua publish: WiFi/MQTT dang mat ket noi");
    return;
  }
  mqtt.publish(topic, payload);
}
