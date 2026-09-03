/*
 * PANDA FIRMWARE (BODY+HEAD) — ESP32
 * ====================================
 * Chạy được 2 chế độ:
 *   [SIM]  Wokwi / Serial Monitor — gõ lệnh tay, KHÔNG cần MQTT:
 *            face happy
 *            move forward
 *            arm wave
 *            buzz on
 *            text XIN CHAO
 *   [THẬT] Bật USE_MQTT → nối WiFi + broker, subscribe panda/cmd/# y hệt virtual_robot.
 *
 * ── BẢNG MẠCH (giống sơ đồ sẽ lắp thật — KHÔNG có tay servo) ───────────
 *   OLED SSD1306 : SDA→21  SCL→22  VCC→3V3  GND→GND
 *   Buzzer       : +→18   -→GND   (SIM: thay bằng LED)
 *   Motor driver : PWMA→25 AIN1→26 AIN2→27 | PWMB→32 BIN1→33 BIN2→14
 *                  (SIM: nối LED vào 25 & 32 làm "đèn motor")
 *   HC-SR04      : TRIG→4 ECHO→5 VCC→5V GND→GND
 *                  (SIM: potentiometer → GPIO34, xoay núm = đổi khoảng cách cm)
 *   Nút bấm      : 1 chân→19, chân kia→GND
 *   (Nếu sau này lắp tay: bật #define HAS_ARM và nối servo SIG→13)
 *
 * ── WOKWI: tạo project ESP32, Libraries thêm:
 *    "Adafruit SSD1306", "Adafruit GFX Library"  (chưa cần ESP32Servo)
 *    Kéo parts: esp32, ssd1306, leds, button, potentiometer
 *    Nối dây đúng bảng trên → paste code → bấm Play → gõ lệnh trong Serial.
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// #define HAS_ARM            // ← bật nếu sau này lắp tay servo
#ifdef HAS_ARM
#include <ESP32Servo.h>
#endif

// #define USE_MQTT            // ← BẬT khi nạp vào ESP32 thật
#ifdef USE_MQTT
#include <WiFi.h>
#include <PubSubClient.h>
const char* WIFI_SSID = "TEN_WIFI";
const char* WIFI_PASS = "MAT_KHAU";
const char* MQTT_HOST = "192.168.1.10";   // máy chạy brain
#endif

// ── Pins ──
#define PIN_SDA 21
#define PIN_SCL 22
#define PIN_SERVO 13
#define PIN_BUZZ 18
#define PIN_PWMA 25
#define PIN_AIN1 26
#define PIN_AIN2 27
#define PIN_PWMB 32
#define PIN_BIN1 33
#define PIN_BIN2 14
#define PIN_TRIG 4
#define PIN_ECHO 5
#define PIN_BTN 19
#define PIN_POT 34   // SIM: potentiometer giả khoảng cách

Adafruit_SSD1306 d(128, 64, &Wire, -1);
#ifdef HAS_ARM
Servo arm;
#endif

String faceMode = "neutral";
unsigned long lastStatus = 0;
unsigned long lastAnim = 0;
int animFrame = 0;
unsigned long lastCmd = 0, lastCycle = 0;   // auto-cycle demo face
int cycleIdx = -1;
const char* FACE_LIST[] = { "neutral", "happy", "sad", "angry", "surprised", "love", "wink",
                            "sleepy", "cool", "cute", "dizzy", "questioning", "thinking", "speaking" };

// ── Vẽ mặt OLED giống dashboard (trắng/đen) ──
void eye(int x, int y, int w, int h) { d.fillRoundRect(x, y, w, h, 9, WHITE); }
void mouth(int cx, int cy, bool smile) {   // cung miệng 3 đoạn
  if (smile) { d.drawLine(cx - 8, cy, cx - 3, cy + 4, WHITE); d.drawLine(cx - 3, cy + 4, cx + 3, cy + 4, WHITE); d.drawLine(cx + 3, cy + 4, cx + 8, cy, WHITE); }
  else       { d.drawLine(cx - 8, cy + 4, cx - 3, cy, WHITE); d.drawLine(cx - 3, cy, cx + 3, cy, WHITE); d.drawLine(cx + 3, cy, cx + 8, cy + 4, WHITE); } }
void heart(int cx, int cy) {
  d.fillCircle(cx - 5, cy - 4, 6, WHITE); d.fillCircle(cx + 5, cy - 4, 6, WHITE);
  d.fillTriangle(cx - 11, cy - 2, cx + 11, cy - 2, cx, cy + 11, WHITE); }
void cross(int cx, int cy) {
  d.drawLine(cx - 7, cy - 7, cx + 7, cy + 7, WHITE); d.drawLine(cx - 7, cy + 7, cx + 7, cy - 7, WHITE); }

void drawFace() {
  d.clearDisplay();
  const int L = 30, R = 76, Y = 14, W = 22, H = 32;
  if (faceMode == "neutral") { eye(L, Y, W, H); eye(R, Y, W, H); }
  else if (faceMode == "happy") { eye(L, Y + 9, W, 20); eye(R, Y + 9, W, 20); mouth(64, 48, true); }
  else if (faceMode == "sad") { eye(L, Y + 8, W, 22); eye(R, Y + 8, W, 22);
    d.drawLine(L, Y + 4, L + W, Y - 2, WHITE); d.drawLine(R + W, Y + 4, R, Y - 2, WHITE); mouth(64, 50, false); }
  else if (faceMode == "angry") { eye(L, Y + 4, W, 26); eye(R, Y + 4, W, 26);
    d.drawLine(L, Y - 2, L + W, Y + 4, WHITE); d.drawLine(R + W, Y - 2, R, Y + 4, WHITE); mouth(64, 50, false); }
  else if (faceMode == "surprised") { d.fillCircle(L + 11, 28, 12, WHITE); d.fillCircle(R + 11, 28, 12, WHITE);
    d.drawCircle(64, 51, 5, WHITE); }
  else if (faceMode == "sleepy") { d.fillRoundRect(L, Y + 22, W, 5, 2, WHITE); d.fillRoundRect(R, Y + 22, W, 5, 2, WHITE);
    d.setTextSize(1); d.setCursor(104, 8); d.print("zZ"); }
  else if (faceMode == "wink") { eye(L, Y, W, H); d.fillRoundRect(R, Y + 15, W, 5, 2, WHITE); mouth(64, 48, true); }
  else if (faceMode == "love") { heart(L + 11, 26); heart(R + 11, 26); mouth(64, 48, true); }
  else if (faceMode == "cool") { d.fillRect(L - 3, Y + 8, W + 6, 12, WHITE); d.fillRect(R - 3, Y + 8, W + 6, 12, WHITE);
    d.drawLine(L + W, Y + 12, R, Y + 12, WHITE); mouth(64, 48, true); }
  else if (faceMode == "cute") { eye(L - 2, Y - 2, W + 4, H + 4); eye(R - 2, Y - 2, W + 4, H + 4);
    d.fillCircle(64, 51, 3, WHITE); }
  else if (faceMode == "dizzy") { cross(L + 11, 28); cross(R + 11, 28); mouth(64, 50, false); }
  else if (faceMode == "questioning") { d.setTextSize(4); d.setCursor(52, 16); d.print("?"); }
  else if (faceMode == "thinking") { for (int i = 0; i < 3; i++)
      if ((animFrame / 3) % 3 == i) d.fillCircle(44 + i * 20, 32, 6, WHITE); else d.drawCircle(44 + i * 20, 32, 6, WHITE); }
  else if (faceMode == "speaking") { for (int i = 0; i < 5; i++) {
      int h = 8 + ((animFrame * (i + 3)) % 28); d.fillRect(34 + i * 14, 56 - h, 8, h, WHITE); } }
  else { eye(L, Y, W, H); eye(R, Y, W, H); }
  d.display();
}

// ── Điều khiển ──
void setMotor(bool fwd, bool bwd, bool left, bool right) {
  int a1 = fwd ? HIGH : LOW, a2 = bwd ? HIGH : LOW;
  int b1 = fwd ? HIGH : LOW, b2 = bwd ? HIGH : LOW;
  if (left)  { a1 = LOW; a2 = HIGH; }   // rẽ: bánh trái quay ngược
  if (right) { b1 = LOW; b2 = HIGH; }
  digitalWrite(PIN_AIN1, a1); digitalWrite(PIN_AIN2, a2);
  digitalWrite(PIN_BIN1, b1); digitalWrite(PIN_BIN2, b2);
  analogWrite(PIN_PWMA, (fwd || bwd || left || right) ? 200 : 0);
  analogWrite(PIN_PWMB, (fwd || bwd || left || right) ? 200 : 0);
}

void handleMove(String m) {
  if (m == "forward") setMotor(1, 0, 0, 0);
  else if (m == "back") setMotor(0, 1, 0, 0);
  else if (m == "left") setMotor(1, 0, 1, 0);
  else if (m == "right") setMotor(1, 0, 0, 1);
  else setMotor(0, 0, 0, 0);
  Serial.println("[PANDA] move " + m);
}

void handleArm(String a) {
#ifdef HAS_ARM
  if (a == "wave") { for (int i = 0; i < 3; i++) { arm.write(20); delay(250); arm.write(90); delay(250); } }
  else if (a == "up") arm.write(30);
  else if (a == "down") arm.write(120);
  else arm.write(90);
#endif
  Serial.println("[PANDA] arm " + a);   // robot không tay: chỉ log, không lỗi
}

void handleCmd(String topic, String payload) {
  if (topic.endsWith("/move")) handleMove(payload);
  else if (topic.endsWith("/arm")) handleArm(payload);
  else if (topic.endsWith("/buzz")) { digitalWrite(PIN_BUZZ, payload == "on" ? HIGH : LOW); }
  else if (topic.endsWith("/face")) { faceMode = payload; drawFace(); }
  else if (topic.endsWith("/text")) { d.clearDisplay(); d.setTextSize(1); d.setCursor(4, 28); d.print(payload); d.display(); }
}

#ifdef USE_MQTT
WiFiClient wc;
PubSubClient mqtt(wc);
void onMqtt(char* t, byte* p, unsigned int n) {
  String topic = String(t), payload = "";
  for (unsigned int i = 0; i < n; i++) payload += (char)p[i];
  handleCmd(topic, payload);
}
#endif

void setup() {
  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL);
  d.begin(SSD1306_SWITCHCAPVCC, 0x3C);
#ifdef HAS_ARM
  arm.attach(PIN_SERVO); arm.write(90);
#endif
  pinMode(PIN_BUZZ, OUTPUT);
  pinMode(PIN_TRIG, OUTPUT); pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_BTN, INPUT_PULLUP);
  pinMode(PIN_AIN1, OUTPUT); pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_BIN1, OUTPUT); pinMode(PIN_BIN2, OUTPUT);
  drawFace();
  Serial.println("[PANDA] SAN SANG. Lenh: face X | move X | arm X | buzz on/off | text X");
#ifdef USE_MQTT
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(300); }
  mqtt.setServer(MQTT_HOST, 1883); mqtt.setCallback(onMqtt);
#endif
}

long readDist() {
#ifndef USE_MQTT
  // Chế độ mô phỏng: xoay potentiometer để đổi khoảng cách 4–400cm
  return map(analogRead(PIN_POT), 0, 4095, 4, 400);
#endif
  digitalWrite(PIN_TRIG, LOW); delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  long t = pulseIn(PIN_ECHO, HIGH, 30000);
  return t * 0.0343 / 2;
}

void loop() {
#ifdef USE_MQTT
  if (!mqtt.connected()) {
    if (mqtt.connect("panda_body")) mqtt.subscribe("panda/cmd/#");
  }
  mqtt.loop();
#else
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n'); line.trim();
    int sp = line.indexOf(' ');
    if (sp > 0) { handleCmd("panda/cmd/" + line.substring(0, sp), line.substring(sp + 1)); lastCmd = millis(); }
  }
#endif
  // DEMO WOKWI: không có lệnh 8s → tự diễn vòng 14 mặt, mỗi 2.5s
  if (millis() - lastCmd > 8000 && millis() - lastCycle > 2500) {
    lastCycle = millis();
    cycleIdx = (cycleIdx + 1) % 14;
    faceMode = FACE_LIST[cycleIdx];
    Serial.println("[FACE] " + faceMode);
    drawFace();
  }
  // face động (thinking/speaking) ~10fps
  if (millis() - lastAnim > 100) { lastAnim = millis(); animFrame++;
    if (faceMode == "thinking" || faceMode == "speaking") drawFace(); }
  // status 2Hz
  if (millis() - lastStatus > 500) { lastStatus = millis();
    long dist = readDist(); int btn = digitalRead(PIN_BTN) == LOW ? 1 : 0;
    String s = "{\"dist\":" + String(dist) + ",\"btn\":" + String(btn) + "}";
#ifdef USE_MQTT
    if (mqtt.connected()) mqtt.publish("panda/status", s.c_str());
#else
    Serial.println("[STATUS] " + s);
#endif
  }
}
