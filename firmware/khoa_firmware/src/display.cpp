// Bộ vẽ biểu cảm OLED — port từ firmware/panda_firmware.ino (bạn AI trong nhóm viết,
// xem ai.md mục 5). Giữ NGUYÊN toạ độ mắt (L/R/Y/W/H) và tên biểu cảm so với bản gốc để
// khi ghép MQTT thật (topic panda/cmd/face) sau này, robot vẽ ra đúng như dashboard/bản
// AI đã thống nhất — không phải "phát minh lại" ngôn ngữ hình ảnh riêng cho firmware-demo.
//
// ANIMATION: bản CSS gốc (Panda-Robotics-Client-/web/public/style.css) dùng @keyframes
// cho 6 biểu cảm: neutral (nháy mắt định kỳ), love (nhịp tim), sleepy (trôi nhẹ),
// cute (phồng nhẹ theo nhịp), dizzy (xoay tròn), questioning (lắc lư). Các biểu cảm còn
// lại (happy/sad/angry/surprised/wink/cool) KHÔNG có animation trong CSS gốc (chỉ tĩnh)
// — file này giữ đúng sự phân chia đó, không tự thêm animation cho chúng.
// OLED không hiểu CSS keyframes, nên "dịch" bằng cách: vẽ lại nhiều lần/giây, mỗi lần
// tính lại vị trí/kích thước bằng sin()/cos() theo mốc thời gian millis() — sin() cho ra
// đúng kiểu chuyển động "chậm dần ở 2 đầu" giống easing của CSS, thay vì nhảy cứng.
#include "display.h"
#include "pins.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <math.h>

static Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

static String currentExpression = "neutral";
static String currentWord = "";
static int currentCorrect = 0;
static int currentWrong = 0;

static unsigned long lastAnimMs = 0;
static const unsigned long ANIM_INTERVAL_MS = 100; // ~10fps, đủ mượt cho OLED, đủ nhẹ cho ESP32

// Toạ độ mắt cố định — KHÔNG đổi số này nếu không có lý do, vì nó là "hợp đồng hình ảnh"
// dùng chung với firmware/panda_firmware.ino của nhóm AI.
static const int EYE_L = 32, EYE_R = 76, EYE_Y = 17, EYE_W = 20, EYE_H = 30;

static void eye(int x, int y, int w, int h)
{
  display.fillRoundRect(x, y, w, h, 7, SSD1306_WHITE);
}

// Vẽ 1 hình "dấu X xoay" tại tâm (cx,cy) với góc hiện tại — dùng cho dizzy. Adafruit_GFX
// không tự xoay hình được (khác CSS `transform: rotate`), nên tự tính 2 đầu mút mỗi đường
// bằng cos()/sin() theo góc để mô phỏng xoay tròn liên tục.
static void drawSpinningX(int cx, int cy, int r, float angle)
{
  int x1 = cx + (int)(r * cosf(angle));
  int y1 = cy + (int)(r * sinf(angle));
  display.drawLine(x1, y1, cx - (x1 - cx), cy - (y1 - cy), SSD1306_WHITE);

  float angle2 = angle + (float)PI / 2.0f;
  int x2 = cx + (int)(r * cosf(angle2));
  int y2 = cy + (int)(r * sinf(angle2));
  display.drawLine(x2, y2, cx - (x2 - cx), cy - (y2 - cy), SSD1306_WHITE);
}

