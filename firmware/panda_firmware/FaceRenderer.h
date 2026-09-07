#ifndef FACE_RENDERER_H
#define FACE_RENDERER_H

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include "Config.h"

// Compose a complete frame in RAM, then transfer it to the TFT in one pass.
// Eyes have no pupils or highlights. A few explicit modes reshape them into symbols:
// love uses hearts, cool uses sunglasses, and hearing adds a small '?'.
static GFXcanvas16 faceCanvas(CANVAS_W, CANVAS_H);

static const int FACE_CX = CANVAS_W / 2;
static const int FACE_CY = CANVAS_H / 2;
static const int LEFT_EYE_X = FACE_CX - 40;
static const int RIGHT_EYE_X = FACE_CX + 40;

struct EyePose {
  int cx;
  int cy;
  int width;
  int height;
  float tiltDeg;
  uint16_t color;
  int topSlope;
};

static float faceWave(uint32_t frame, float speed, float phase = 0.0f) {
  return sinf(frame * speed * FACE_MOTION_SPEED + phase);
}

static uint8_t calculateBlinkOpen(unsigned long elapsedMs) {
  const int travel = 100 - FACE_MIN_EYE_OPEN;
  if (elapsedMs < FACE_BLINK_CLOSE_MS) {
    return 100 - (uint8_t)(elapsedMs * travel / FACE_BLINK_CLOSE_MS);
  }

  elapsedMs -= FACE_BLINK_CLOSE_MS;
  if (elapsedMs < FACE_BLINK_HOLD_MS) return FACE_MIN_EYE_OPEN;

  elapsedMs -= FACE_BLINK_HOLD_MS;
  if (elapsedMs < FACE_BLINK_OPEN_MS) {
    return FACE_MIN_EYE_OPEN +
           (uint8_t)(elapsedMs * travel / FACE_BLINK_OPEN_MS);
  }
  return 100;
}

static EyePose makeEye(
  int cx, int cy, int width, int height,
  float tiltDeg = 0.0f, uint16_t color = COLOR_CYAN,
  int topSlope = 0
) {
  EyePose eye = {cx, cy, width, height, tiltDeg, color, topSlope};
  return eye;
}

static void drawSolidEye(GFXcanvas16 &g, const EyePose &pose, uint8_t blinkOpen) {
  int width = max(8, pose.width);
  int height = max(4, pose.height * (int)blinkOpen / 100);
  int halfWidth = width / 2;
  int radius = min(halfWidth, max(2, height / 3));
  int straightHalfHeight = max(0, height / 2 - radius);
  int top = pose.cy - height / 2;
  float tangent = tanf(pose.tiltDeg * PI / 180.0f);

  // Scanline pill allows the whole solid eye to tilt without adding eyebrows/masks.
  for (int row = 0; row < height; row++) {
    float centeredY = row - (height - 1) * 0.5f;
    float distanceY = fabsf(centeredY);
    int rowHalfWidth = halfWidth;

    if (distanceY > straightHalfHeight) {
      float circleY = distanceY - straightHalfHeight;
      float circleX = sqrtf(max(0.0f, (float)(radius * radius) - circleY * circleY));
      rowHalfWidth = max(1, halfWidth - radius + (int)roundf(circleX));
    }

    int shiftX = (int)roundf(centeredY * tangent);
    g.drawFastHLine(pose.cx + shiftX - rowHalfWidth, top + row,
                    rowHalfWidth * 2 + 1, pose.color);
  }

  // Shape only the upper eyelid. This reads as emotion without a separate brow.
  int topSlope = pose.topSlope * (int)blinkOpen / 100;
  int left = pose.cx - halfWidth;
  int right = pose.cx + halfWidth;
  if (topSlope > 0) {
    g.fillTriangle(left, top, right, top, right, top + topSlope, COLOR_BG);
  } else if (topSlope < 0) {
    g.fillTriangle(left, top, right, top, left, top - topSlope, COLOR_BG);
  }
}

