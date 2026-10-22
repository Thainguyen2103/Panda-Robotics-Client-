// face.cpp — vẽ mặt robot lên TFT. Phần vẽ mắt CHÉP NGUYÊN từ tft-selftest/src/main.cpp
// (vốn port từ firmware-demo/src/display.cpp) — chỉ bỏ phần Kanji và vòng tự đổi mặt, thêm
// dòng chữ chú thích bên dưới để hiện AI đang thấy cảm xúc gì.
#include "face.h"
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <math.h>

#define TFT_CS 1
#define TFT_DC 2
#define TFT_RST 14
#define TFT_MOSI 38
#define TFT_SCK 39
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240

Adafruit_ILI9341 tft(&SPI, TFT_DC, TFT_CS, TFT_RST);

// --------------------------------------------------------------------------
// Bảng màu RGB565 — copy nguyên từ firmware-demo/src/display.cpp để mặt trông giống hệt.
// --------------------------------------------------------------------------
#define COLOR_BG 0x0823
#define COLOR_CYAN 0x067F
#define COLOR_GREEN 0x2EB6
#define COLOR_RED 0xF9C7
#define COLOR_ORANGE 0xFD40
#define COLOR_PURPLE 0xA4DF
#define COLOR_PINK 0xF9B0
#define COLOR_CUTE_PINK 0xFBAC
#define COLOR_YELLOW 0xFE75
#define COLOR_TEAL 0x0455
#define COLOR_WHITE 0xFFFF
#define COLOR_DARK_GRAY 0x18E3

#define CANVAS_W 240
#define CANVAS_H 130
#define CANVAS_X ((SCREEN_WIDTH - CANVAS_W) / 2)
#define CANVAS_Y 56

static GFXcanvas16 faceCanvas(CANVAS_W, CANVAS_H);

static const int FACE_CX = CANVAS_W / 2;
static const int FACE_CY = CANVAS_H / 2;
static const int EYE_LX = FACE_CX - 56;
static const int EYE_RX = FACE_CX + 56;

static const unsigned long FRAME_US = 30000UL;
static const float MOTION = 1.75f;

static const unsigned long BLINK_CLOSE_MS = 70;
static const unsigned long BLINK_HOLD_MS = 60;
static const unsigned long BLINK_OPEN_MS = 110;
static const unsigned long BLINK_TOTAL_MS = BLINK_CLOSE_MS + BLINK_HOLD_MS + BLINK_OPEN_MS;
static const int MIN_EYE_OPEN = 4;

static String currentExpression = "neutral";
static uint32_t animFrame = 0;
static unsigned long lastFrameUs = 0;
static unsigned long lastBlinkMs = 0;
static unsigned long blinkStartMs = 0;
static unsigned long nextBlinkGapMs = 3000;
static bool blinking = false;
static uint8_t eyeOpen = 100;


static uint16_t scaleColor(uint16_t c, uint8_t percent)
{
  uint16_t r = (((c >> 11) & 0x1F) * percent) / 100;
  uint16_t g = (((c >> 5) & 0x3F) * percent) / 100;
  uint16_t b = ((c & 0x1F) * percent) / 100;
  return (uint16_t)((r << 11) | (g << 5) | b);
}

static float wave(uint32_t frame, float speed, float phase = 0.0f)
{
  return sinf((float)frame * speed * MOTION + phase);
}

struct EyePose
{
  int cx, cy;
  int w, h;
  float tilt;
  uint16_t color;
  int topSlope;
};

static void fillPill(GFXcanvas16 &g, int cx, int cy, int w, int h, float tiltDeg, uint16_t color)
{
  if (w < 4)
    w = 4;
  if (h < 2)
    h = 2;

  int halfW = w / 2;
  int radius = min(halfW, max(2, h / 3));
  int straightHalf = max(0, h / 2 - radius);
  int top = cy - h / 2;
  float tangent = tanf(tiltDeg * (float)PI / 180.0f);

  for (int row = 0; row < h; row++)
  {
    float centeredY = (float)row - (float)(h - 1) * 0.5f;
    float dy = fabsf(centeredY);
    int rowHalfW = halfW;

    if (dy > straightHalf)
    {
      float k = dy - (float)straightHalf;
      float dx = sqrtf(max(0.0f, (float)(radius * radius) - k * k));
      rowHalfW = max(1, halfW - radius + (int)roundf(dx));
    }

    int shiftX = (int)roundf(centeredY * tangent);
    g.drawFastHLine(cx + shiftX - rowHalfW, top + row, rowHalfW * 2 + 1, color);
  }
}

