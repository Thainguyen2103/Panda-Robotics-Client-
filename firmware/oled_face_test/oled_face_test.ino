/*
 * PANDA ROBOT FACE TEST — ESP32 + ILI9341 320x240
 * ================================================================
 * The test sketch uses the same framebuffer renderer as the main firmware.
 *
 * Serial Monitor (115200 baud):
 *   face neutral / happy / sad / angry / surprised / love / wink
 *   face sleepy / cool / cute / dizzy
 *   face questioning / hearing / ai-thinking / speaking
 *   text <noi dung>  (chi kich hoat attentive eyes, khong ve chu)
 *   demo
 */

#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

#include "../panda_firmware/Config.h"
#include "../panda_firmware/FaceRenderer.h"

Adafruit_ILI9341 tft(TFT_CS, TFT_DC, TFT_RST);

String faceMode = "neutral";
String lastFaceMode = "";
String faceText = "Toi co the giup gi cho ban?";

unsigned long lastFrameMicros = 0;
unsigned long lastCycle = 0;
unsigned long lastBlink = 0;
unsigned long blinkStart = 0;
unsigned long nextBlink = 3200;

uint32_t animFrame = 0;
int cycleIndex = -1;
uint8_t eyeOpen = 100;
bool isBlinking = false;
bool autoDemo = true;
bool needRedraw = true;

const char *FACE_LIST[] = {
  "neutral", "happy", "sad", "angry", "surprised", "love", "wink",
  "sleepy", "cool", "cute", "dizzy",
  "questioning", "hearing", "ai-thinking", "speaking"
};
const int FACE_COUNT = sizeof(FACE_LIST) / sizeof(FACE_LIST[0]);

static bool faceSupportsBlink(const String &mode) {
  return mode != "happy" && mode != "sleepy";
}

static void updateBlink(unsigned long now) {
  if (!faceSupportsBlink(faceMode)) {
    isBlinking = false;
    eyeOpen = 100;
    return;
  }

  if (!isBlinking && now - lastBlink >= nextBlink) {
    isBlinking = true;
    blinkStart = now;
    lastBlink = now;
    nextBlink = random(2500, 5500);
  }

  if (!isBlinking) return;

  unsigned long elapsed = now - blinkStart;
  if (elapsed >= FACE_BLINK_MS) {
    isBlinking = false;
    eyeOpen = 100;
    return;
  }

  eyeOpen = calculateBlinkOpen(elapsed);
}

static void readSerialCommand() {
  if (!Serial.available()) return;

  String command = Serial.readStringUntil('\n');
  command.trim();

  if (command == "demo") {
    autoDemo = !autoDemo;
    lastCycle = millis();
    Serial.println(autoDemo ? "[DEMO] ON" : "[DEMO] OFF");
  } else if (command.startsWith("text ")) {
    faceText = command.substring(5);
    faceMode = "hearing";
    autoDemo = false;
    needRedraw = true;
  } else if (command.startsWith("face ")) {
    faceMode = command.substring(5);
    faceMode.trim();
    faceText = faceMode == "hearing" ? "Dang nghe ban noi..." : "";
    autoDemo = false;
    needRedraw = true;
    Serial.println("[FACE] " + faceMode);
  }
}

void setup() {
  Serial.begin(115200);
  delay(150);

  tft.begin(40000000);
  tft.setRotation(1);
  tft.fillScreen(COLOR_BG);

  if (!initFaceRenderer()) {
    Serial.println("[DISPLAY] ERROR: Khong du RAM cho face framebuffer");
  }

  // Không có boot logo: màn hình luôn chỉ hiển thị đúng hai mắt.
  renderFaceToDisplay(tft, faceMode, faceText, animFrame, eyeOpen);
  lastFaceMode = faceMode;
  lastFrameMicros = micros();

  Serial.println("[READY] face <mode> | text <content> | demo");
}

void loop() {
  unsigned long now = millis();
  unsigned long nowMicros = micros();
  readSerialCommand();

  if (autoDemo && now - lastCycle >= 3000) {
    lastCycle = now;
    cycleIndex = (cycleIndex + 1) % FACE_COUNT;
    faceMode = FACE_LIST[cycleIndex];
    faceText = faceMode == "hearing" ? "Hom nay ban cam thay the nao?" : "";
    needRedraw = true;
    Serial.println("[DEMO] " + faceMode);
  }

  updateBlink(now);

  bool modeChanged = faceMode != lastFaceMode;
  if (modeChanged) {
    lastFaceMode = faceMode;
    animFrame = 0;
    isBlinking = false;
    eyeOpen = 100;
    if (faceSupportsBlink(faceMode)) {
      lastBlink = now;
      nextBlink = random(1200, 2200);
    }
    needRedraw = true;
  }

  if (needRedraw || nowMicros - lastFrameMicros >= FACE_FRAME_US) {
    lastFrameMicros = nowMicros;
    if (!modeChanged) animFrame++;
    renderFaceToDisplay(tft, faceMode, faceText, animFrame, eyeOpen);
    needRedraw = false;
  }
}