// Vẽ phần MẮT theo biểu cảm hiện tại (không đụng tới chữ trên/dưới).
static void renderEyes()
{
  int L = EYE_L, R = EYE_R, Y = EYE_Y, W = EYE_W, H = EYE_H;
  unsigned long now = millis();

  if (currentExpression == "happy")
  {
    eye(L, Y + 8, W, 16);
    eye(R, Y + 8, W, 16);
  }
  else if (currentExpression == "sad")
  {
    eye(L, Y + 10, W, 18);
    eye(R, Y + 10, W, 18);
    display.drawLine(L, Y + 4, L + W, Y + 10, SSD1306_WHITE);
    display.drawLine(R + W, Y + 4, R, Y + 10, SSD1306_WHITE);
  }
  else if (currentExpression == "angry")
  {
    eye(L, Y, W, H);
    eye(R, Y, W, H);
    display.drawLine(L, Y + 10, L + W, Y + 2, SSD1306_WHITE);
    display.drawLine(R + W, Y + 10, R, Y + 2, SSD1306_WHITE);
  }
  else if (currentExpression == "surprised")
  {
    display.fillCircle(L + 10, 32, 12, SSD1306_WHITE);
    display.fillCircle(R + 10, 32, 12, SSD1306_WHITE);
  }
  else if (currentExpression == "wink")
  {
    eye(L, Y, W, H);
    display.fillRoundRect(R, Y + 14, W, 5, 2, SSD1306_WHITE);
  }
  else if (currentExpression == "cool")
  {
    display.fillRect(L - 2, Y + 8, W + 4, 12, SSD1306_WHITE);
    display.fillRect(R - 2, Y + 8, W + 4, 12, SSD1306_WHITE);
    display.drawLine(L + W, Y + 10, R, Y + 10, SSD1306_WHITE);
  }
  else if (currentExpression == "sleepy")
  {
    // Trôi nhẹ lên/xuống liên tục — bản CSS gốc: "sleepy-drift 3.5s infinite ease-in-out".
    int drift = (int)(3 * sinf(now * (2.0f * (float)PI / 3500.0f)));
    display.fillRoundRect(L, Y + 20 + drift, W, 5, 2, SSD1306_WHITE);
    display.fillRoundRect(R, Y + 20 + drift, W, 5, 2, SSD1306_WHITE);
  }
  else if (currentExpression == "love")
  {
    // Nhịp tim: co giãn ±15% liên tục — bản CSS gốc: "heart-beat 0.85s infinite ease-in-out".
    float scale = 1.0f + 0.15f * sinf(now * (2.0f * (float)PI / 850.0f));
    int rr = (int)(7 * scale);
    int cy = Y + 8;
    display.fillCircle(L + 6, cy, rr, SSD1306_WHITE);
    display.fillCircle(L + 14, cy, rr, SSD1306_WHITE);
    display.fillTriangle(L - 1, Y + 12, L + 21, Y + 12, L + 10, Y + 28, SSD1306_WHITE);
    display.fillCircle(R + 6, cy, rr, SSD1306_WHITE);
    display.fillCircle(R + 14, cy, rr, SSD1306_WHITE);
    display.fillTriangle(R - 1, Y + 12, R + 21, Y + 12, R + 10, Y + 28, SSD1306_WHITE);
  }
  else if (currentExpression == "cute")
  {
    // Phồng to/nhỏ nhẹ liên tục quanh cùng 1 tâm — bản CSS gốc: "cute-glow 2s infinite".
    float scale = 1.0f + 0.08f * sinf(now * (2.0f * (float)PI / 2000.0f));
    int baseW = W + 4, baseH = H + 4;
    int w = (int)(baseW * scale), h = (int)(baseH * scale);
    int offX = (w - baseW) / 2, offY = (h - baseH) / 2;
    eye(L - 2 - offX, Y - 2 - offY, w, h);
    eye(R - 2 - offX, Y - 2 - offY, w, h);
  }
  else if (currentExpression == "dizzy")
  {
    // Xoay tròn liên tục quanh tâm mỗi mắt — bản CSS gốc: "dizzy-wobble" xoay 360 độ.
    float angle = now * (2.0f * (float)PI / 900.0f); // 1 vòng ~0.9s
    drawSpinningX(L + W / 2, Y + H / 2, 10, angle);
    drawSpinningX(R + W / 2, Y + H / 2, 10, angle);
  }
  else if (currentExpression == "questioning")
  {
    // Dấu "?" lắc lư lên xuống nhẹ liên tục — bản CSS gốc: "oled-icon-wobble".
    int bob = (int)(4 * sinf(now * (2.0f * (float)PI / 1400.0f)));
    display.setTextSize(3);
    display.setCursor(56, 20 + bob);
    display.print("?");
  }
  else if (currentExpression == "thinking")
  {
    // 3 chấm tròn, lần lượt "sáng" (fill) mỗi 400ms -> hiệu ứng đang suy nghĩ.
    int phase = (int)((now / 400) % 3);
    for (int i = 0; i < 3; i++)
    {
      if (i == phase)
        display.fillCircle(44 + i * 20, 32, 6, SSD1306_WHITE);
      else
        display.drawCircle(44 + i * 20, 32, 6, SSD1306_WHITE);
    }
  }
  else if (currentExpression == "speaking")
  {
    // 5 cột "equalizer", MỖI CỘT một chu kỳ sin() khác nhau (giống CSS: mỗi bar có
    // animation-duration/delay riêng) -> các cột nhảy lệch pha nhau, trông tự nhiên hơn
    // là công thức đồng bộ cứng.
    static const int PERIOD_MS[5] = {550, 700, 600, 450, 650};
    for (int i = 0; i < 5; i++)
    {
      float t = fabsf(sinf(now * ((float)PI / PERIOD_MS[i])));
      int h = 8 + (int)(28 * t);
      display.fillRect(34 + i * 14, 56 - h, 8, h, SSD1306_WHITE);
    }
  }
  else // "neutral" hoặc tên không nhận diện được -> mắt mặc định, có nháy mắt định kỳ
  {
    // Nháy mắt 2 lần mỗi 4s (mỗi lần ~120ms) để mặt không trông "chết" khi không có sự
    // kiện gì — bản CSS gốc: "idle-breathe 7s infinite" thu mắt còn ~5px rồi mở lại.
    unsigned long t = now % 4000;
    bool blinking = (t < 120) || (t >= 2000 && t < 2120);
    if (blinking)
    {
      eye(L, Y + H / 2 - 2, W, 4);
      eye(R, Y + H / 2 - 2, W, 4);
    }
    else
    {
      eye(L, Y, W, H);
      eye(R, Y, W, H);
    }
  }
}