static void drawThickSegment(
  GFXcanvas16 &g, int x0, int y0, int x1, int y1,
  int radius, uint16_t color
) {
  int steps = max(abs(x1 - x0), abs(y1 - y0));
  if (steps == 0) {
    g.fillCircle(x0, y0, radius, color);
    return;
  }
  for (int i = 0; i <= steps; i++) {
    int x = x0 + (x1 - x0) * i / steps;
    int y = y0 + (y1 - y0) * i / steps;
    g.fillCircle(x, y, radius, color);
  }
}

static void drawHappyArcEye(
  GFXcanvas16 &g, int cx, int cy, bool mirror,
  uint16_t color = COLOR_CYAN
) {
  int lean = mirror ? 2 : -2;
  drawThickSegment(g, cx - 25, cy + 8, cx - 11, cy - 4 + lean, 5, color);
  drawThickSegment(g, cx - 11, cy - 4 + lean, cx, cy - 8, 5, color);
  drawThickSegment(g, cx, cy - 8, cx + 11, cy - 4 - lean, 5, color);
  drawThickSegment(g, cx + 11, cy - 4 - lean, cx + 25, cy + 8, 5, color);
}

static void drawDizzyCrossEye(
  GFXcanvas16 &g, int cx, int cy, float angle, uint16_t color
) {
  const int arm = 17;
  float c = cosf(angle);
  float s = sinf(angle);
  int x1 = cx + (int)roundf((-arm) * c - (-arm) * s);
  int y1 = cy + (int)roundf((-arm) * s + (-arm) * c);
  int x2 = cx + (int)roundf(arm * c - arm * s);
  int y2 = cy + (int)roundf(arm * s + arm * c);
  int x3 = cx + (int)roundf((-arm) * c - arm * s);
  int y3 = cy + (int)roundf((-arm) * s + arm * c);
  int x4 = cx + (int)roundf(arm * c - (-arm) * s);
  int y4 = cy + (int)roundf(arm * s + (-arm) * c);
  drawThickSegment(g, x1, y1, x2, y2, 5, color);
  drawThickSegment(g, x3, y3, x4, y4, 5, color);
}

static void drawHeartEye(
  GFXcanvas16 &g, int cx, int cy, int size, uint16_t color
) {
  // Two round lobes and one tapered point form a clean solid heart silhouette.
  int radius = max(7, size / 4);
  int lobeOffset = max(6, size / 5);
  int lobeY = cy - size / 7;
  int halfWidth = size / 2;
  g.fillCircle(cx - lobeOffset, lobeY, radius, color);
  g.fillCircle(cx + lobeOffset, lobeY, radius, color);
  g.fillTriangle(cx - halfWidth, lobeY, cx + halfWidth, lobeY,
                 cx, cy + size / 2, color);
}

static void drawSunglasses(GFXcanvas16 &g, uint32_t frame) {
  int bob = (int)roundf(faceWave(frame, 0.15f) * 3.0f);
  int swagger = (int)roundf(faceWave(frame, 0.075f, PI / 2.0f) * 5.0f);
  const int lensW = 62;
  const int lensH = 42;
  const int radius = 9;
  int leftX = LEFT_EYE_X + swagger - lensW / 2;
  int rightX = RIGHT_EYE_X + swagger - lensW / 2;
  int top = FACE_CY - lensH / 2 + bob;

  // Bright frames remain readable on the navy display; dark lenses have no pupils.
  g.fillRoundRect(leftX, top, lensW, lensH, radius, COLOR_CYAN);
  g.fillRoundRect(rightX, top, lensW, lensH, radius, COLOR_CYAN);
  g.fillRoundRect(leftX + 5, top + 5, lensW - 10, lensH - 10,
                  radius - 3, COLOR_DARK_GRAY);
  g.fillRoundRect(rightX + 5, top + 5, lensW - 10, lensH - 10,
                  radius - 3, COLOR_DARK_GRAY);
  g.fillRect(leftX + lensW - 1, top + 12, rightX - leftX - lensW + 2,
             7, COLOR_CYAN);
  g.fillRect(leftX - 7, top + 8, 8, 6, COLOR_CYAN);
  g.fillRect(rightX + lensW - 1, top + 8, 8, 6, COLOR_CYAN);
}