static const int GLOW_OUTER = 14;
static const int GLOW_INNER = 6;

static void drawEye(GFXcanvas16 &g, const EyePose &e, uint8_t blinkOpen)
{
  int h = max(4, e.h * (int)blinkOpen / 100);
  int w = max(8, e.w);

  fillPill(g, e.cx, e.cy, w + GLOW_OUTER, h + GLOW_OUTER, e.tilt, scaleColor(e.color, 13));
  fillPill(g, e.cx, e.cy, w + GLOW_INNER, h + GLOW_INNER, e.tilt, scaleColor(e.color, 32));
  fillPill(g, e.cx, e.cy, w, h, e.tilt, e.color);

  int slope = e.topSlope * (int)blinkOpen / 100;
  if (slope != 0)
  {
    int pad = GLOW_OUTER / 2;
    int glowTop = e.cy - (h + GLOW_OUTER) / 2;
    int left = e.cx - (w + GLOW_OUTER) / 2 - 6;
    int right = e.cx + (w + GLOW_OUTER) / 2 + 6;
    if (slope > 0)
      g.fillTriangle(left, glowTop, right, glowTop, right, glowTop + pad + slope, COLOR_BG);
    else
      g.fillTriangle(left, glowTop, right, glowTop, left, glowTop + pad - slope, COLOR_BG);
  }
}

static void drawArc(GFXcanvas16 &g, int cx, int cy, bool mirror,
                    int halfW, int rise, int thick, uint16_t color)
{
  for (int dx = -halfW; dx <= halfW; dx++)
  {
    int lean = (mirror ? -dx : dx) / 10;
    int y = cy - rise / 2 + (dx * dx * rise) / (halfW * halfW) + lean;
    g.drawFastVLine(cx + dx, y - thick / 2, thick, color);
  }
}

static void drawArcEye(GFXcanvas16 &g, int cx, int cy, bool mirror, uint16_t color)
{
  drawArc(g, cx, cy, mirror, 36, 24, 22, scaleColor(color, 20));
  drawArc(g, cx, cy, mirror, 32, 22, 13, color);
}

static void drawThickLine(GFXcanvas16 &g, int x0, int y0, int x1, int y1, int r, uint16_t color)
{
  int steps = max(abs(x1 - x0), abs(y1 - y0));
  if (steps == 0)
  {
    g.fillCircle(x0, y0, r, color);
    return;
  }
  for (int i = 0; i <= steps; i += 2)
  {
    g.fillCircle(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, r, color);
  }
  g.fillCircle(x1, y1, r, color);
}

static void drawSpinningX(GFXcanvas16 &g, int cx, int cy, int arm, float angle, uint16_t color)
{
  float c = cosf(angle), s = sinf(angle);
  int x1 = cx + (int)roundf((-arm) * c - (-arm) * s);
  int y1 = cy + (int)roundf((-arm) * s + (-arm) * c);
  int x2 = cx + (int)roundf(arm * c - arm * s);
  int y2 = cy + (int)roundf(arm * s + arm * c);
  int x3 = cx + (int)roundf((-arm) * c - arm * s);
  int y3 = cy + (int)roundf((-arm) * s + arm * c);
  int x4 = cx + (int)roundf(arm * c - (-arm) * s);
  int y4 = cy + (int)roundf(arm * s + (-arm) * c);
  drawThickLine(g, x1, y1, x2, y2, 5, color);
  drawThickLine(g, x3, y3, x4, y4, 5, color);
}

static void drawHeart(GFXcanvas16 &g, int cx, int cy, int size, uint16_t color)
{
  int radius = max(6, size / 4);
  int lobe = max(5, size / 5);
  int lobeY = cy - size / 7;
  int halfW = size / 2;
  g.fillCircle(cx - lobe, lobeY, radius, color);
  g.fillCircle(cx + lobe, lobeY, radius, color);
  g.fillTriangle(cx - halfW, lobeY, cx + halfW, lobeY, cx, cy + size / 2, color);
}

static void drawSparkle(GFXcanvas16 &g, int cx, int cy, int size, uint16_t color)
{
  if (size < 1)
    return;
  g.drawFastHLine(cx - size, cy, size * 2 + 1, color);
  g.drawFastVLine(cx, cy - size, size * 2 + 1, color);
  if (size >= 4)
  {
    g.drawFastHLine(cx - size / 2, cy - 1, size + 1, color);
    g.drawFastHLine(cx - size / 2, cy + 1, size + 1, color);
    g.drawFastVLine(cx - 1, cy - size / 2, size + 1, color);
    g.drawFastVLine(cx + 1, cy - size / 2, size + 1, color);
  }
}