static void render()
{
  display.clearDisplay();

  if (currentWord.length() > 0)
  {
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println(currentWord);
  }

  renderEyes();

  display.setCursor(0, 55);
  display.setTextSize(1);
  display.print("Dung: ");
  display.print(currentCorrect);
  display.print("  Sai: ");
  display.print(currentWrong);

  display.display();
}

// true cho các biểu cảm KHÔNG có animation ở bản CSS gốc — vẽ 1 lần là đủ, không cần
// displayLoop() vẽ lại liên tục (đỡ tốn thời gian giao tiếp I2C với OLED một cách vô ích).
static bool isStaticExpression(const String &name)
{
  return name == "happy" || name == "sad" || name == "angry" ||
         name == "surprised" || name == "wink" || name == "cool";
}

void displaySetup()
{
  // Wire (I2C) trên ESP32 mặc định chạy 100kHz (Standard Mode) nếu không đổi. Ở tốc độ
  // đó, gửi 1 khung OLED 128x64 (1024 byte) qua display.display() mất ~92ms — VÀ đây là
  // hàm CHẶN (blocking): trong lúc gửi, loop() không đọc được nút bấm/mạng/gì khác.
  // Từ khi có animation liên tục (vd neutral nháy mắt ~10 lần/giây), code gần như lúc nào
  // cũng đang "kẹt" trong display.display(), nên bấm nút hay rơi đúng lúc đang kẹt ->
  // cảm giác "giật lag" và "bấm không ăn". SSD1306 hỗ trợ tốt 400kHz (Fast Mode), giảm
  // thời gian gửi 1 khung xuống còn ~25ms, để lại nhiều thời gian rảnh hơn cho loop() đọc
  // nút bấm giữa 2 lần vẽ.
  Wire.begin();
  Wire.setClock(400000);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDRESS))
  {
    Serial.println("[display] Khong tim thay man hinh OLED");
  }
}

void displaySetExpression(const char *expression)
{
  currentExpression = expression;
  Serial.print("[display] Doi bieu cam -> ");
  Serial.println(currentExpression);
  render();
}

void displaySetStats(const char *word, int correctCount, int wrongCount)
{
  currentWord = word;
  currentCorrect = correctCount;
  currentWrong = wrongCount;
  render();
}

void displayLoop()
{
  if (isStaticExpression(currentExpression))
  {
    return;
  }

  unsigned long now = millis();
  if (now - lastAnimMs < ANIM_INTERVAL_MS)
  {
    return;
  }
  lastAnimMs = now;
  render();
}
