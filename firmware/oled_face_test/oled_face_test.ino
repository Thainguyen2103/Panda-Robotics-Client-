/*
 * PANDA OLED FACE TEST — bản tối giản chỉ để test màn hình trên Wokwi
 * ================================================================
 * Part cần duy nhất: board-ssd1306  (SDA→21, SCL→22, VCC→3V3, GND→GND)
 * Libraries: "Adafruit SSD1306" + "Adafruit GFX Library"
 *
 * Chạy: bấm Play → để yên 8s, Panda TỰ diễn vòng 14 mặt (2.5s/mặt).
 * Gõ Serial:  face happy | face love | face speaking | ...  để giữ 1 mặt.
 */
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

Adafruit_SSD1306 d(128, 64, &Wire, -1);
String faceMode = "neutral";
unsigned long lastCmd = 0, lastCycle = 0, lastAnim = 0;
int animFrame = 0, cycleIdx = -1;
const char* FACE_LIST[] = { "neutral", "happy", "sad", "angry", "surprised", "love", "wink",
                            "sleepy", "cool", "cute", "dizzy", "questioning", "thinking", "speaking" };

// ── Helper vẽ ──
void eye(int x, int y, int w, int h) { d.fillRoundRect(x, y, w, h, 9, WHITE); }
void mouth(int cx, int cy, bool smile) {
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

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  d.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  drawFace();
  Serial.println("[OLED TEST] San sang. Go: face <ten> | de yen = auto demo.");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n'); line.trim();
    int sp = line.indexOf(' ');
    if (sp > 0 && line.substring(0, sp) == "face") {
      faceMode = line.substring(sp + 1);
      lastCmd = millis();
      Serial.println("[FACE] " + faceMode);
      drawFace();
    }
  }
  // Auto demo: không lệnh 8s → vòng 14 mặt, 2.5s/mặt
  if (millis() - lastCmd > 8000 && millis() - lastCycle > 2500) {
    lastCycle = millis();
    cycleIdx = (cycleIdx + 1) % 14;
    faceMode = FACE_LIST[cycleIdx];
    Serial.println("[FACE] " + faceMode);
    drawFace();
  }
  // thinking/speaking animation ~10fps
  if (millis() - lastAnim > 100) { lastAnim = millis(); animFrame++;
    if (faceMode == "thinking" || faceMode == "speaking") drawFace(); }
}
