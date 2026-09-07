#include "input.h"
#include "pins.h"

// HIGH khi không bấm (INPUT_PULLUP kéo lên), LOW khi bấm (nút nối chân xuống GND).
static bool lastCorrectState = HIGH;
static bool lastWrongState = HIGH;

static unsigned long lastEventMs = 0;
static const unsigned long DEBOUNCE_MS = 200;

void inputSetup()
{
  pinMode(PIN_BTN_CORRECT, INPUT_PULLUP);
  pinMode(PIN_BTN_WRONG, INPUT_PULLUP);
}

ButtonEvent inputPoll()
{
  bool correctState = digitalRead(PIN_BTN_CORRECT);
  bool wrongState = digitalRead(PIN_BTN_WRONG);
  unsigned long now = millis();

  ButtonEvent event = ButtonEvent::None;

  // Debounce bằng millis() thay vì delay(): delay() sẽ đứng hình TOÀN BỘ loop() (kể cả
  // networkLoop() đang cố reconnect WiFi/MQTT và displayLoop() đang chạy animation), còn
  // cách này chỉ "bỏ qua" sự kiện đến quá sớm sau lần trước, phần còn lại vẫn chạy đều.
  if (now - lastEventMs >= DEBOUNCE_MS)
  {
    if (correctState == LOW && lastCorrectState == HIGH)
    {
      event = ButtonEvent::Correct;
      lastEventMs = now;
    }
    else if (wrongState == LOW && lastWrongState == HIGH)
    {
      event = ButtonEvent::Wrong;
      lastEventMs = now;
    }
  }

  lastCorrectState = correctState;
  lastWrongState = wrongState;
  return event;
}
