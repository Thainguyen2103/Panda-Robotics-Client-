// ===========================================================================
//  display.cpp — vẽ khuôn mặt robot lên màn TFT ILI9341 2.4" (320x240, SPI).
//
//  VÌ SAO ĐỔI TỪ OLED SSD1306 (I2C) SANG TFT ILI9341 (SPI)? — xem WEEKLY_LOGIC.md.
//  3 điểm KỸ THUẬT quan trọng nhất khi viết firmware cho nó:
//
//  1) SPI ở đây chạy 40MHz trên chân VSPI phần cứng, tức nhanh gấp ~100 lần so với I2C
//     400kHz của OLED cũ. Nhờ vậy mới đủ băng thông cho animation liên tục — chính là
//     thứ đã gây bug "giật lag, bấm nút không ăn" hồi còn dùng I2C.
//
//  2) KHÔNG vẽ trực tiếp từng hình lên màn. Mỗi lệnh vẽ thẳng lên màn là một lượt truyền
//     SPI riêng, và người xem sẽ thấy hình NHẤP NHÁY vì màn bị xoá rồi mới vẽ lại từng
//     phần. Thay vào đó: vẽ vào một vùng nhớ RAM (GFXcanvas16 — "tờ giấy nháp" 16 bit
//     màu), vẽ xong xuôi mới bắn NGUYÊN KHỐI lên màn bằng drawRGBBitmap(). Kết quả:
//     không nháy, và mỗi khung hình chỉ tốn đúng 1 lượt truyền SPI.
//
//  3) Canvas chỉ bao vùng MẮT (240x130 = 62KB RAM), không phải cả màn 320x240 (150KB).
//     ESP32 chỉ có ~320KB RAM và còn phải chừa cho WiFi/MQTT, nên ôm cả màn là quá tay.
//     Phần chữ tĩnh (từ vựng, điểm số) nằm NGOÀI canvas và chỉ vẽ lại khi số liệu đổi.
//
//  Về mặt hình ảnh: giữ nguyên tên biểu cảm + bảng màu của dashboard web bạn AI làm
//  (xem ai.md), để khi ghép MQTT thật (panda/cmd/face) thì robot và dashboard "nói cùng
//  một ngôn ngữ hình ảnh", không phải mỗi bên một kiểu.
// ===========================================================================
#include "display.h"
#include "pins.h"
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <math.h>

// --------------------------------------------------------------------------
// Bảng màu RGB565 (16 bit: 5 đỏ - 6 lục - 5 lam), copy đúng theo dashboard web.
// --------------------------------------------------------------------------
#define COLOR_BG 0x0823        // #080c18 navy rất tối, gần đen
#define COLOR_CYAN 0x067F      // #00d2ff màu chủ đạo của mắt
#define COLOR_GREEN 0x2EB6     // #2ed573 điểm đúng
#define COLOR_RED 0xF9C7       // #ff3838 điểm sai / buồn
#define COLOR_ORANGE 0xFD40    // #ffaa00 ngạc nhiên
#define COLOR_PURPLE 0xA4DF    // #a29bfe buồn ngủ / suy nghĩ
#define COLOR_PINK 0xF9B0      // #ff3385 tim (love)
#define COLOR_CUTE_PINK 0xFBAC // #ff7675 dễ thương
#define COLOR_YELLOW 0xFE75    // #fdcb6e sao quay (dizzy)
#define COLOR_TEAL 0x0455      // #0088aa tức giận
#define COLOR_WHITE 0xFFFF
#define COLOR_DARK_GRAY 0x18E3 // tròng kính râm

// --------------------------------------------------------------------------
// Hình học: canvas nằm giữa màn, chừa dải chữ phía trên và phía dưới.
// --------------------------------------------------------------------------
#define CANVAS_W 240
#define CANVAS_H 130
#define CANVAS_X ((SCREEN_WIDTH - CANVAS_W) / 2) // = 40
#define CANVAS_Y 56

static Adafruit_ILI9341 tft(TFT_CS, TFT_DC, TFT_RST);
static GFXcanvas16 faceCanvas(CANVAS_W, CANVAS_H);

static const int FACE_CX = CANVAS_W / 2; // 120 — tâm khuôn mặt trong hệ toạ độ canvas
static const int FACE_CY = CANVAS_H / 2; // 65
static const int EYE_LX = FACE_CX - 56;  // tâm mắt trái
static const int EYE_RX = FACE_CX + 56;  // tâm mắt phải

