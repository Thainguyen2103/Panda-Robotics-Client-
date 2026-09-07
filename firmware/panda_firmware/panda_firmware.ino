/*
 * PANDA ROBOT FIRMWARE (ESP32) — REPLICA CHUẨN DASHBOARD WEB
 * ================================================================
 * Màn hình: ILI9341 TFT-LCD (SPI 320×240 Landscape, Full Color RGB565)
 * Công nghệ: Off-screen framebuffer (GFXcanvas16) — không xóa/vẽ trực tiếp lên TFT
 *
 * Hỗ trợ 2 chế độ hoạt động:
 *   [1] Mô phỏng Wokwi / Serial Monitor: Test không cần WiFi/MQTT
 *   [2] Robot thật: Bật #define USE_MQTT trong Config.h để kết nối WiFi & MQTT
 *
 * Giao thức MQTT đồng bộ 100% với Dashboard:
 *   Sub: panda/cmd/move    -> forward | back | left | right | stop
 *   Sub: panda/cmd/face    -> neutral | happy | sad | angry | surprised | love | ...
 *   Sub: panda/cmd/text    -> kích hoạt trạng thái attentive (không vẽ chữ)
 *   Sub: panda/cmd/buzz    -> on | off
 *   Sub: panda/ai/state    -> listening | speaking | thinking | standby
 *   Sub: panda/ai/thinking -> JSON { "stage": "question", "text": "..." }
 *   Pub: panda/status      -> JSON { "dist": 25, "btn": 0 } (2Hz)
 * ================================================================
 */

#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <ArduinoJson.h>

#include "Config.h"
#include "FaceRenderer.h"
#include "RobotMotor.h"

#ifdef USE_MQTT
#include <WiFi.h>
#include <PubSubClient.h>
WiFiClient espClient;
PubSubClient mqtt(espClient);
#endif

// Khởi tạo đối tượng màn hình ILI9341
Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC, TFT_RST);

// ─── Trạng thái hệ thống ──────────────────────────────────────
String faceMode     = "neutral";
String lastFaceMode = "";
String oledText     = "";

unsigned long lastAnimMicros = 0;
unsigned long lastStatus     = 0;
unsigned long lastCmdTime    = 0;
unsigned long lastIdleAction = 0;
unsigned long nextIdleAction = 7000;
unsigned long lastCycle      = 0;

int  animFrame   = 0;
int  cycleIdx    = -1;
bool isBlinking  = false;
uint8_t eyeOpen  = 100;
bool needRedraw  = true;
bool autoDemo    = false; // Mặc định tắt auto-demo khi chạy robot thật/mô phỏng chính thức

unsigned long blinkStart = 0;
unsigned long lastBlink  = 0;
unsigned long nextBlink  = 3500;

bool inIdleAction = false;
unsigned long idleActionStart = 0;

#ifdef USE_MQTT
unsigned long lastMqttAttempt = 0;
const unsigned long MQTT_RETRY_MS = 5000;
#endif

const char* DEMO_FACE_LIST[] = {
  "neutral", "happy", "sad", "angry", "surprised", "love", "wink",
  "sleepy", "cool", "cute", "dizzy",
  "questioning", "hearing", "ai-thinking", "speaking"
};
const int DEMO_FACE_COUNT = 15;

// ================================================================
//  XỬ LÝ LỆNH TỪ DASHBOARD & MQTT
// ================================================================

