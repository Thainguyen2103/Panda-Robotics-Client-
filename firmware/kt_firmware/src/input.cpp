#include "input.h"
#include "pins.h"

// HIGH khi không bấm (INPUT_PULLUP kéo lên), LOW khi bấm (nút nối chân xuống GND).
static bool lastFaceState = HIGH;
static bool lastWordState = HIGH;

static unsigned long lastEventMs = 0;
static const unsigned long DEBOUNCE_MS = 200;

void inputSetup()
{
  pinMode(PIN_BTN_FACE, INPUT_PULLUP);
  pinMode(PIN_BTN_WORD, INPUT_PULLUP);
}

ButtonEvent inputPoll()
{
  bool faceState = digitalRead(PIN_BTN_FACE);
  bool wordState = digitalRead(PIN_BTN_WORD);
  unsigned long now = millis();

  ButtonEvent event = ButtonEvent::None;

  // Debounce bằng millis() thay vì delay(): delay() sẽ đứng hình TOÀN BỘ loop() (kể cả
  // networkLoop() đang cố reconnect WiFi/MQTT và displayLoop() đang chạy animation), còn
  // cách này chỉ "bỏ qua" sự kiện đến quá sớm sau lần trước, phần còn lại vẫn chạy đều.
  if (now - lastEventMs >= DEBOUNCE_MS)
  {
    if (faceState == LOW && lastFaceState == HIGH)
    {
      event = ButtonEvent::NextFace;
      lastEventMs = now;
    }
    else if (wordState == LOW && lastWordState == HIGH)
    {
      event = ButtonEvent::NextWord;
      lastEventMs = now;
    }
  }

  lastFaceState = faceState;
  lastWordState = wordState;
  return event;
}