// ~33 khung/giây. Chỉnh số này nếu thấy Wokwi chạy nặng (tăng lên) hoặc muốn mượt hơn
// trên phần cứng thật (giảm xuống, tối đa hợp lý là 16667 = 60fps).
static const unsigned long FRAME_US = 30000UL;

// Hệ số tốc độ chung cho mọi chuyển động — chỉnh 1 số này là nhanh/chậm cả khuôn mặt.
static const float MOTION = 1.75f;

// Nháy mắt: đóng nhanh, giữ một nhịp, mở chậm hơn — đây là điều làm nó giống mắt thật
// thay vì chớp cứng như đèn nhấp nháy.
static const unsigned long BLINK_CLOSE_MS = 70;
static const unsigned long BLINK_HOLD_MS = 60;
static const unsigned long BLINK_OPEN_MS = 110;
static const unsigned long BLINK_TOTAL_MS = BLINK_CLOSE_MS + BLINK_HOLD_MS + BLINK_OPEN_MS;
static const int MIN_EYE_OPEN = 4; // % chiều cao còn lại lúc nhắm sâu nhất

// --------------------------------------------------------------------------
// Trạng thái
// --------------------------------------------------------------------------
static String currentExpression = "neutral";
static String currentWord = "";
static int currentCorrect = 0;
static int currentWrong = 0;

static uint32_t animFrame = 0;
static unsigned long lastFrameUs = 0;
static unsigned long lastBlinkMs = 0;
static unsigned long blinkStartMs = 0;
static unsigned long nextBlinkGapMs = 3000;
static bool blinking = false;
static uint8_t eyeOpen = 100;

// --------------------------------------------------------------------------
// Tiện ích nhỏ
// --------------------------------------------------------------------------

// Giảm độ sáng một màu RGB565 xuống còn `percent`% — dùng để vẽ "quầng sáng neon"
// mờ phía sau mắt. Phải tách riêng 3 kênh màu rồi nhân, không nhân thẳng cả số 16 bit
// (nhân thẳng sẽ làm tràn kênh này sang kênh kia và ra màu sai bét).
static uint16_t scaleColor(uint16_t c, uint8_t percent)
{
  uint16_t r = (((c >> 11) & 0x1F) * percent) / 100;
  uint16_t g = (((c >> 5) & 0x3F) * percent) / 100;
  uint16_t b = ((c & 0x1F) * percent) / 100;
  return (uint16_t)((r << 11) | (g << 5) | b);
}

// Sóng sin theo số thứ tự khung hình. Dùng khung hình (không dùng millis) để mỗi lần
// đổi biểu cảm, animation bắt đầu lại sạch sẽ từ đầu thay vì nhảy vào giữa chừng.
static float wave(uint32_t frame, float speed, float phase = 0.0f)
{
  return sinf((float)frame * speed * MOTION + phase);
}

struct EyePose
{
  int cx, cy;      // tâm mắt (toạ độ canvas)
  int w, h;        // bề ngang / chiều cao
  float tilt;      // độ nghiêng, đơn vị độ (âm = đổ về bên trái)
  uint16_t color;  //
  int topSlope;    // cắt vát mí trên: >0 vát sâu dần về bên PHẢI, <0 về bên TRÁI
};

// Vẽ một "viên thuốc" (hình chữ nhật bo tròn 2 đầu) có thể nghiêng.
// Adafruit_GFX không xoay hình được, nên tự vẽ từng DÒNG NGANG một: mỗi dòng tính bề
// rộng riêng (bo tròn ở 2 đầu) rồi đẩy ngang theo tan(góc) để tạo cảm giác nghiêng.
static void fillPill(GFXcanvas16 &g, int cx, int cy, int w, int h, float tiltDeg, uint16_t color)
{
  if (w < 4)
    w = 4;
  if (h < 2)
    h = 2;

  int halfW = w / 2;
  int radius = min(halfW, max(2, h / 3));
  int straightHalf = max(0, h / 2 - radius); // đoạn thân thẳng ở giữa, chưa bo
  int top = cy - h / 2;
  float tangent = tanf(tiltDeg * (float)PI / 180.0f);

  for (int row = 0; row < h; row++)
  {
    float centeredY = (float)row - (float)(h - 1) * 0.5f;
    float dy = fabsf(centeredY);
    int rowHalfW = halfW;

    if (dy > straightHalf)
    {
      // Đang ở vùng bo tròn: bề rộng dòng này thu lại theo phương trình đường tròn.
      float k = dy - (float)straightHalf;
      float dx = sqrtf(max(0.0f, (float)(radius * radius) - k * k));
      rowHalfW = max(1, halfW - radius + (int)roundf(dx));
    }

    int shiftX = (int)roundf(centeredY * tangent);
    g.drawFastHLine(cx + shiftX - rowHalfW, top + row, rowHalfW * 2 + 1, color);
  }
}

