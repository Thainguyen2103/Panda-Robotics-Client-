#include <Arduino.h>
#include "esp_camera.h"
#include "face.h"

// ---------------------------------------------------------------------------
// cam-emotion — camera + màn hình + AI cảm xúc của Thái.
//
// Chia việc:
//   ESP32 (file này): chụp ảnh → gửi qua dây USB lên laptop; nhận lại tên biểu cảm → vẽ mặt.
//   Laptop (tools/emotion_viewer.py): chạy ĐÚNG code nhận diện cảm xúc của Thái (thư mục
//     Panda-Robotics-Client-/server/vision) trên ảnh nhận được, hiện cửa sổ camera có khung
//     mặt + % từng cảm xúc, rồi gửi lệnh "face <ten> <chu thich>" ngược xuống board.
// Vì sao AI chạy trên laptop chứ không trên ESP32: mô hình FER+ nặng 35MB, MediaPipe còn
// cần cả trăm MB RAM — ESP32-S3 chỉ có 8MB PSRAM và CPU 240MHz, không kham nổi.
//
// 2 việc chạy SONG SONG trên 2 nhân CPU của ESP32-S3:
//   - Nhân 0: task cameraTask() — chụp + đẩy ảnh qua USB (bận chờ dây USB phần lớn thời gian)
//   - Nhân 1: loop() — đọc lệnh từ laptop + vẽ mặt 33 khung/giây
// Nếu làm chung 1 vòng lặp, lúc gửi 1 ảnh (~30ms) mặt sẽ đứng hình → chuyển động giật.
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 4000000 // đã đo ở cam-selftest: 5M thì chip CH343 truyền sai bit

#define PWDN_GPIO_NUM -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 15
#define SIOD_GPIO_NUM 4
#define SIOC_GPIO_NUM 5
#define Y9_GPIO_NUM 16
#define Y8_GPIO_NUM 17
#define Y7_GPIO_NUM 18
#define Y6_GPIO_NUM 12
#define Y5_GPIO_NUM 10
#define Y4_GPIO_NUM 8
#define Y3_GPIO_NUM 9
#define Y2_GPIO_NUM 11
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM 7
#define PCLK_GPIO_NUM 13

static const uint8_t FRAME_MAGIC[4] = {'P', 'N', 'D', 'A'};

// Khoá dùng chung dây Serial: 1 khung ảnh gửi bằng 3 lần write (dấu, độ dài, dữ liệu). Nếu
// nhân kia chen 1 dòng log vào giữa, laptop sẽ đọc sai độ dài → hỏng khung. Ai muốn ghi Serial
// phải "cầm khoá" trước, ghi xong mới trả.
static SemaphoreHandle_t serialLock;

static void logLine(const String &text)
{
  xSemaphoreTake(serialLock, portMAX_DELAY);
  Serial.print("[cam] ");
  Serial.println(text);
  xSemaphoreGive(serialLock);
}

static bool setupCamera()
{
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 24000000; // đo ở cam-selftest: 24MHz = 16,5 khung/giây
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.frame_size = FRAMESIZE_VGA; // 640x480 = đúng kích thước code của Thái xử lý
  config.jpeg_quality = 10;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;

  if (esp_camera_init(&config) != ESP_OK)
  {
    return false;
  }
  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 1); // camera lắp ngược → xoay 180°
  s->set_hmirror(s, 1);
  s->set_lenc(s, 1);
  s->set_bpc(s, 1);
  s->set_wpc(s, 1);
  s->set_raw_gma(s, 1);
  return true;
}

// 2 kiểu ảnh, đổi được lúc đang chạy bằng lệnh "cam natural" / "cam enhanced" từ laptop.
//  - natural (mặc định): để cảm biến gần như nguyên gốc, giống webcam laptop. FER+ được train
//    trên ảnh chụp bình thường, nên ảnh "tự nhiên" là thứ AI quen nhìn nhất.
//  - enhanced: bản chỉnh ở cam-selftest cho MẮT NGƯỜI xem (sắc cạnh tối đa, tăng tương phản,
//    tắt lọc nhiễu) — đẹp với người nhưng tạo viền giả + nhiễu hạt quanh chân mày, có thể làm
//    AI đọc sai các cơ nhỏ như cau mày (cảm xúc "giận").
static void applyCameraPreset(bool enhanced)
{
  sensor_t *s = esp_camera_sensor_get();
  s->set_brightness(s, enhanced ? 1 : 0);
  s->set_saturation(s, enhanced ? -1 : 0);
  s->set_contrast(s, enhanced ? 1 : 0);
  s->set_sharpness(s, enhanced ? 2 : 0);
  s->set_denoise(s, enhanced ? 0 : 1);
}

static void cameraTask(void *)
{
  for (;;)
  {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
    {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    uint32_t len = fb->len;
    xSemaphoreTake(serialLock, portMAX_DELAY);
    Serial.write(FRAME_MAGIC, 4);
    Serial.write((const uint8_t *)&len, 4);
    Serial.write(fb->buf, fb->len);
    xSemaphoreGive(serialLock);
    esp_camera_fb_return(fb);
  }
}

// Lệnh từ laptop, mỗi lệnh 1 dòng: "face <ten_bieu_cam> <chu thich...>"
// vd "face happy VUI 87%". Ghép từng ký tự vào bộ đệm tới khi gặp '\n' — không dùng
// readStringUntil() vì hàm đó đứng chờ tới 1 giây nếu dòng chưa tới đủ, mặt sẽ đứng hình.
static void readCommands()
{
  static char line[96];
  static size_t n = 0;
  while (Serial.available())
  {
    char c = (char)Serial.read();
    if (c == '\r')
    {
      continue;
    }
    if (c != '\n')
    {
      if (n < sizeof(line) - 1)
      {
        line[n++] = c;
      }
      continue;
    }
    line[n] = '\0';
    n = 0;
    if (strcmp(line, "cam natural") == 0 || strcmp(line, "cam enhanced") == 0)
    {
      applyCameraPreset(line[4] == 'e');
      continue;
    }
    if (strncmp(line, "face ", 5) != 0)
    {
      continue;
    }
    char *name = line + 5;
    char *caption = strchr(name, ' ');
    if (caption)
    {
      *caption++ = '\0';
    }
    faceSetExpression(name);
    faceSetCaption(caption ? caption : "");
  }
}

void setup()
{
  Serial.setTxBufferSize(32768);
  Serial.setRxBufferSize(1024);
  Serial.begin(SERIAL_BAUD);
  serialLock = xSemaphoreCreateMutex();
  delay(300);

  if (!faceBegin())
  {
    logLine("LOI: khong du RAM cho canvas mat");
  }
  faceSetExpression("sleepy");
  faceSetCaption("CHO LAPTOP...");

  if (!psramFound())
  {
    logLine("LOI: khong thay PSRAM - kiem tra board_build.arduino.memory_type trong platformio.ini");
    faceSetCaption("LOI PSRAM");
    return;
  }
  if (!setupCamera())
  {
    logLine("LOI: camera init that bai - cam lai cap FPC");
    faceSetExpression("dizzy");
    faceSetCaption("LOI CAMERA");
    return;
  }
  applyCameraPreset(false);
  logLine("Camera + man hinh OK, dang gui anh len laptop");

  // Nhân 0 (APP_CPU là nhân 1, nơi loop() chạy). Không dùng WiFi nên nhân 0 đang rảnh.
  xTaskCreatePinnedToCore(cameraTask, "camera", 8192, nullptr, 1, nullptr, 0);
}

void loop()
{
  readCommands();
  faceTick();
  delay(1);
}
