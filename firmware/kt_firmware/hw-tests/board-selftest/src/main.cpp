#include <Arduino.h>

// board-selftest — KHÔNG cần nối bất kỳ dây nào ngoài cáp USB-C từ board sang máy tính.
// Mục đích duy nhất: xác nhận 3 việc cùng lúc — (1) máy tính nạp được code vào board,
// (2) chip ESP32-S3 khởi động và chạy được code đó, (3) kênh Serial (cổng để xem log)
// hoạt động cả 2 chiều (board gửi log ra, và board đọc được phím gõ vào từ Serial Monitor).
//
// Không dùng I2S/camera/thư viện gì đặc biệt — nếu bài này chạy được thì chắc chắn board
// còn sống và quy trình nạp code (PlatformIO -> USB -> chip) đang đúng, có vấn đề gì về
// sau (mic không lên, loa im...) thì chắc chắn là do dây nối, không phải do board hỏng.

static unsigned long lastPrint = 0;
static int counter = 0;

// ---------------------------------------------------------------------------
// Nháy đèn LED đỏ liên tục — không phụ thuộc Serial Monitor có mở hay không, chỉ cần
// cắm nguồn là nháy, để nhìn bằng mắt biết ngay board đang chạy mà không cần mở máy tính.
//
// ESP32-S3-DevKitC-1 (và board N16R8 của bạn) dùng đèn LED RGB ĐỊA CHỈ HOÁ (kiểu WS2812,
// chỉ có 1 dây dữ liệu điều khiển cả 3 màu) thay vì đèn LED thường 1 màu bật/tắt bằng
// digitalWrite() — nên không thể nháy bằng cách quen thuộc, phải gọi neopixelWrite() với
// đủ 3 giá trị đỏ/lục/lam. RGB_BUILTIN là hằng số Arduino-ESP32 tự định nghĩa sẵn đúng
// chân LED này cho board đang chọn trong platformio.ini (board = esp32-s3-devkitc-1).
// ---------------------------------------------------------------------------
#if !defined(RGB_BUILTIN) && !defined(LED_BUILTIN)
#warning "Board nay khong khai bao san LED nao (khong co RGB_BUILTIN lan LED_BUILTIN) - phan nhay den se bi bo qua, xem dong Serial.println canh bao luc chay."
#endif

static bool ledOn = false;
static unsigned long lastBlinkMs = 0;
static const unsigned long BLINK_INTERVAL_MS = 400; // nháy 2 lần rưỡi mỗi giây — đủ nhanh để thấy rõ là "đang chạy" chứ không phải đứng hình

void setup()
{
  Serial.begin(115200);
  delay(500); // chờ cổng Serial ổn định — mở Serial Monitor trễ 1 chút cũng không mất log đầu

#if !defined(RGB_BUILTIN) && defined(LED_BUILTIN)
  pinMode(LED_BUILTIN, OUTPUT);
#endif

  Serial.println();
  Serial.println("========================================");
  Serial.println("  PANDA HEAD - board-selftest");
  Serial.println("  Neu doc duoc dong nay: board da NAP CODE THANH CONG");
  Serial.println("========================================");

  Serial.print("Chip: ");
  Serial.println(ESP.getChipModel());
  Serial.print("So nhan (core): ");
  Serial.println(ESP.getChipCores());
  Serial.print("Toc do CPU: ");
  Serial.print(ESP.getCpuFreqMHz());
  Serial.println(" MHz");
  Serial.print("Flash: ");
  Serial.print(ESP.getFlashChipSize() / (1024 * 1024));
  Serial.println(" MB");

  // PSRAM: bản N16R8 phải có 8MB. Nếu dòng này in ra 0, nghĩa là board_build.psram_type
  // trong platformio.ini chưa khớp với board thật (báo lại để sửa, không phải board hỏng).
  Serial.print("PSRAM: ");
  Serial.print(ESP.getPsramSize() / (1024 * 1024));
  Serial.println(" MB");

#if defined(RGB_BUILTIN)
  Serial.println("LED: dung RGB_BUILTIN (den dia chi hoa), se nhay mau do.");
#elif defined(LED_BUILTIN)
  Serial.println("LED: dung LED_BUILTIN (den thuong 1 mau).");
#else
  Serial.println("LED: KHONG TIM THAY - board nay chua khai bao chan LED co san, bo qua phan nhay den.");
#endif

  Serial.println("----------------------------------------");
  Serial.println("Go chu bat ky roi Enter trong Serial Monitor, board se lap lai cho ban xem.");
}

void loop()
{
  // Cứ mỗi giây in 1 dòng đếm số — nếu số này chạy đều, nghĩa là chip không bị treo/reset
  // liên tục (một lỗi hay gặp với board rẻ tiền là nguồn yếu, chip cứ khởi động lại liên tục).
  if (millis() - lastPrint >= 1000)
  {
    lastPrint = millis();
    counter++;
    Serial.print("[dang song] nhip thu ");
    Serial.println(counter);
  }

  // Nháy LED — dùng millis() thay vì delay() để không chặn phần đọc Serial phía dưới.
  if (millis() - lastBlinkMs >= BLINK_INTERVAL_MS)
  {
    lastBlinkMs = millis();
    ledOn = !ledOn;
#if defined(RGB_BUILTIN)
    // Độ sáng để 40/255 (không phải 255) — đèn RGB sát ngay cạnh mắt nhìn, để full sáng
    // vừa chói vừa tốn điện không cần thiết cho một đèn báo trạng thái.
    neopixelWrite(RGB_BUILTIN, ledOn ? 40 : 0, 0, 0);
#elif defined(LED_BUILTIN)
    digitalWrite(LED_BUILTIN, ledOn ? HIGH : LOW);
#endif
  }

  // Đọc thử xem Serial Monitor có gõ gì vào không — xác nhận luôn chiều máy tính -> board.
  if (Serial.available())
  {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0)
    {
      Serial.print("[nhan duoc] ban vua go: ");
      Serial.println(line);
    }
  }

  delay(1);
}
