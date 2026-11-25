// body-test — thử phần THÂN robot: 2 bánh + cảm biến vật cản.
//
// Nhận lệnh từ laptop theo 2 đường (đường nào cũng được, cùng 1 kiểu lệnh):
//   - dây USB (Serial 115200)             : tools/lai_xe.py hoặc head-demo khi thân cắm laptop
//   - WiFi (UDP, cổng 4211)               : head-demo khi thân cắm SẠC DỰ PHÒNG (chỉ có 1 dây USB)
// Lệnh laptop → board, gửi liên tục ~20 lần/giây:
//     "m <trai> <phai>\n"      tốc độ mỗi bánh -255..255 (0 = đứng yên, số ÂM = quay LÙI)
//                              vd "m 150 150" tới, "m -150 -150" lùi, "m -150 150" xoay trái tại chỗ
// Board → laptop ~10 lần/giây (qua Serial, và qua WiFi tới cổng UDP 4210 của laptop):
//     "S <cm> <trai> <phai> <chan>\n"   khoảng cách, tốc độ thật đang chạy, 1 = đang bị chặn
//
// Luật an toàn (chạy NGAY TRÊN BOARD, không phụ thuộc laptop):
//   1. Vật cản gần hơn STOP_CM → cấm ĐI TỚI (cả 2 bánh cùng quay tới), nhưng vẫn cho LÙI và
//      RẼ/XOAY để xe thoát ra. Cấm luôn cả những hướng đó thì xe bị "kẹt cứng" trước vật cản.
//      (Cảm biến chỉ nhìn phía TRƯỚC: lùi thì không có gì bảo vệ, người lái tự nhìn.)
//      Vật đi xa hơn CLEAR_CM thì mới cho đi thẳng lại (khoảng chênh để bánh không giật bật/tắt
//      liên tục khi vật đứng đúng ngay ngưỡng).
//   2. Quá CMD_TIMEOUT_MS không nhận lệnh (rút cáp, tắt chương trình, mất WiFi) → dừng.
//      Thiếu luật này, lỡ mất kết nối lúc đang chạy là bánh quay mãi.
#include <Arduino.h>
#include <ArduinoOTA.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// Tên + mật khẩu WiFi nằm trong file riêng (không đưa lên git). Chưa có file thì tạo từ
// wifi_secrets.example.h. Laptop và board phải vào CÙNG 1 mạng WiFi.
#if __has_include("wifi_secrets.h")
#include "wifi_secrets.h"
#else
#define WIFI_SSID ""
#define WIFI_PASS ""
#endif

// ---- Chân, đúng sơ đồ breadboard trong moon-lap-rap.html ----
const int PWMA = 25, AIN1 = 26, AIN2 = 27; // bánh TRÁI (AO1/AO2)
const int PWMB = 32, BIN1 = 33, BIN2 = 14; // bánh PHẢI (BO1/BO2)
const int TRIG = 13, ECHO = 18;            // HC-SR04 (ECHO qua chia áp 1k/2,2k)

// Bánh quay lùi khi bạn giữ phím? Đổi true ↔ false cho bánh đó (khỏi đảo dây).
const bool INVERT_LEFT = false;
const bool INVERT_RIGHT = false;

// Trước là 20/25cm: xe dừng khi vật còn khá xa, lái trong phòng chật là dừng suốt.
// 12cm vẫn đủ phanh: từ lúc vật vào ngưỡng tới lúc chặn mất ~250ms (3 lần đo × 60ms + lọc),
// xe tốc độ 150 đi thêm khoảng 5-8cm → dừng cách vật vài cm. Xe chạy nhanh hơn (+ nhiều lần)
// mà vẫn đâm vào vật thì tăng STOP_CM lên 15.
const float STOP_CM = 12.0;  // gần hơn → cấm đi thẳng
const float CLEAR_CM = 16.0; // xa hơn → cho đi thẳng lại
// 500ms: WiFi thỉnh thoảng trễ 100-200ms, đặt quá ngắn bánh sẽ khựng vô cớ.
const uint32_t CMD_TIMEOUT_MS = 500;