static void drawTear(GFXcanvas16 &g, int cx, int cy, int size, uint16_t color)
{
  if (size < 1)
    return;
  g.fillCircle(cx, cy, size, color);
  g.fillTriangle(cx - size, cy - 1, cx + size, cy - 1, cx, cy - size * 2 - 1, color);
}

static void faceNeutral(GFXcanvas16 &g, uint32_t f, uint8_t open, int moveX, int moveY)
{
  int breatheY = (int)roundf(wave(f, 0.055f) * 2.0f);
  int breatheH = (int)roundf(wave(f, 0.055f, 1.2f) * 3.0f);
  EyePose l = {EYE_LX + moveX, FACE_CY + moveY + breatheY, 58, 84 + breatheH, 0.0f, COLOR_CYAN, 0};
  EyePose r = {EYE_RX + moveX, FACE_CY + moveY + breatheY, 58, 84 + breatheH, 0.0f, COLOR_CYAN, 0};
  drawEye(g, l, open);
  drawEye(g, r, open);
}

static void faceHappy(GFXcanvas16 &g, uint32_t f)
{
  int bounce = (int)roundf(wave(f, 0.10f) * 3.0f);
  drawArcEye(g, EYE_LX, FACE_CY + bounce, false, COLOR_CYAN);
  drawArcEye(g, EYE_RX, FACE_CY + bounce, true, COLOR_CYAN);
}

static void faceSad(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  int sink = 8 + (int)roundf(wave(f, 0.045f) * 2.0f);
  EyePose l = {EYE_LX, FACE_CY + sink, 56, 60, 0.0f, COLOR_RED, -20};
  EyePose r = {EYE_RX, FACE_CY + sink, 56, 60, 0.0f, COLOR_RED, 20};
  drawEye(g, l, open);
  drawEye(g, r, open);

  const uint32_t TEAR_FRAMES = 75;
  float t = (float)(f % TEAR_FRAMES) / (float)TEAR_FRAMES;
  int ty = FACE_CY + 2 + (int)(t * 54.0f);
  int size = max(1, (int)roundf(5.0f * (1.0f - t)));
  drawTear(g, EYE_LX - 44, ty, size, scaleColor(COLOR_CYAN, (uint8_t)(60 + 40 * (1.0f - t))));
}

static void faceAngry(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  int shake = (int)((f / 2) % 3) - 1;
  EyePose l = {EYE_LX + shake, FACE_CY + 8, 60, 56, 0.0f, COLOR_TEAL, 22};
  EyePose r = {EYE_RX + shake, FACE_CY + 8, 60, 56, 0.0f, COLOR_TEAL, -22};
  uint8_t o = (uint8_t)min((int)open, 88);
  drawEye(g, l, o);
  drawEye(g, r, o);
}

static void faceSurprised(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  int pulse = (int)roundf((wave(f, 0.09f) + 1.0f) * 3.0f);
  EyePose l = {EYE_LX, FACE_CY - 2, 68 + pulse, 90 + pulse, 0.0f, COLOR_ORANGE, 0};
  EyePose r = {EYE_RX, FACE_CY - 2, 68 + pulse, 90 + pulse, 0.0f, COLOR_ORANGE, 0};
  drawEye(g, l, open);
  drawEye(g, r, open);
}

static void faceWink(GFXcanvas16 &g, uint32_t f)
{
  int bounce = (int)roundf(wave(f, 0.09f) * 2.0f);
  drawArcEye(g, EYE_LX, FACE_CY - 4 + bounce, false, COLOR_CYAN);
  EyePose r = {EYE_RX, FACE_CY + 14 + bounce, 56, 11, 8.0f, COLOR_CYAN, 0};
  drawEye(g, r, 100);
}

static void faceSleepy(GFXcanvas16 &g, uint32_t f)
{
  int drift = 14 + (int)roundf(wave(f, 0.045f) * 4.0f);
  EyePose l = {EYE_LX, FACE_CY + drift, 58, 12, -3.0f, COLOR_PURPLE, 0};
  EyePose r = {EYE_RX, FACE_CY + drift, 58, 12, 3.0f, COLOR_PURPLE, 0};
  drawEye(g, l, 100);
  drawEye(g, r, 100);

  g.setTextWrap(false);
  for (int i = 0; i < 3; i++)
  {
    const uint32_t PERIOD = 96;
    float t = (float)((f + (uint32_t)i * 32) % PERIOD) / (float)PERIOD;
    int size = 1 + (int)(t * 2.0f);
    g.setTextSize(size);
    g.setTextColor(scaleColor(COLOR_PURPLE, (uint8_t)(100 - t * 72)));
    g.setCursor(FACE_CX + 56 + i * 7, FACE_CY - 20 - (int)(t * 42.0f));
    g.print("z");
  }
}