static void drawEyePair(
  GFXcanvas16 &g, const EyePose &leftEye, const EyePose &rightEye,
  uint8_t eyeOpen
) {
  drawSolidEye(g, leftEye, eyeOpen);
  drawSolidEye(g, rightEye, eyeOpen);
}

static void drawNeutralEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen, int moveX, int moveY) {
  int breatheY = (int)roundf(faceWave(frame, 0.09f) * 1.5f);
  int breatheH = (int)roundf(faceWave(frame, 0.09f, 1.2f) * 1.5f);
  EyePose left = makeEye(LEFT_EYE_X + moveX, FACE_CY + moveY + breatheY, 50, 70 + breatheH);
  EyePose right = makeEye(RIGHT_EYE_X + moveX, FACE_CY + moveY + breatheY, 50, 70 + breatheH);
  drawEyePair(g, left, right, eyeOpen);
}

static void drawHappyEyes(GFXcanvas16 &g, uint32_t frame) {
  int bounce = (int)roundf(faceWave(frame, 0.12f) * 2.0f);
  drawHappyArcEye(g, LEFT_EYE_X, FACE_CY + bounce, false);
  drawHappyArcEye(g, RIGHT_EYE_X, FACE_CY + bounce, true);
}

static void drawSadEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  int sink = 5 + (int)roundf(faceWave(frame, 0.07f) * 1.5f);
  EyePose left = makeEye(LEFT_EYE_X, FACE_CY + sink, 52, 58, 0.0f, COLOR_RED, -18);
  EyePose right = makeEye(RIGHT_EYE_X, FACE_CY + sink, 52, 58, 0.0f, COLOR_RED, 18);
  drawEyePair(g, left, right, eyeOpen);
}

static void drawAngryEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  int shake = ((frame / 2) % 3) - 1;
  EyePose left = makeEye(LEFT_EYE_X + shake, FACE_CY + 9, 56, 52, 0.0f, COLOR_TEAL, 18);
  EyePose right = makeEye(RIGHT_EYE_X + shake, FACE_CY + 9, 56, 52, 0.0f, COLOR_TEAL, -18);
  drawEyePair(g, left, right, min((int)eyeOpen, 88));
}

static void drawSurprisedEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  int pulse = (int)roundf((faceWave(frame, 0.11f) + 1.0f) * 2.0f);
  EyePose left = makeEye(LEFT_EYE_X, FACE_CY - 4, 63 + pulse, 84 + pulse, 0.0f, COLOR_ORANGE);
  EyePose right = makeEye(RIGHT_EYE_X, FACE_CY - 4, 63 + pulse, 84 + pulse, 0.0f, COLOR_ORANGE);
  drawEyePair(g, left, right, eyeOpen);
}

static void drawWinkEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  int bounce = (int)roundf(faceWave(frame, 0.10f) * 1.5f);
  (void)eyeOpen;
  drawHappyArcEye(g, LEFT_EYE_X, FACE_CY - 3 + bounce, false);
  EyePose right = makeEye(RIGHT_EYE_X, FACE_CY + 12 + bounce, 49, 8, 8.0f);
  drawSolidEye(g, right, 100);
}

static void drawSleepyEyes(GFXcanvas16 &g, uint32_t frame) {
  int drift = 10 + (int)roundf(faceWave(frame, 0.07f) * 3.0f);
  EyePose left = makeEye(LEFT_EYE_X, FACE_CY + drift, 52, 10, -2.0f, COLOR_PURPLE);
  EyePose right = makeEye(RIGHT_EYE_X, FACE_CY + drift, 52, 10, 2.0f, COLOR_PURPLE);
  drawEyePair(g, left, right, 100);
}

static void drawCoolEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  (void)eyeOpen;
  drawSunglasses(g, frame);
}