const uint16_t CMD_PORT = 4211;    // board nghe lệnh ở cổng này
const uint16_t STATUS_PORT = 4210; // laptop nghe trạng thái ở cổng này

// PWM của ESP32 (LEDC): mỗi bánh 1 kênh, 20kHz (trên ngưỡng tai nghe → motor không kêu rít),
// độ phân giải 8 bit → tốc độ 0..255.
const int CH_LEFT = 0, CH_RIGHT = 1;

int wantLeft = 0, wantRight = 0; // laptop muốn
int runLeft = 0, runRight = 0;   // đang chạy thật (sau luật an toàn)
bool blocked = false;
bool otaBusy = false;            // đang nạp code qua WiFi → khoá bánh, khỏi chạy lung tung
float distCm = -1;               // -1 = không thấy vật nào trong tầm (~4m)
uint32_t lastCmdMs = 0;

WiFiUDP udp;
IPAddress laptopIp;         // laptop vừa gửi lệnh qua WiFi (để gửi trạng thái thẳng về)
uint32_t lastUdpCmdMs = 0;

// Chạy 1 bánh: speed -255..255. TB6612 chọn chiều bằng 2 chân IN:
//   IN1=1,IN2=0 → tới;  IN1=0,IN2=1 → lùi;  cả 2 = 1 → PHANH (nối tắt 2 đầu motor).
// Độ lớn của speed (bỏ dấu) là độ rộng xung PWM = mạnh/yếu.
void setWheel(int ch, int in1, int in2, int speed, bool invert)
{
  if (speed == 0)
  {
    // PHANH thay vì thả trôi (cả 2 = 0). Motor đang quay mà bị nối tắt 2 đầu thì chính nó
    // sinh dòng hãm lại → bánh đứng gần như ngay, như phanh xe. Thả trôi thì xe còn lăn thêm
    // vài cm — dở khi dừng vì vật cản. Phanh kiểu này không tốn điện pin.
    digitalWrite(in1, HIGH);
    digitalWrite(in2, HIGH);
    ledcWrite(ch, 0);
    return;
  }
  bool forward = (speed > 0) != invert; // bánh lắp ngược (invert) thì đảo chiều
  digitalWrite(in1, forward ? HIGH : LOW);
  digitalWrite(in2, forward ? LOW : HIGH);
  ledcWrite(ch, min(abs(speed), 255));
}