static void faceLove(GFXcanvas16 &g, uint32_t f)
{
  float w = wave(f, 0.16f);
  float beat = (w + 1.0f) * 0.5f;
  int grow = (int)roundf(beat * 10.0f);
  int lift = (int)roundf(fabsf(w) * -5.0f);
  int inward = (int)roundf(beat * 4.0f);
  int size = 58 + grow;

  drawHeart(g, EYE_LX + inward, FACE_CY + lift, size + 10, scaleColor(COLOR_PINK, 22));
  drawHeart(g, EYE_RX - inward, FACE_CY + lift, size + 10, scaleColor(COLOR_PINK, 22));
  drawHeart(g, EYE_LX + inward, FACE_CY + lift, size, COLOR_PINK);
  drawHeart(g, EYE_RX - inward, FACE_CY + lift, size, COLOR_PINK);
}

static void faceCool(GFXcanvas16 &g, uint32_t f)
{
  int bob = (int)roundf(wave(f, 0.09f) * 3.0f);
  int swagger = (int)roundf(wave(f, 0.045f, (float)PI / 2.0f) * 6.0f);
  const int lensW = 78, lensH = 54, radius = 11;
  int leftX = EYE_LX + swagger - lensW / 2;
  int rightX = EYE_RX + swagger - lensW / 2;
  int top = FACE_CY - lensH / 2 + bob;

  g.fillRoundRect(leftX, top, lensW, lensH, radius, COLOR_CYAN);
  g.fillRoundRect(rightX, top, lensW, lensH, radius, COLOR_CYAN);
  g.fillRoundRect(leftX + 5, top + 5, lensW - 10, lensH - 10, radius - 3, COLOR_DARK_GRAY);
  g.fillRoundRect(rightX + 5, top + 5, lensW - 10, lensH - 10, radius - 3, COLOR_DARK_GRAY);
  g.fillRect(leftX + lensW - 1, top + 16, rightX - leftX - lensW + 2, 8, COLOR_CYAN);
  g.fillRect(leftX - 9, top + 10, 10, 7, COLOR_CYAN);
  g.fillRect(rightX + lensW - 1, top + 10, 10, 7, COLOR_CYAN);

  const uint32_t SHINE_PERIOD = 110;
  uint32_t phase = f % SHINE_PERIOD;
  if (phase < SHINE_PERIOD * 35 / 100)
  {
    float t = (float)phase / (float)(SHINE_PERIOD * 35 / 100);
    int inset = 8;
    int span = lensW - inset * 2 - 10;
    int off = inset + (int)(t * span);
    for (int lens = 0; lens < 2; lens++)
    {
      int baseX = (lens == 0 ? leftX : rightX) + off;
      drawThickLine(g, baseX, top + inset, baseX - 10, top + lensH - inset, 3,
                    scaleColor(COLOR_WHITE, 55));
    }
  }
}

static void faceCute(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  float pulse = wave(f, 0.085f);
  int delta = (int)roundf(pulse * 11.0f);
  int bounce = (int)roundf(fabsf(wave(f, 0.15f)) * -7.0f);
  int sway = (int)roundf(wave(f, 0.07f) * 5.0f);

  EyePose l = {EYE_LX + 5 + sway, FACE_CY - 4 + bounce, 62 + delta / 2, 84 + delta,
               -8.0f, COLOR_CUTE_PINK, 0};
  EyePose r = {EYE_RX - 5 + sway, FACE_CY + 3 + bounce, 56 - delta / 2, 70 - delta,
               8.0f, COLOR_CUTE_PINK, 0};
  drawEye(g, l, open);
  drawEye(g, r, open);

  static const int SPARKLE_X[4] = {18, 222, 40, 204};
  static const int SPARKLE_Y[4] = {24, 30, 104, 98};
  for (int i = 0; i < 4; i++)
  {
    float s = wave(f, 0.13f, (float)i * 1.6f);
    int size = (int)roundf((s + 1.0f) * 3.5f);
    drawSparkle(g, SPARKLE_X[i], SPARKLE_Y[i], size, scaleColor(COLOR_WHITE, 75));
  }
}