static const int GLOW_OUTER = 14; // tổng bề dày quầng sáng ngoài (cộng vào cả w và h)
static const int GLOW_INNER = 6;

// Vẽ 1 con mắt hoàn chỉnh: 2 lớp quầng sáng mờ dần + mắt đặc + cắt vát mí trên.
// Quầng sáng chính là thứ thay cho `box-shadow` phát sáng của bản CSS trên web — màn
// OLED trắng đen cũ không làm nổi, còn TFT 65 nghìn màu thì thừa sức.
static void drawEye(GFXcanvas16 &g, const EyePose &e, uint8_t blinkOpen)
{
  int h = max(4, e.h * (int)blinkOpen / 100);
  int w = max(8, e.w);

  fillPill(g, e.cx, e.cy, w + GLOW_OUTER, h + GLOW_OUTER, e.tilt, scaleColor(e.color, 13));
  fillPill(g, e.cx, e.cy, w + GLOW_INNER, h + GLOW_INNER, e.tilt, scaleColor(e.color, 32));
  fillPill(g, e.cx, e.cy, w, h, e.tilt, e.color);

  // Vát mí trên tạo cảm xúc (giận: vát vào trong; buồn: vát ra ngoài) mà không cần vẽ
  // lông mày riêng. Cắt bằng chính màu nền, nên phải cắt rộng hơn để xoá luôn quầng sáng.
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

// Vẽ cung "^" (mắt cười) bằng NHIỀU CỘT DỌC sát nhau thay vì chồng nhiều hình tròn.
// Cách này rẻ hơn hàng chục lần về số điểm ảnh phải ghi — quan trọng vì mỗi khung hình
// chỉ có ~30ms, ghi thừa là tụt khung hình ngay.
static void drawArc(GFXcanvas16 &g, int cx, int cy, bool mirror,
                    int halfW, int rise, int thick, uint16_t color)
{
  for (int dx = -halfW; dx <= halfW; dx++)
  {
    int lean = (mirror ? -dx : dx) / 10; // lệch nhẹ cho 2 mắt không đối xứng cứng nhắc
    int y = cy - rise / 2 + (dx * dx * rise) / (halfW * halfW) + lean;
    g.drawFastVLine(cx + dx, y - thick / 2, thick, color);
  }
}

static void drawArcEye(GFXcanvas16 &g, int cx, int cy, bool mirror, uint16_t color)
{
  drawArc(g, cx, cy, mirror, 36, 24, 22, scaleColor(color, 20));
  drawArc(g, cx, cy, mirror, 32, 22, 13, color);
}

// Đường thẳng "dày" = chuỗi hình tròn nhỏ nối nhau. Bước nhảy 2 điểm ảnh cho nhẹ; các
// hình tròn vẫn chồng lên nhau nên nét liền, không bị đứt.
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

// Dấu "X" xoay quanh tâm — dùng cho dizzy. Tự tính 4 đầu mút bằng cos/sin theo góc,
// vì Adafruit_GFX không có phép xoay hình như `transform: rotate` bên CSS.
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

// Trái tim = 2 múi tròn phía trên + 1 tam giác nhọn phía dưới.
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

// Ngôi sao 4 cánh mảnh — dùng làm hạt lấp lánh quanh mắt "cute".
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

// Giọt nước mắt = nửa dưới tròn + chóp nhọn phía trên.
static void drawTear(GFXcanvas16 &g, int cx, int cy, int size, uint16_t color)
{
  if (size < 1)
    return;
  g.fillCircle(cx, cy, size, color);
  g.fillTriangle(cx - size, cy - 1, cx + size, cy - 1, cx, cy - size * 2 - 1, color);
}

// --------------------------------------------------------------------------
// Từng biểu cảm. Tất cả đều nhận `f` = số thứ tự khung hình để tự tính chuyển động.
// --------------------------------------------------------------------------

static void faceNeutral(GFXcanvas16 &g, uint32_t f, uint8_t open, int moveX, int moveY)
{
  // "Thở": chiều cao và vị trí mắt nhấp nhô rất nhẹ, lệch pha nhau một chút để trông
  // như đang sống chứ không phải ảnh tĩnh.
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

  // Giọt nước mắt rơi lặp vô hạn: lấy phần dư của bộ đếm khung hình làm "đồng hồ" chạy
  // 0..1 rồi nội suy vị trí + kích thước, nên không cần biến trạng thái riêng nào cả.
  // Đặt lệch hẳn ra mép ngoài mắt trái để giọt nước chảy dọc "gò má", không đè lên mắt.
  const uint32_t TEAR_FRAMES = 75;
  float t = (float)(f % TEAR_FRAMES) / (float)TEAR_FRAMES;
  int ty = FACE_CY + 2 + (int)(t * 54.0f);
  int size = max(1, (int)roundf(5.0f * (1.0f - t)));
  drawTear(g, EYE_LX - 44, ty, size, scaleColor(COLOR_CYAN, (uint8_t)(60 + 40 * (1.0f - t))));
}

static void faceAngry(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  int shake = (int)((f / 2) % 3) - 1; // rung 1 điểm ảnh qua lại
  EyePose l = {EYE_LX + shake, FACE_CY + 8, 60, 56, 0.0f, COLOR_TEAL, 22};
  EyePose r = {EYE_RX + shake, FACE_CY + 8, 60, 56, 0.0f, COLOR_TEAL, -22};
  uint8_t o = (uint8_t)min((int)open, 88); // luôn hơi nheo lại
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

  // 3 chữ "z" bay lên rồi mờ dần, lệch pha nhau -> trông như khói ngủ trong truyện tranh.
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
  float beat = (w + 1.0f) * 0.5f; // 0..1
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
  g.fillRect(leftX + lensW - 1, top + 16, rightX - leftX - lensW + 2, 8, COLOR_CYAN); // gọng giữa
  g.fillRect(leftX - 9, top + 10, 10, 7, COLOR_CYAN);                                 // càng kính trái
  g.fillRect(rightX + lensW - 1, top + 10, 10, 7, COLOR_CYAN);                         // càng kính phải

  // Vệt sáng quét chéo qua mặt kính, chỉ chạy trong ~35% đầu mỗi chu kỳ rồi nghỉ —
  // giống hiệu ứng "loé kính" trong phim, tạo cảm giác chất liệu bóng.
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
  // Hai mắt CỐ TÌNH lệch nhau (to/nhỏ, cao/thấp, nghiêng ngược chiều) — đây là mẹo làm
  // khuôn mặt trông "dễ thương" thay vì đối xứng cứng như robot.
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

  // 4 hạt lấp lánh nhấp nháy lệch pha quanh mặt.
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
  // 2 mắt xoay NGƯỢC chiều nhau và nhấp nhô lệch pha -> cảm giác choáng váng rõ hơn.
  drawSpinningX(g, EYE_LX, FACE_CY + wobble, 22, angle, COLOR_YELLOW);
  drawSpinningX(g, EYE_RX, FACE_CY - wobble, 22, -angle, COLOR_YELLOW);
}

static void faceQuestioning(GFXcanvas16 &g, uint32_t f, uint8_t open)
{
  // Một mắt mở to trong khi mắt kia nheo lại, rồi đổi vai cho nhau — kiểu "nhướn mày".
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
  // Mắt mở rất to + dấu "?" nảy lên xuống: trạng thái "đang chăm chú nghe bạn nói".
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
  // Cặp mắt quay quanh tâm khuôn mặt theo quỹ đạo elip, vừa quay vừa phình/xẹp lệch
  // pha — nhìn là hiểu ngay "đang xử lý", không cần chữ.
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
  // Trộn 2 sóng sin tần số khác nhau -> nhịp "co giãn" không đều, nghe như đang phát âm
  // từng âm tiết, tự nhiên hơn nhiều so với 1 sóng sin đều đặn.
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

// --------------------------------------------------------------------------
// Điều phối
// --------------------------------------------------------------------------

// Chỉ những biểu cảm dùng mắt dạng "viên thuốc" mới nháy mắt được. Cung cười, tim,
// kính râm, dấu X... mà nháy thì trông sai, nên loại ra.
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
    // Khoảng cách giữa 2 lần nháy ngẫu nhiên -> không đều đặn như máy, giống người hơn.
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
  else if (m == "hearing" || m == "listening")
    faceHearing(g, f, eyeOpen);
  else if (m == "thinking" || m == "ai-thinking")
    faceThinking(g, f, eyeOpen);
  else if (m == "speaking")
    faceSpeaking(g, f, eyeOpen);
  else
    faceNeutral(g, f, eyeOpen, 0, 0); // gồm cả "neutral" và mọi tên lạ

  // Một lần truyền SPI duy nhất cho cả khung hình -> không nháy, không xé hình.
  tft.drawRGBBitmap(CANVAS_X, CANVAS_Y, g.getBuffer(), CANVAS_W, CANVAS_H);
}

// Vẽ 2 dải chữ NGOÀI vùng canvas (từ vựng phía trên, điểm số phía dưới). Chỉ gọi khi số
// liệu thay đổi — không vẽ mỗi khung hình, để dành băng thông SPI cho khuôn mặt.
static void drawChrome()
{
  tft.fillRect(0, 0, SCREEN_WIDTH, CANVAS_Y, COLOR_BG);
  tft.fillRect(0, CANVAS_Y + CANVAS_H, SCREEN_WIDTH,
               SCREEN_HEIGHT - (CANVAS_Y + CANVAS_H), COLOR_BG);

  tft.setTextWrap(false);
  if (currentWord.length() > 0)
  {
    tft.setTextSize(3);
    tft.setTextColor(COLOR_WHITE);
    int textW = (int)currentWord.length() * 18; // cỡ chữ 3 => mỗi ký tự rộng 18 điểm ảnh
    tft.setCursor(max(4, (SCREEN_WIDTH - textW) / 2), 13);
    tft.print(currentWord);
  }
  tft.drawFastHLine(70, 46, SCREEN_WIDTH - 140, scaleColor(COLOR_CYAN, 45));

  const int chipW = 128, chipH = 30, chipY = SCREEN_HEIGHT - 38;
  tft.setTextSize(2);

  tft.drawRoundRect(22, chipY, chipW, chipH, 8, COLOR_GREEN);
  tft.setTextColor(COLOR_GREEN);
  tft.setCursor(22 + 17, chipY + 8);
  tft.print("DUNG ");
  tft.print(currentCorrect);

  tft.drawRoundRect(SCREEN_WIDTH - 22 - chipW, chipY, chipW, chipH, 8, COLOR_RED);
  tft.setTextColor(COLOR_RED);
  tft.setCursor(SCREEN_WIDTH - 22 - chipW + 17, chipY + 8);
  tft.print("SAI  ");
  tft.print(currentWrong);
}

// --------------------------------------------------------------------------
// API công khai
// --------------------------------------------------------------------------

void displaySetup()
{
  tft.begin(40000000); // 40MHz — tốc độ SPI mà ILI9341 chạy ổn định
  tft.setRotation(1);  // xoay ngang: 320 rộng x 240 cao
  tft.fillScreen(COLOR_BG);

  // GFXcanvas16 xin ~62KB từ vùng nhớ động lúc khởi động. Nếu ESP32 không còn đủ RAM
  // (thường do WiFi/MQTT đã chiếm), getBuffer() trả về con trỏ rỗng và mọi lệnh vẽ sẽ
  // ghi vào vùng nhớ không hợp lệ -> reset board. Báo rõ ra Serial để còn biết đường lần.
  if (faceCanvas.getBuffer() == nullptr)
  {
    Serial.println("[display] LOI: khong du RAM cho canvas khuon mat");
    tft.setTextColor(COLOR_RED);
    tft.setTextSize(2);
    tft.setCursor(10, 100);
    tft.print("OUT OF RAM");
    return;
  }

  drawChrome();
  lastBlinkMs = millis();
}

void displaySetExpression(const char *expression)
{
  if (currentExpression == expression)
  {
    return; // đang là biểu cảm đó rồi -> đừng reset animation về khung 0 một cách vô ích
  }
  currentExpression = expression;
  animFrame = 0; // mỗi biểu cảm bắt đầu animation từ đầu, không nhảy vào giữa chừng
  blinking = false;
  eyeOpen = 100;
  lastBlinkMs = millis();
  Serial.print("[display] Doi bieu cam -> ");
  Serial.println(currentExpression);
}

void displaySetStats(const char *word, int correctCount, int wrongCount)
{
  currentWord = word;
  currentCorrect = correctCount;
  currentWrong = wrongCount;
  if (faceCanvas.getBuffer() != nullptr)
  {
    drawChrome();
  }
}

void displayLoop()
{
  if (faceCanvas.getBuffer() == nullptr)
  {
    return;
  }

  // Giới hạn tốc độ khung hình bằng micros() thay vì delay(): loop() vẫn chạy tự do để
  // đọc nút bấm và giữ kết nối MQTT giữa 2 khung hình, thay vì đứng hình chờ.
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
