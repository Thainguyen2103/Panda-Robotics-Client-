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

// Client ID KHÔNG được để cố định. Theo chuẩn MQTT, 2 thiết bị nối vào cùng 1 broker với
// cùng Client ID thì broker sẽ ĐÁ thiết bị nối trước ra. Nếu mình và bạn Thắng (hoặc 2 tab
// Wokwi của chính mình) cùng chạy firmware này, 2 bên sẽ liên tục đá nhau -> mất kết nối
// -> reconnect liên tục. Thêm hậu tố ngẫu nhiên để mỗi lần chạy là một cái tên khác nhau.
static String mqttClientId;

static WiFiClient espClient;
static PubSubClient mqtt(espClient);

// Địa chỉ IP của broker sau khi tra DNS THÀNH CÔNG đúng 1 lần. Xem giải thích dài ở
// resolveBrokerOnce() bên dưới — đây là phần sửa lỗi crash IllegalInstruction.
static IPAddress brokerIp;
static bool brokerResolved = false;

// KHÔNG dùng while(...) { delay(...) } để retry vô hạn như bản Tuần 2 — cách đó chặn đứng
// toàn bộ loop() (OLED không vẽ được, nút bấm không đọc được) mỗi khi mất mạng giữa chừng.
// Thay vào đó chỉ lưu lại "lần thử gần nhất" và mỗi networkLoop() chỉ thử lại nếu đã đủ
// RETRY_INTERVAL_MS kể từ lần trước, còn lại thì return ngay cho phần code khác chạy tiếp.
static const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
static const unsigned long MQTT_RETRY_INTERVAL_MS = 5000;
static unsigned long lastWifiAttemptMs = 0;
static unsigned long lastMqttAttemptMs = 0;

// Tra tên miền "broker.hivemq.com" ra địa chỉ IP, ĐÚNG MỘT LẦN DUY NHẤT rồi nhớ luôn.
//
// VÌ SAO PHẢI LÀM VẬY — đây là nguyên nhân gốc của lỗi crash "IllegalInstruction":
// Khi PubSubClient nhận tên miền, mỗi lần connect() nó lại gọi WiFi.hostByName() để tra
// DNS. Hàm hostByName() của Arduino-ESP32 đưa cho lwIP một CON TRỎ TỚI BIẾN CỤC BỘ (nằm
// trên stack) để lwIP ghi kết quả vào khi có phản hồi, rồi chờ tối đa 15 giây. Nếu quá
// 15 giây chưa có phản hồi, hàm BỎ CUỘC và trả về — nhưng lwIP thì VẪN GIỮ con trỏ đó.
// Khi phản hồi DNS về muộn, lwIP ghi 4 byte vào một chỗ trên stack mà **hàm cũ đã kết
// thúc từ lâu** — tức là ghi đè lên dữ liệu của hàm khác đang chạy ở đúng chỗ đó. Nếu
// chỗ bị ghi đè là địa chỉ trở về của một hàm, CPU sẽ nhảy tới một địa chỉ rác (trong
// log là PC = 0xb33fffff) và chết ngay với lỗi IllegalInstruction.
//
// Cách chặn đứng: tra DNS 1 lần, thành công thì gọi mqtt.setServer(IP, port). Từ đó trở
// đi PubSubClient nối thẳng bằng IP và KHÔNG BAO GIỜ đi vào đường DNS nữa.
static bool resolveBrokerOnce()
{
  if (brokerResolved)
  {
    return true;
  }

  Serial.print("[net] Dang tra DNS cho ");
  Serial.print(MQTT_BROKER);
  Serial.print("...");

  if (WiFi.hostByName(MQTT_BROKER, brokerIp) == 1 && brokerIp != IPAddress((uint32_t)0))
  {
    brokerResolved = true;
    mqtt.setServer(brokerIp, MQTT_PORT); // đổi từ "nối bằng tên miền" sang "nối bằng IP"
    Serial.print(" OK -> ");
    Serial.println(brokerIp);
    return true;
  }

  Serial.println(" that bai, se thu lai sau");
  return false;
}

static void tryConnectMqttOnce()
{
  if (!resolveBrokerOnce())
  {
    return;
  }

  Serial.print("[net] Dang ket noi MQTT (");
  Serial.print(mqttClientId);
  Serial.print(")...");
  if (mqtt.connect(mqttClientId.c_str()))
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
  // esp_random() là bộ sinh số ngẫu nhiên PHẦN CỨNG của ESP32 — khác random() của Arduino
  // (vốn cho ra cùng một dãy số sau mỗi lần khởi động nếu không gieo hạt), nên mỗi lần bật
  // máy sẽ ra một Client ID thật sự khác nhau.
  mqttClientId = "panda-demo-khoa-" + String(esp_random() & 0xFFFFFF, HEX);

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);

  // PubSubClient mặc định chờ tối đa 15 GIÂY cho mỗi thao tác mạng (kết nối TCP, bắt tay
  // MQTT) trước khi coi là thất bại — và trong lúc chờ đó, mqtt.connect() KHÔNG TRẢ VỀ,
  // nghĩa là cả loop() (kể cả inputPoll() đọc nút) bị đứng hình theo. 15s là con số hợp lý
  // cho thiết bị IoT bình thường, nhưng quá dài cho 1 nút bấm cần phản hồi ngay. Giảm
  // xuống 3s để nếu broker.hivemq.com phản hồi chậm (broker công cộng, qua cổng Internet
  // ảo của Wokwi), thời gian "đứng hình" tối đa chỉ còn 3s thay vì 15s.
  mqtt.setSocketTimeout(3);

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