static void faceDizzy(GFXcanvas16 &g, uint32_t f)
{
  float angle = (float)f * 0.075f * MOTION;
  int wobble = (int)roundf(wave(f, 0.12f) * 4.0f);
  drawSpinningX(g, EYE_LX, FACE_CY + wobble, 22, angle, COLOR_YELLOW);
  drawSpinningX(g, EYE_RX, FACE_CY - wobble, 22, -angle, COLOR_YELLOW);
}

static void faceQuestioning(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  float curiosity = wave(f, 0.085f);
  int lh = 56 + (int)roundf(curiosity * 30.0f);
  int rh = 56 - (int)roundf(curiosity * 30.0f);
  int moveX = (int)roundf(wave(f, 0.055f) * 8.0f);
  int moveY = -2 + (int)roundf(wave(f, 0.10f) * 4.0f);

  EyePose l = {EYE_LX + moveX, FACE_CY + moveY, 58, lh, -9.0f, COLOR_CYAN, 0};
  EyePose r = {EYE_RX + moveX, FACE_CY + moveY, 58, rh, 9.0f, COLOR_CYAN, 0};
  drawEye(g, l, open);
  drawEye(g, r, open);
}

static void faceHearing(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  float focus = (wave(f, 0.14f) + 1.0f) * 0.5f;
  int grow = (int)roundf(focus * 8.0f);
  int bob = (int)roundf(wave(f, 0.17f, (float)PI / 2.0f) * 4.0f);

  EyePose l = {EYE_LX + 2, FACE_CY + 6 + bob, 64 + grow, 84 + grow, 0.0f, COLOR_GREEN, 0};
  EyePose r = {EYE_RX - 2, FACE_CY + 6 + bob, 64 + grow, 84 + grow, 0.0f, COLOR_GREEN, 0};
  drawEye(g, l, open);
  drawEye(g, r, open);

  g.setTextWrap(false);
  g.setTextSize(3);
  g.setTextColor(COLOR_GREEN);
  g.setCursor(FACE_CX - 8, 5 + (int)roundf(wave(f, 0.17f) * 3.0f));
  g.print("?");
}

static void faceThinking(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  float angle = (float)f * 0.07f * MOTION;
  int orbitX = (int)roundf(cosf(angle) * 46.0f);
  int orbitY = (int)roundf(sinf(angle) * 26.0f);
  int pulse = (int)roundf(sinf(angle * 2.0f) * 5.0f);

  EyePose l = {FACE_CX - orbitX, FACE_CY - orbitY, 42 + pulse, 48 - pulse,
               cosf(angle) * 18.0f, COLOR_PURPLE, 0};
  EyePose r = {FACE_CX + orbitX, FACE_CY + orbitY, 42 - pulse, 48 + pulse,
               -cosf(angle) * 18.0f, COLOR_PURPLE, 0};
  uint8_t o = (uint8_t)min((int)open, 92);
  drawEye(g, l, o);
  drawEye(g, r, o);
}

static void faceSpeaking(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  float voice = 0.65f * fabsf(wave(f, 0.28f)) + 0.35f * fabsf(wave(f, 0.48f, 0.7f));
  int h = 26 + (int)roundf(voice * 56.0f);
  int w = 62 - (int)roundf(voice * 6.0f);
  int y = FACE_CY + 10 - (int)roundf(voice * 14.0f);
  float tilt = 4.0f + voice * 5.0f;

  EyePose l = {EYE_LX, y, w, h, -tilt, COLOR_CYAN, 0};
  EyePose r = {EYE_RX, y, w, h, tilt, COLOR_CYAN, 0};
  drawEye(g, l, open);
  drawEye(g, r, open);
}

static bool supportsBlink(const String &m)
{
  return m != "happy" && m != "wink" && m != "sleepy" && m != "love" &&
         m != "cool" && m != "dizzy";
}