// 1. Lệnh AI (panda/ai/*) — đồng bộ 100% với hàm setOledAiMode() của dashboard
void handleAiCmd(String subtopic, String payload) {
  inIdleAction = false;

  // panda/ai/state — listening | speaking | thinking | standby
  if (subtopic == "state") {
    if (payload == "listening") {
      faceMode = "hearing";
      oledText = "";
      Serial.println("[AI] state: listening -> attentive eyes");
    } else if (payload == "speaking") {
      faceMode = "speaking";
      Serial.println("[AI] state: speaking -> face speaking");
    } else if (payload == "thinking") {
      faceMode = "ai-thinking";
      Serial.println("[AI] state: thinking -> thinking eyes");
    } else { // standby
      faceMode = "neutral";
      oledText = "";
      Serial.println("[AI] state: standby -> face neutral");
    }
    needRedraw = true;
    return;
  }

  // panda/ai/thinking — JSON stage-based: { "stage": "question", "text": "..." }
  if (subtopic == "thinking") {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
      Serial.println("[AI] JSON Parse Error: " + String(err.c_str()));
      return;
    }

    const char* stage = doc["stage"] | "idle";
    const char* text  = doc["text"]  | "";

    if (strcmp(stage, "listening") == 0) {
      faceMode = "hearing";
      oledText = "";
      Serial.println("[AI] thinking/listening -> attentive eyes");
    } else if (strcmp(stage, "question") == 0) {
      faceMode = "questioning";
      oledText = String(text);
      Serial.println("[AI] thinking/question -> curious eyes");
    } else if (strcmp(stage, "thinking") == 0) {
      faceMode = "ai-thinking";
      Serial.println("[AI] thinking/thinking -> thinking eyes");
    } else if (strcmp(stage, "answering") == 0) {
      // Giữ transcript hoặc chuẩn bị sang speaking
      Serial.println("[AI] thinking/answering -> face " + faceMode);
    } else if (strcmp(stage, "done") == 0) {
      Serial.println("[AI] thinking/done");
    } else { // idle
      faceMode = "neutral";
      oledText = "";
      Serial.println("[AI] thinking/idle -> face neutral");
    }
    needRedraw = true;
    return;
  }
}

// 2. Lệnh chung (panda/cmd/* và Serial)
void handleGeneralCmd(String topic, String payload) {
  lastCmdTime = millis();
  inIdleAction = false;

  // panda/cmd/move -> forward | back | left | right | stop
  if (topic.endsWith("/move")) {
    handleMoveCmd(payload);
  }
  // panda/cmd/face -> neutral | happy | sad | angry | ...
  else if (topic.endsWith("/face")) {
    faceMode = payload;
    oledText = "";
    autoDemo = false;
    needRedraw = true;
    Serial.println("[PANDA] Set face: " + faceMode);
  }
  // panda/cmd/text -> giữ tương thích giao thức; mặt chỉ chuyển sang attentive eyes
  else if (topic.endsWith("/text")) {
    faceMode = "hearing";
    oledText = payload;
    autoDemo = false;
    needRedraw = true;
    Serial.println("[PANDA] Transcript received -> attentive eyes");
  }
  // panda/cmd/buzz -> on | off
  else if (topic.endsWith("/buzz")) {
    setBuzzer(payload == "on" || payload == "1");
  }
  // panda/cmd/arm -> wave | up | down
  else if (topic.endsWith("/arm")) {
    handleArmCmd(payload);
  }
  // panda/ai/*
  else if (topic.indexOf("/ai/") >= 0) {
    int idx = topic.indexOf("/ai/") + 4;
    handleAiCmd(topic.substring(idx), payload);
  }
}

// ================================================================
//  MQTT CALLBACK & KẾT NỐI
// ================================================================
#ifdef USE_MQTT
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String t = String(topic);
  String p = "";
  for (unsigned int i = 0; i < length; i++) p += (char)payload[i];
  handleGeneralCmd(t, p);
}

void checkMqttConnection() {
  if (mqtt.connected()) return;

  unsigned long now = millis();
  if (lastMqttAttempt != 0 && now - lastMqttAttempt < MQTT_RETRY_MS) return;
  lastMqttAttempt = now;

  Serial.print("[MQTT] Connecting to Broker...");
  if (mqtt.connect("PandaRobot_Body")) {
    Serial.println(" Connected!");
    mqtt.subscribe("panda/cmd/#");
    mqtt.subscribe("panda/ai/#");
  } else {
    Serial.print(" Failed, rc=");
    Serial.println(mqtt.state());
  }
}
#endif