// Đo khoảng cách: phát xung 10µs ở TRIG, đo độ dài xung ECHO (thời gian sóng âm đi + về).
// Âm thanh ~0,0343 cm/µs, đi 2 lần quãng đường → chia 2.
float readDistanceCm()
{
  digitalWrite(TRIG, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  // Chờ tối đa 25ms (~4m). Hết giờ = không có vật trong tầm → trả -1.
  unsigned long us = pulseIn(ECHO, HIGH, 25000);
  if (us == 0)
  {
    return -1;
  }
  return us * 0.0343f / 2.0f;
}

// 1 dòng lệnh, đến từ dây USB hay WiFi đều xử lý giống nhau.
bool handleLine(const char *line)
{
  int l, r;
  if (sscanf(line, "m %d %d", &l, &r) != 2)
  {
    return false;
  }
  wantLeft = constrain(l, -255, 255);
  wantRight = constrain(r, -255, 255);
  lastCmdMs = millis();
  return true;
}

void readSerial()
{
  static char line[32];
  static size_t len = 0;
  while (Serial.available())
  {
    char c = (char)Serial.read();
    if (c == '\r')
    {
      continue;
    }
    if (c != '\n')
    {
      if (len < sizeof(line) - 1)
      {
        line[len++] = c;
      }
      continue;
    }
    line[len] = '\0';
    len = 0;
    handleLine(line);
  }
}

// UDP = gói tin rời qua WiFi: mỗi gói là 1 lệnh trọn vẹn, không cần ghép từng ký tự như Serial.
void readUdp()
{
  int size;
  while ((size = udp.parsePacket()) > 0)
  {
    char line[32];
    int n = udp.read(line, sizeof(line) - 1);
    line[max(n, 0)] = '\0';
    if (handleLine(line))
    {
      laptopIp = udp.remoteIP();
      lastUdpCmdMs = millis();
    }
  }
}

void sendStatus()
{
  char msg[48];
  snprintf(msg, sizeof(msg), "S %.1f %d %d %d\n", distCm, runLeft, runRight, blocked ? 1 : 0);
  Serial.print(msg);
  if (WiFi.status() != WL_CONNECTED)
  {
    return;
  }
  // Đã có laptop điều khiển qua WiFi → gửi thẳng cho nó. Chưa có → phát cho cả mạng
  // (broadcast) 1 lần/giây để laptop tự tìm ra board, khỏi phải gõ địa chỉ IP.
  static uint32_t lastBroadcast = 0;
  if (millis() - lastUdpCmdMs < 2000)
  {
    udp.beginPacket(laptopIp, STATUS_PORT);
  }
  else if (millis() - lastBroadcast >= 1000)
  {
    lastBroadcast = millis();
    udp.beginPacket(WiFi.broadcastIP(), STATUS_PORT);
  }
  else
  {
    return;
  }
  udp.write((const uint8_t *)msg, strlen(msg));
  udp.endPacket();
}

// Giữ WiFi luôn nối, gọi mỗi vòng loop().
// Vì sao cần: thư viện WiFi của ESP32 chỉ tự thử lại vài lần. Bật board trước khi hotspot laptop
// kịp phát sóng (hoặc tắt/bật lại hotspot giữa chừng) → nó báo "không thấy mạng" (NO_AP_FOUND)
// rồi BỎ CUỘC LUÔN; trước đây phải nạp lại code (= reset board) mới nối được. Ở đây cứ chưa nối
// là 8 giây thử lại 1 lần, nên thứ tự bật hotspot / cắm nguồn thế nào cũng tự vào mạng.
// 8 giây chứ không ngắn hơn: 1 lần nối (dò mạng + bắt tay + xin IP) mất 2-5 giây, gọi begin()
// lại giữa chừng là cắt ngang chính lần nối đang chạy.
void keepWifi()
{
  if (strlen(WIFI_SSID) == 0)
  {
    return;
  }
  static bool wasConnected = false;
  static uint32_t lastTry = 0;
  bool connected = WiFi.status() == WL_CONNECTED;

  if (connected && !wasConnected)
  {
    // Mở lại cổng UDP mỗi lần (vừa) có mạng, cho chắc nó gắn với kết nối mới.
    udp.begin(CMD_PORT);
    // Nạp code qua WiFi (OTA): từ giờ không cần dây nữa — xem env "ota" trong platformio.ini.
    // begin() gọi lại lần 2 khi WiFi nối lại cũng không sao (thư viện tự bỏ qua).
    ArduinoOTA.setHostname("panda-body");
    ArduinoOTA.onStart([]()
                       { otaBusy = true;
                         setWheel(CH_LEFT, AIN1, AIN2, 0, INVERT_LEFT);
                         setWheel(CH_RIGHT, BIN1, BIN2, 0, INVERT_RIGHT); });
    ArduinoOTA.onError([](ota_error_t)
                       { otaBusy = false; });
    ArduinoOTA.begin();
    Serial.printf("# WiFi OK: %s, IP %s\n", WIFI_SSID, WiFi.localIP().toString().c_str());
  }
  if (connected)
  {
    ArduinoOTA.handle(); // xem có ai đang gửi code mới qua WiFi không
  }
  else if (!connected && wasConnected)
  {
    Serial.println("# WiFi mat ket noi, dang thu noi lai...");
    lastTry = millis(); // thư viện tự thử lại ngay 1 lần, cho nó 8 giây trước khi mình can thiệp
  }
  wasConnected = connected;

  if (!connected && millis() - lastTry >= 8000)
  {
    lastTry = millis();
    Serial.printf("# WiFi: chua thay \"%s\" (hotspot da bat chua? phai la 2,4GHz), thu lai...\n", WIFI_SSID);
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
}

void setup()
{
  Serial.begin(115200);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  ledcSetup(CH_LEFT, 20000, 8);
  ledcSetup(CH_RIGHT, 20000, 8);
  ledcAttachPin(PWMA, CH_LEFT);
  ledcAttachPin(PWMB, CH_RIGHT);
  setWheel(CH_LEFT, AIN1, AIN2, 0, INVERT_LEFT);
  setWheel(CH_RIGHT, BIN1, BIN2, 0, INVERT_RIGHT);

  if (strlen(WIFI_SSID) > 0)
  {
    // Không chờ WiFi ở đây: vẫn lái được qua dây USB ngay, WiFi tự nối dần ở chế độ nền
    // (và tự thử lại mãi nếu chưa thấy hotspot — xem keepWifi()).
    WiFi.persistent(false); // không ghi tên/mật khẩu WiFi vào flash mỗi lần begin() → flash bền hơn
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false); // tắt tiết kiệm điện WiFi → lệnh tới nhanh, bánh không khựng
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
  Serial.println("# body-test san sang: day USB (lai_xe.py) hoac WiFi (head-demo)");
}

void loop()
{
  readSerial();
  readUdp();
  keepWifi();

  // Đo 1 lần mỗi 60ms (HC-SR04 cần nghỉ giữa 2 lần đo để tiếng vang cũ tắt hẳn).
  static uint32_t lastMeasure = 0;
  static int nearCount = 0;
  static float last3[3] = {-1, -1, -1}; // 3 lần đo gần nhất, để lấy trung vị
  if (millis() - lastMeasure >= 60)
  {
    lastMeasure = millis();
    float raw = readDistanceCm();
    // Motor vừa quay là kéo dòng mạnh → nhiễu lên đường 5V và dây ECHO → HC-SR04 trả về xung
    // rất ngắn = khoảng cách vài cm dù phía trước trống (đo thật 19/11: đang thấy 304cm, bánh
    // vừa quay là báo VAT CAN). HC-SR04 không đo được dưới 2cm, nên số đó chắc chắn là nhiễu → bỏ.
    if (raw >= 0 && raw < 2.0f)
    {
      raw = -1;
    }
    last3[0] = last3[1];
    last3[1] = last3[2];
    last3[2] = raw;
    // Trung vị 3 lần đo: 1 lần nhiễu lẻ (quá gần hoặc quá xa) bị 2 lần còn lại "át" đi.
    float a = last3[0], b = last3[1], c = last3[2];
    distCm = max(min(a, b), min(max(a, b), c));
    bool near = distCm > 0 && distCm < STOP_CM;
    bool clear = distCm < 0 || distCm > CLEAR_CM;
    // Cần 3 trung vị GẦN liên tiếp (~180ms) mới chặn. Xe chạy chậm nên vẫn kịp dừng trước vật.
    nearCount = near ? nearCount + 1 : 0;
    if (nearCount >= 3)
    {
      blocked = true;
    }
    else if (clear)
    {
      blocked = false;
    }
  }

  bool lostLaptop = millis() - lastCmdMs > CMD_TIMEOUT_MS;
  // Cả 2 bánh cùng quay TỚI = đang lao về phía trước → vật cản chặn. Lùi, xoay tại chỗ
  // (2 bánh ngược chiều) hay rẽ 1 bánh → vẫn cho, để xe thoát khỏi vật cản (luật 1 đầu file).
  bool goingStraight = wantLeft > 0 && wantRight > 0;
  bool stopNow = otaBusy || lostLaptop || (blocked && goingStraight);
  runLeft = stopNow ? 0 : wantLeft;
  runRight = stopNow ? 0 : wantRight;
  setWheel(CH_LEFT, AIN1, AIN2, runLeft, INVERT_LEFT);
  setWheel(CH_RIGHT, BIN1, BIN2, runRight, INVERT_RIGHT);

  static uint32_t lastReport = 0;
  if (millis() - lastReport >= 100)
  {
    lastReport = millis();
    sendStatus();
  }
}