static void updateBlink(unsigned long now)
{
  if (!supportsBlink(currentExpression))
  {
    blinking = false;
    eyeOpen = 100;
    return;
  }

  if (!blinking && now - lastBlinkMs >= nextBlinkGapMs)
  {
    blinking = true;
    blinkStartMs = now;
    lastBlinkMs = now;
    nextBlinkGapMs = random(2600, 5600);
  }

  if (!blinking)
    return;

  unsigned long elapsed = now - blinkStartMs;
  if (elapsed >= BLINK_TOTAL_MS)
  {
    blinking = false;
    eyeOpen = 100;
    return;
  }

  const int travel = 100 - MIN_EYE_OPEN;
  if (elapsed < BLINK_CLOSE_MS)
    eyeOpen = (uint8_t)(100 - (elapsed * travel / BLINK_CLOSE_MS));
  else if (elapsed < BLINK_CLOSE_MS + BLINK_HOLD_MS)
    eyeOpen = (uint8_t)MIN_EYE_OPEN;
  else
    eyeOpen = (uint8_t)(MIN_EYE_OPEN +
                        (elapsed - BLINK_CLOSE_MS - BLINK_HOLD_MS) * travel / BLINK_OPEN_MS);
}

static void renderFace()
{
  GFXcanvas16 &g = faceCanvas;
  const String &m = currentExpression;
  uint32_t f = animFrame;

  g.fillScreen(COLOR_BG);

  if (m == "happy")
    faceHappy(g, f);
  else if (m == "sad")
    faceSad(g, f, eyeOpen);
  else if (m == "angry")
    faceAngry(g, f, eyeOpen);
  else if (m == "surprised")
    faceSurprised(g, f, eyeOpen);
  else if (m == "wink")
    faceWink(g, f);
  else if (m == "sleepy")
    faceSleepy(g, f);
  else if (m == "love")
    faceLove(g, f);
  else if (m == "cool")
    faceCool(g, f);
  else if (m == "cute")
    faceCute(g, f, eyeOpen);
  else if (m == "dizzy")
    faceDizzy(g, f);
  else if (m == "questioning")
    faceQuestioning(g, f, eyeOpen);
  else if (m == "hearing")
    faceHearing(g, f, eyeOpen);
  else if (m == "thinking")
    faceThinking(g, f, eyeOpen);
  else if (m == "speaking")
    faceSpeaking(g, f, eyeOpen);
  else
    faceNeutral(g, f, eyeOpen, 0, 0);

  tft.drawRGBBitmap(CANVAS_X, CANVAS_Y, g.getBuffer(), CANVAS_W, CANVAS_H);
}

// ---------------------------------------------------------------------------
// Phần mới cho cam-emotion: API cho main.cpp gọi + dải chữ chú thích dưới mặt.
// Không in Serial ở file này: dây Serial đang chở ảnh camera, log lung tung vào giữa sẽ
// cắt đôi 1 khung ảnh — main.cpp tự lo log có khoá.
// ---------------------------------------------------------------------------
#define CAPTION_Y 196

bool faceBegin()
{
  SPI.begin(TFT_SCK, -1, TFT_MOSI, TFT_CS);
  tft.begin(20000000);
  tft.setRotation(1);
  tft.fillScreen(COLOR_BG);
  tft.setTextWrap(false);

  tft.setTextSize(2);
  tft.setTextColor(scaleColor(COLOR_WHITE, 60));
  tft.setCursor(10, 12);
  tft.print("PANDA - cam xuc");

  lastBlinkMs = millis();
  return faceCanvas.getBuffer() != nullptr;
}

void faceSetExpression(const char *expression)
{
  if (currentExpression == expression)
  {
    return; // AI gửi lại cùng cảm xúc liên tục — đừng reset hoạt ảnh, mặt sẽ giật
  }
  currentExpression = expression;
  animFrame = 0;
  blinking = false;
  eyeOpen = 100;
  lastBlinkMs = millis();
}

void faceSetCaption(const char *text)
{
  static String last;
  if (last == text)
  {
    return; // chữ tĩnh: chỉ vẽ lại khi đổi, giống cách firmware-demo vẽ điểm số
  }
  last = text;
  tft.fillRect(0, CAPTION_Y, SCREEN_WIDTH, SCREEN_HEIGHT - CAPTION_Y, COLOR_BG);
  tft.setTextSize(3);
  tft.setTextColor(COLOR_WHITE);
  int w = (int)strlen(text) * 18; // font mặc định: 6px/ký tự × cỡ 3
  tft.setCursor(max(4, (SCREEN_WIDTH - w) / 2), CAPTION_Y + 10);
  tft.print(text);
}

void faceTick()
{
  if (faceCanvas.getBuffer() == nullptr)
  {
    return;
  }
  unsigned long nowUs = micros();
  if (nowUs - lastFrameUs < FRAME_US)
  {
    return;
  }
  lastFrameUs = nowUs;
  updateBlink(millis());
  animFrame++;
  renderFace();
}