// ================================================================
//  XỬ LÝ LỆNH QUA SERIAL MONITOR (CHO MÔ PHỎNG & DEBUG)
// ================================================================
void processSerialInput() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  // Lệnh bật/tắt auto demo
  if (line == "demo") {
    autoDemo = !autoDemo;
    inIdleAction = false;
    Serial.println(autoDemo ? "[DEMO] Auto-cycle ON" : "[DEMO] Auto-cycle OFF");
    return;
  }

  int sp = line.indexOf(' ');
  if (sp > 0) {
    String cmd = line.substring(0, sp);
    String val = line.substring(sp + 1);

    if (cmd == "face") {
      handleGeneralCmd("panda/cmd/face", val);
    } else if (cmd == "text") {
      handleGeneralCmd("panda/cmd/text", val);
    } else if (cmd == "move") {
      handleGeneralCmd("panda/cmd/move", val);
    } else if (cmd == "arm") {
      handleGeneralCmd("panda/cmd/arm", val);
    } else if (cmd == "buzz") {
      handleGeneralCmd("panda/cmd/buzz", val);
    } else if (cmd == "ai") {
      int sp2 = val.indexOf(' ');
      if (sp2 > 0) {
        handleGeneralCmd("panda/ai/" + val.substring(0, sp2), val.substring(sp2 + 1));
      } else {
        handleGeneralCmd("panda/ai/" + val, "");
      }
    }
  } else {
    // Lệnh 1 từ: forward, back, left, right, stop
    if (line == "forward" || line == "back" || line == "left" || line == "right" || line == "stop") {
      handleGeneralCmd("panda/cmd/move", line);
    }
  }
}