static void drawCuteEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  float pulse = faceWave(frame, 0.095f);
  int delta = (int)roundf(pulse * 11.0f);
  int bounce = (int)roundf(fabsf(faceWave(frame, 0.16f)) * -6.0f);
  int sway = (int)roundf(faceWave(frame, 0.08f) * 5.0f);
  EyePose left = makeEye(LEFT_EYE_X + 5 + sway, FACE_CY - 4 + bounce,
                         58 + delta / 2, 79 + delta, -8.0f, COLOR_CUTE_PINK);
  EyePose right = makeEye(RIGHT_EYE_X - 5 + sway, FACE_CY + 3 + bounce,
                          52 - delta / 2, 66 - delta, 8.0f, COLOR_CUTE_PINK);
  drawEyePair(g, left, right, eyeOpen);
}

static void drawLoveEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  (void)eyeOpen;
  float beatWave = faceWave(frame, 0.18f);
  float beat = (beatWave + 1.0f) * 0.5f;
  int grow = (int)roundf(beat * 8.0f);
  int inward = (int)roundf(beat * 4.0f);
  int lift = (int)roundf(fabsf(beatWave) * -4.0f);
  drawHeartEye(g, LEFT_EYE_X + inward, FACE_CY + lift, 48 + grow, COLOR_PINK);
  drawHeartEye(g, RIGHT_EYE_X - inward, FACE_CY + lift, 48 + grow, COLOR_PINK);
}

static void drawDizzyEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  (void)eyeOpen;
  float angle = frame * 0.085f * FACE_MOTION_SPEED;
  int wobbleY = (int)roundf(faceWave(frame, 0.13f) * 3.0f);
  drawDizzyCrossEye(g, LEFT_EYE_X, FACE_CY + wobbleY, angle, COLOR_YELLOW);
  drawDizzyCrossEye(g, RIGHT_EYE_X, FACE_CY - wobbleY, -angle, COLOR_YELLOW);
}

static void drawQuestioningEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  // One eye opens while the other squints, then they trade emphasis smoothly.
  float curiosity = faceWave(frame, 0.095f);
  int leftHeight = 49 + (int)roundf(curiosity * 30.0f);
  int rightHeight = 49 - (int)roundf(curiosity * 30.0f);
  int moveX = (int)roundf(faceWave(frame, 0.065f) * 7.0f);
  int moveY = -2 + (int)roundf(faceWave(frame, 0.11f) * 4.0f);
  EyePose left = makeEye(LEFT_EYE_X + moveX, FACE_CY + moveY, 55, leftHeight, -9.0f);
  EyePose right = makeEye(RIGHT_EYE_X + moveX, FACE_CY + moveY, 55, rightHeight, 9.0f);
  drawEyePair(g, left, right, eyeOpen);
}

static void drawListeningEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  // A strong attentive reaction: very wide eyes plus a bouncing question mark.
  float focus = (faceWave(frame, 0.15f) + 1.0f) * 0.5f;
  int grow = (int)roundf(focus * 7.0f);
  int inward = (int)roundf(focus);
  int bob = (int)roundf(faceWave(frame, 0.18f, PI / 2.0f) * 4.0f);
  EyePose left = makeEye(LEFT_EYE_X + inward, FACE_CY + 2 + bob, 60 + grow, 79 + grow);
  EyePose right = makeEye(RIGHT_EYE_X - inward, FACE_CY + 2 + bob, 60 + grow, 79 + grow);
  drawEyePair(g, left, right, eyeOpen);

  g.setTextColor(COLOR_GREEN);
  g.setTextSize(2);
  g.setCursor(FACE_CX - 6, 4 + (int)roundf(faceWave(frame, 0.18f) * 3.0f));
  g.print("?");
}

static void drawThinkingEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  // The pair revolves around the face center, so the thinking loop is unmistakable.
  float angle = frame * 0.080f * FACE_MOTION_SPEED;
  int orbitX = (int)roundf(cosf(angle) * 38.0f);
  int orbitY = (int)roundf(sinf(angle) * 22.0f);
  int pulse = (int)roundf(sinf(angle * 2.0f) * 4.0f);
  EyePose left = makeEye(FACE_CX - orbitX, FACE_CY - orbitY, 37 + pulse, 42 - pulse,
                         cosf(angle) * 18.0f, COLOR_PURPLE);
  EyePose right = makeEye(FACE_CX + orbitX, FACE_CY + orbitY, 37 - pulse, 42 + pulse,
                          -cosf(angle) * 18.0f, COLOR_PURPLE);
  drawEyePair(g, left, right, min((int)eyeOpen, 92));
}

