#include <Arduino.h>
#include "pins.h"
#include "display.h"
#include "input.h"
#include "network.h"
#include "audio_i2s.h"

// main.cpp giờ chỉ còn vai trò "nhạc trưởng": setup()/loop() gọi các module, không tự
// đụng vào chi tiết OLED/WiFi/MQTT/nút bấm nữa (những phần đó đã chuyển sang display.*,
// network.*, input.*). Xem WEEKLY_LOGIC.md để hiểu lý do tách module theo cách này.

const char *TOPIC_RESULT = "panda/demo/khoa/result";
const char *TOPIC_PROGRESS = "panda/demo/khoa/progress";
const char *DEMO_WORD = "hello";

static int correctCount = 0;
static int wrongCount = 0;

static void publishResult(const char *result)
{
  char payload[128];
  snprintf(payload, sizeof(payload),
           "{\"word\":\"%s\",\"result\":\"%s\",\"ts\":%lu}",
           DEMO_WORD, result, millis());
  networkPublish(TOPIC_RESULT, payload);

  char progress[64];
  snprintf(progress, sizeof(progress),
           "{\"correct\":%d,\"wrong\":%d}", correctCount, wrongCount);
  networkPublish(TOPIC_PROGRESS, progress);

  Serial.print("Da publish: ");
  Serial.println(payload);
}

// Danh sách đủ 14 biểu cảm để lệnh "face demo" tự chạy qua từng cái — đỡ phải gõ tay
// 14 lần khi muốn xem hết hoặc quay video demo báo cáo.
static const char *DEMO_CYCLE[] = {
    "neutral", "happy", "sad", "angry", "surprised", "sleepy", "wink",
    "love", "cool", "cute", "dizzy", "questioning", "thinking", "speaking"};
static const int DEMO_CYCLE_LEN = sizeof(DEMO_CYCLE) / sizeof(DEMO_CYCLE[0]);
static const unsigned long DEMO_CYCLE_INTERVAL_MS = 1500;
static bool demoCycleActive = false;
static int demoCycleIndex = 0;
static unsigned long demoCycleLastMs = 0;

// Cho gõ tay "face <ten>" qua Serial Monitor để thử từng biểu cảm, hoặc "face demo" để
// tự động chạy qua LẦN LƯỢT cả 14 biểu cảm (mỗi cái giữ 1.5s) — cùng quy ước "face X" với
// firmware/panda_firmware.ino của bạn AI trong nhóm (xem ai.md mục 5).
static void handleSerialCommand()
{
  if (!Serial.available())
  {
    return;
  }
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (!line.startsWith("face "))
  {
    return;
  }

  String arg = line.substring(5);
  if (arg == "demo")
  {
    demoCycleActive = true;
    demoCycleIndex = 0;
    demoCycleLastMs = millis();
    displaySetExpression(DEMO_CYCLE[demoCycleIndex]);
  }
  else
  {
    // Gõ 1 biểu cảm cụ thể bằng tay -> huỷ chế độ demo tự động đang chạy (nếu có), để
    // lệnh tay luôn "thắng" thay vì bị demo tự động ghi đè ngay vòng loop() kế tiếp.
    demoCycleActive = false;
    displaySetExpression(arg.c_str());
  }
}

// Gọi mỗi vòng loop(): khi demo tự động đang bật, cứ mỗi 1.5s chuyển sang biểu cảm kế
// tiếp trong DEMO_CYCLE, lặp vòng quanh khi hết danh sách.
static void handleDemoCycle()
{
  if (!demoCycleActive)
  {
    return;
  }
  unsigned long now = millis();
  if (now - demoCycleLastMs < DEMO_CYCLE_INTERVAL_MS)
  {
    return;
  }
  demoCycleLastMs = now;
  demoCycleIndex = (demoCycleIndex + 1) % DEMO_CYCLE_LEN;
  displaySetExpression(DEMO_CYCLE[demoCycleIndex]);
}

void setup()
{
  Serial.begin(115200);
  inputSetup();
  displaySetup();
  networkSetup();
  audioI2sSetup(); // module học I2S của Tuần 3 — xem audio_i2s.cpp để hiểu vì sao chưa đọc được âm thanh thật trong Wokwi
  displaySetExpression("neutral");
  displaySetStats(DEMO_WORD, correctCount, wrongCount);
}

void loop()
{
  networkLoop();
  handleSerialCommand();
  handleDemoCycle();

  ButtonEvent event = inputPoll();
  if (event == ButtonEvent::Correct)
  {
    demoCycleActive = false; // nút bấm thật luôn "thắng" demo tự động, tránh bị ghi đè ngay vòng loop() kế tiếp
    correctCount++;
    displaySetExpression("happy");
    displaySetStats(DEMO_WORD, correctCount, wrongCount);
    publishResult("correct");
  }
  else if (event == ButtonEvent::Wrong)
  {
    demoCycleActive = false;
    wrongCount++;
    displaySetExpression("sad");
    displaySetStats(DEMO_WORD, correctCount, wrongCount);
    publishResult("wrong");
  }
  else if (event == ButtonEvent::CycleFace)
  {
    // Nút thứ 3 (GPIO27): mỗi lần bấm nhảy sang biểu cảm KẾ TIẾP trong DEMO_CYCLE — cách
    // test 14 biểu cảm bằng phần cứng thật, không phụ thuộc gõ lệnh Serial (Serial Monitor
    // của VS Code đôi khi không nhận đúng bàn phím tuỳ cấu hình terminal).
    demoCycleActive = false;
    demoCycleIndex = (demoCycleIndex + 1) % DEMO_CYCLE_LEN;
    displaySetExpression(DEMO_CYCLE[demoCycleIndex]);
  }

  displayLoop();
  audioI2sLoop();
}