// ================================================================
//  SETUP HỆ THỐNG
// ================================================================
void setup() {
  Serial.begin(115200);
  delay(150);

  Serial.println("====================================================");
  Serial.println("  PANDA ROBOT — FIRMWARE REPLICA CHUẨN DASHBOARD");
  Serial.println("  Hardware: ESP32 + ILI9341 Color Display (SPI)");
  Serial.println("  Feature : Off-screen Framebuffer Animation");
  Serial.println("====================================================");

  // 1. Khởi tạo ngoại vi & động cơ
  initRobotHardware();

  // 2. Khởi tạo màn hình màu ILI9341
  tft.begin(40000000);
  tft.setRotation(1); // 1 = Landscape 320×240 (xoay ngang)
  tft.fillScreen(COLOR_BG);

  if (!initFaceRenderer()) {
    Serial.println("[DISPLAY] ERROR: Khong du RAM cho face framebuffer");
  }

  // Màn hình luôn chỉ có hai mắt, kể cả lúc khởi động.
  renderFaceToDisplay(tft, faceMode, oledText, animFrame, 100);
  lastFaceMode = faceMode;

#ifdef USE_MQTT
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[WIFI] Connecting to ");
  Serial.println(WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.println("\n[WIFI] Connected! IP: " + WiFi.localIP().toString());
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setSocketTimeout(1);
  mqtt.setCallback(onMqttMessage);
#endif

  Serial.println("[SYSTEM] Ready! Type 'help' or commands (face, move, text, demo)...");
}

// ================================================================
//  MAIN LOOP
// ================================================================
void loop() {
  unsigned long now = millis();
  unsigned long nowMicros = micros();

  // 1. Đọc lệnh từ Serial & MQTT
  processSerialInput();

#ifdef USE_MQTT
  checkMqttConnection();
  mqtt.loop();
#endif

  // 2. Tự động chuyển mode khi bật chế độ Demo
  if (autoDemo && now - lastCycle >= 3000) {
    lastCycle = now;
    cycleIdx = (cycleIdx + 1) % DEMO_FACE_COUNT;
    faceMode = DEMO_FACE_LIST[cycleIdx];
    oledText = (faceMode == "hearing") ? "Hom nay thoi tiet the nao?" : "";
    needRedraw = true;
    Serial.println("[DEMO] Face -> " + faceMode);
  }

  // 3. Hành vi tự chủ khi nhàn rỗi (Idle Micro-Behaviors — Giống Robot Vector & Dashboard)
  // Khi ở mode neutral lâu mà không có lệnh tương tác, robot tự liếc mắt hoặc tò mò
  if (faceMode == "neutral" && !autoDemo && (now - lastCmdTime > 6000)) {
    if (!inIdleAction && now - lastIdleAction >= nextIdleAction) {
      inIdleAction = true;
      idleActionStart = now;
      lastIdleAction = now;
      nextIdleAction = random(5000, 10000); // 5s - 10s làm một trò vui

      int r = random(0, 5);
      if (r == 0)      faceMode = "idle-look-left";
      else if (r == 1) faceMode = "idle-look-right";
      else if (r == 2) faceMode = "idle-curious";
      else if (r == 3) faceMode = "idle-squint";
      else             faceMode = "idle-look-up";

      needRedraw = true;
    }
  }

  // Kết thúc hành vi nhàn rỗi sau 1.4s -> Trở về neutral
  if (inIdleAction && (now - idleActionStart >= 1400)) {
    inIdleAction = false;
    faceMode = "neutral";
    needRedraw = true;
  }

  // 4. Chớp mắt theo đường cong đóng/mở thay vì đổi 2 frame đột ngột.
  bool supportsBlink = (faceMode != "happy" && faceMode != "sleepy");
  if (supportsBlink) {
    if (!isBlinking && now - lastBlink >= nextBlink) {
      isBlinking = true;
      blinkStart = now;
      lastBlink = now;
      nextBlink = random(2500, 5500); // 2.5s - 5.5s chớp 1 lần
      needRedraw = true;
    }

    if (isBlinking) {
      unsigned long elapsed = now - blinkStart;
      if (elapsed >= FACE_BLINK_MS) {
        isBlinking = false;
        eyeOpen = 100;
      } else {
        eyeOpen = calculateBlinkOpen(elapsed);
      }
    }
  } else {
    isBlinking = false;
    eyeOpen = 100;
  }

  // 5. Reset pha animation khi đổi mode. Framebuffer tự thay toàn bộ vùng mặt,
  // nên không cần giữ cờ modeChanged tới lần render kế tiếp.
  bool modeChanged = (faceMode != lastFaceMode);
  if (modeChanged) {
    lastFaceMode = faceMode;
    animFrame = 0;
    isBlinking = false;
    eyeOpen = 100;
    if (supportsBlink) {
      lastBlink = now;
      nextBlink = random(1200, 2200);
    }
    needRedraw = true;
  }

  // 6. Tất cả biểu cảm chạy chung nhịp mục tiêu 60 FPS. Frame được dựng trong
  // canvas 170x100 rồi truyền sang TFT, nên không lộ pha xóa nền trung gian.
  if (needRedraw || nowMicros - lastAnimMicros >= FACE_FRAME_US) {
    lastAnimMicros = nowMicros;
    if (!modeChanged) animFrame++;
    renderFaceToDisplay(tft, faceMode, oledText, animFrame, eyeOpen);
    needRedraw = false;
  }

  // 7. Gửi Telemetry cảm biến định kỳ (2Hz)
  if (now - lastStatus >= 500) {
    lastStatus = now;
    long dist = readUltrasonicDistance();
    int  btn  = (digitalRead(PIN_BTN) == LOW) ? 1 : 0;

    // Tự động dừng động cơ nếu vật cản quá gần (< 12cm)
    if (dist > 0 && dist < 12) {
      setMotorOutput(false, false, false, false, 0);
    }

    String telemetry = "{\"dist\":" + String(dist) + ",\"btn\":" + String(btn) + "}";
#ifdef USE_MQTT
    if (mqtt.connected()) mqtt.publish("panda/status", telemetry.c_str());
#endif
  }
}