static void drawSpeakingEyes(GFXcanvas16 &g, uint32_t frame, uint8_t eyeOpen) {
  // Fast, synchronized squash-and-lift reads as syllables without drawing a mouth.
  float voice = 0.65f * fabsf(faceWave(frame, 0.30f)) +
                0.35f * fabsf(faceWave(frame, 0.52f, 0.7f));
  int height = 22 + (int)roundf(voice * 52.0f);
  int width = 58 - (int)roundf(voice * 5.0f);
  int y = FACE_CY + 9 - (int)roundf(voice * 13.0f);
  float tilt = 4.0f + voice * 5.0f;
  EyePose left = makeEye(LEFT_EYE_X, y, width, height, -tilt);
  EyePose right = makeEye(RIGHT_EYE_X, y, width, height, tilt);
  drawEyePair(g, left, right, eyeOpen);
}

static bool initFaceRenderer() {
  return faceCanvas.getBuffer() != nullptr;
}

static void renderFaceToDisplay(
  Adafruit_ILI9341 &tft, const String &mode, const String &text,
  uint32_t frame, uint8_t eyeOpen
) {
  if (!faceCanvas.getBuffer()) return;
  (void)text;

  GFXcanvas16 &g = faceCanvas;
  g.fillScreen(COLOR_BG);

  if (mode == "happy") {
    drawHappyEyes(g, frame);
  } else if (mode == "sad") {
    drawSadEyes(g, frame, eyeOpen);
  } else if (mode == "angry") {
    drawAngryEyes(g, frame, eyeOpen);
  } else if (mode == "surprised") {
    drawSurprisedEyes(g, frame, eyeOpen);
  } else if (mode == "wink") {
    drawWinkEyes(g, frame, eyeOpen);
  } else if (mode == "sleepy") {
    drawSleepyEyes(g, frame);
  } else if (mode == "cool") {
    drawCoolEyes(g, frame, eyeOpen);
  } else if (mode == "cute") {
    drawCuteEyes(g, frame, eyeOpen);
  } else if (mode == "love") {
    drawLoveEyes(g, frame, eyeOpen);
  } else if (mode == "dizzy") {
    drawDizzyEyes(g, frame, eyeOpen);
  } else if (mode == "questioning") {
    drawQuestioningEyes(g, frame, eyeOpen);
  } else if (mode == "hearing") {
    drawListeningEyes(g, frame, eyeOpen);
  } else if (mode == "ai-thinking" || mode == "thinking") {
    drawThinkingEyes(g, frame, eyeOpen);
  } else if (mode == "speaking") {
    drawSpeakingEyes(g, frame, eyeOpen);
  } else if (mode == "idle-look-left") {
    drawNeutralEyes(g, frame, eyeOpen, -16, 0);
  } else if (mode == "idle-look-right") {
    drawNeutralEyes(g, frame, eyeOpen, 16, 0);
  } else if (mode == "idle-look-up") {
    drawNeutralEyes(g, frame, eyeOpen, 0, -12);
  } else if (mode == "idle-curious") {
    EyePose left = makeEye(LEFT_EYE_X, FACE_CY - 3, 59, 82, -3.0f);
    EyePose right = makeEye(RIGHT_EYE_X, FACE_CY + 3, 43, 60, 3.0f);
    drawEyePair(g, left, right, eyeOpen);
  } else if (mode == "idle-squint") {
    EyePose left = makeEye(LEFT_EYE_X, FACE_CY, 56, 27, -3.0f);
    EyePose right = makeEye(RIGHT_EYE_X, FACE_CY, 56, 27, 3.0f);
    drawEyePair(g, left, right, min((int)eyeOpen, 72));
  } else {
    drawNeutralEyes(g, frame, eyeOpen, 0, 0);
  }

  tft.drawRGBBitmap(CANVAS_X, CANVAS_Y, g.getBuffer(), CANVAS_W, CANVAS_H);
}

#endif // FACE_RENDERER_H
