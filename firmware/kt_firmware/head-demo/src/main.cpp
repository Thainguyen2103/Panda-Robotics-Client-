#include <Arduino.h>
#include <ArduinoOTA.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <driver/i2s.h>
#include <freertos/stream_buffer.h>
#include "esp_camera.h"
#include "face.h"

// Tên + mật khẩu WiFi (file riêng, không đưa lên git — giống body-test). Chưa có file thì
// chép wifi_secrets.example.h thành wifi_secrets.h rồi điền. Để trống = chỉ chạy qua dây USB.
#if __has_include("wifi_secrets.h")
#include "wifi_secrets.h"
#else
#define WIFI_SSID ""
#define WIFI_PASS ""
#endif

// ---------------------------------------------------------------------------
// head-demo — phần ĐẦU robot để demo: camera + màn TFT + loa.
//
// Giống cam-emotion (ảnh lên laptop, laptop chạy AI cảm xúc của Thái, gửi lại tên mặt),
// thêm 1 việc: laptop gửi GIỌNG NÓI xuống (câu trả lời của AI Thái + Ngọc Anh, đã đổi
// thành âm thanh PCM 16kHz) → board phát ra loa qua MAX98357.
//
// 2 đường nối với laptop, CÙNG 1 kiểu dữ liệu (laptop đổi đường không cần đổi giao thức):
//   - dây USB (Serial 4Mbaud)                       : như trước
//   - WiFi: laptop nối TCP tới cổng HEAD_TCP_PORT   : không cần dây, robot chạy tự do.
//     Laptop chưa nối thì board phát "PANDA-HEAD" cho cả mạng (UDP cổng HEAD_BEACON_PORT)
//     mỗi giây để laptop tự tìm ra địa chỉ IP, khỏi phải gõ.
//   Có laptop nối WiFi → ảnh/mic gửi qua WiFi; không thì gửi qua dây như cũ. Lệnh nhận cả 2 đường.
//   Nạp code qua WiFi (OTA): xem env "ota" trong platformio.ini.
//
// Lệnh từ laptop (đi ngược chiều với ảnh):
//   "face <ten> <chu thich>\n"   đổi mặt robot
//   "cam natural|enhanced\n"     đổi kiểu ảnh
//   "pcm <n>\n" + đúng n byte   n byte âm thanh (số 16-bit, 16kHz, 1 kênh) để phát ra loa
//   "mic on\n" / "mic off\n"    bật/tắt gửi tiếng từ mic robot lên laptop (xem micTask)
//
// Chia việc trên 2 nhân CPU:
//   Nhân 0: cameraTask — chụp + gửi ảnh lên laptop
//           micTask    — đọc mic INMP441 (I2S_NUM_0, khác I2S_NUM_1 của loa) + gửi lên laptop
//   Nhân 1: loop()     — đọc lệnh từ laptop + vẽ mặt ~33 khung/giây
//           audioTask  — lấy âm thanh từ "bể chứa" và đẩy ra loa
// Vì sao âm thanh cần task riêng: i2s_write() đứng chờ tới khi loa phát xong phần trước.
// Nếu gọi trong loop(), mặt robot sẽ đứng hình trong lúc robot nói.
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 4000000 // đã đo ở cam-selftest: 5M thì chip CH343 truyền sai bit

// Camera OV5640 (qua cáp FPC)
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

// Khuếch đại MAX98357 (đã test bằng hw-tests/speaker-only)
#define AMP_BCLK 47
#define AMP_LRC 48
#define AMP_DIN 21
#define SAMPLE_RATE 16000

// Mic INMP441 (I2S_NUM_0 — khác I2S_NUM_1 của loa ở trên nên chạy đồng thời được).
// 3 chân GPIO 40/41/42 chọn vì CHƯA bị camera/màn/loa dùng (xem danh sách chân đã
// chiếm ở các #define phía trên + face.h) và không nằm trong nhóm chân "đặc biệt" của
// ESP32-S3 (0/3 = strapping lúc boot, 19/20 = USB gốc, 26-37 = nối trong với flash/PSRAM
// octal nên module N16R8 không đưa ra chân ngoài, 43/44 = UART0 đang dùng cho Serial/CH343,
// 45/46 = strapping chọn điện áp flash lúc boot). Chân L/R của mic nối GND -> chọn kênh trái.
// Ban đầu định SCK=40, WS=41 nhưng lúc hàn bị đảo 2 dây -> đổi trong code cho khớp mạch thật
// (ESP32-S3 cho gán I2S vào chân bất kỳ qua "GPIO matrix", nên đổi số ở đây là đủ, không cần hàn lại).
#define MIC_SCK 41
#define MIC_WS 40
#define MIC_SD 42

static const uint8_t FRAME_MAGIC[4] = {'P', 'N', 'D', 'A'};  // 1 khung ảnh JPEG
static const uint8_t MIC_MAGIC[4] = {'P', 'N', 'D', 'M'};    // 1 khung tiếng mic (PCM 16-bit)

// Khoá dùng chung dây Serial khi GỬI: 1 khung ảnh gửi bằng 3 lần write. Nếu nhân kia chen
// 1 dòng log vào giữa, laptop đọc sai độ dài → hỏng khung.
static SemaphoreHandle_t serialLock;

// "Bể chứa" âm thanh 32KB ≈ 1 giây tiếng nói. loop() đổ byte nhận từ USB vào, audioTask
// múc ra phát. Có bể ở giữa để 2 bên chạy lệch nhịp nhau mà tiếng vẫn liền mạch.
static StreamBufferHandle_t audioBuf;
static bool ampReady = false;

// Mic: micEnabled do laptop bật/tắt bằng lệnh "mic on"/"mic off" (SPACE trong head_demo.py).
// Mặc định TẮT: không gửi tiếng mic lên khi không ai hỏi, đỡ chiếm băng thông dây USB
// (camera đã chiếm ~200KB/giây trong tổng ~400KB/giây của dây 4Mbaud).
static bool micEnabled = false;
static bool micReady = false;

// ---- WiFi ----
const uint16_t HEAD_TCP_PORT = 4300;    // laptop nối vào đây
const uint16_t HEAD_BEACON_PORT = 4212; // laptop nghe "PANDA-HEAD" ở đây (thân dùng 4210/4211)
static WiFiServer server(HEAD_TCP_PORT);
static WiFiClient client;         // laptop đang nối qua WiFi
static volatile bool clientOn = false;
static volatile bool otaBusy = false; // đang nạp code qua WiFi → tạm ngừng gửi ảnh/mic
static WiFiUDP beacon;

// Gửi lên laptop. Gọi khi ĐANG GIỮ serialLock. Laptop nối WiFi → gửi qua WiFi, không thì qua dây.
// client.write() đứng chờ tới khi WiFi nhận hết (hoặc hỏng) — trả về số byte đã gửi.
static void sendOut(const uint8_t *data, size_t len)
{
  if (!clientOn)
  {
    Serial.write(data, len);
    return;
  }
  if (client.write(data, len) != len)
  {
    clientOn = false; // gửi hỏng = laptop đã ngắt / WiFi rớt. loop() sẽ dọn và chờ laptop nối lại.
  }
}

static void logLine(const String &text)
{
  String line = "[cam] " + text + "\n";
  xSemaphoreTake(serialLock, portMAX_DELAY);
  sendOut((const uint8_t *)line.c_str(), line.length());
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
  config.xclk_freq_hz = 24000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.frame_size = FRAMESIZE_VGA;
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

// Giống cam-emotion: "natural" cho AI, "enhanced" đẹp cho mắt người.
static void applyCameraPreset(bool enhanced)
{
  sensor_t *s = esp_camera_sensor_get();
  s->set_brightness(s, enhanced ? 1 : 0);
  s->set_saturation(s, enhanced ? -1 : 0);
  s->set_contrast(s, enhanced ? 1 : 0);
  s->set_sharpness(s, enhanced ? 2 : 0);
  s->set_denoise(s, enhanced ? 0 : 1);
}

static bool setupAmp()
{
  // Gửi STEREO, cùng 1 mẫu cho 2 kênh (giống speaker-only đã test chạy tốt): MAX98357 mặc
  // định trộn (trái+phải)/2 nên ra đúng mẫu đó.
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 8,
      .dma_buf_len = 256,
      .use_apll = false,
      .tx_desc_auto_clear = true, // hết tiếng thì tự phát số 0 (im), không lặp khối cũ gây rè
      .fixed_mclk = 0};
  i2s_pin_config_t pins = {
      .mck_io_num = I2S_PIN_NO_CHANGE,
      .bck_io_num = AMP_BCLK,
      .ws_io_num = AMP_LRC,
      .data_out_num = AMP_DIN,
      .data_in_num = I2S_PIN_NO_CHANGE};
  return i2s_driver_install(I2S_NUM_1, &cfg, 0, NULL) == ESP_OK &&
         i2s_set_pin(I2S_NUM_1, &pins) == ESP_OK;
}

static bool setupMic()
{
  // INMP441 gửi mẫu 24-bit (đặt lệch trái trong khung 32-bit) trên 1 kênh (L/R nối GND =
  // kênh trái) -> phải khai 32BIT + ONLY_LEFT, không phải 16BIT như lúc phát ra loa.
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 6,
      .dma_buf_len = 256,
      .use_apll = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk = 0};
  i2s_pin_config_t pins = {
      .mck_io_num = I2S_PIN_NO_CHANGE,
      .bck_io_num = MIC_SCK,
      .ws_io_num = MIC_WS,
      .data_out_num = I2S_PIN_NO_CHANGE,
      .data_in_num = MIC_SD};
  return i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL) == ESP_OK &&
         i2s_set_pin(I2S_NUM_0, &pins) == ESP_OK;
}

static void cameraTask(void *)
{
  for (;;)
  {
    if (otaBusy)
    {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb)
    {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    uint32_t len = fb->len;
    xSemaphoreTake(serialLock, portMAX_DELAY);
    sendOut(FRAME_MAGIC, 4);
    sendOut((const uint8_t *)&len, 4);
    sendOut(fb->buf, fb->len);
    xSemaphoreGive(serialLock);
    esp_camera_fb_return(fb);
  }
}

// Đọc mic, gửi lên laptop dạng "PNDM" + độ dài + PCM 16-bit mono — cùng kiểu khung với
// ảnh camera ("PNDA") để head_demo.py phân biệt được 2 loại khung trên cùng 1 dây.
static void micTask(void *)
{
  static int32_t raw[256];
  static int16_t pcm[256];
  for (;;)
  {
    if (!micReady || !micEnabled || otaBusy)
    {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    size_t bytesRead = 0;
    i2s_read(I2S_NUM_0, raw, sizeof(raw), &bytesRead, pdMS_TO_TICKS(100));
    int samples = bytesRead / 4; // mỗi mẫu mic 32-bit = 4 byte
    if (samples == 0)
    {
      continue;
    }
    // INMP441: 24 bit dữ liệu thật nằm ở 24 bit cao của khung 32-bit -> dịch phải 16 bit =
    // giữ đúng 16 bit cao nhất, kết quả LUÔN vừa int16 nên không bao giờ tràn.
    // Bản cũ dịch 14 (to gấp 4) ra số 18-bit: nói to/sát mic là vượt ±32767, ép kiểu int16_t
    // làm số "quấn" sang dấu ngược (-33000 thành +32536) -> tiếng lốp bốp/rè, Gemini chép sai.
    // Đo file ghi thật: 306 lần quấn trong 1,3 giây nói. Muốn to hơn thì KHÔNG giảm số 16 này:
    // laptop đã tự chỉnh âm lượng (tools/mic_clean.py), tính bằng số thực nên không tràn được.
    for (int i = 0; i < samples; i++)
    {
      pcm[i] = (int16_t)(raw[i] >> 16);
    }
    uint32_t len = samples * 2;
    xSemaphoreTake(serialLock, portMAX_DELAY);
    sendOut(MIC_MAGIC, 4);
    sendOut((const uint8_t *)&len, 4);
    sendOut((const uint8_t *)pcm, len);
    xSemaphoreGive(serialLock);
  }
}

// Múc âm thanh mono từ bể, nhân đôi thành stereo, đẩy ra loa.
static void audioTask(void *)
{
  static int16_t mono[256];
  static int16_t stereo[512];
  for (;;)
  {
    size_t n = xStreamBufferReceive(audioBuf, mono, sizeof(mono), pdMS_TO_TICKS(50));
    int samples = n / 2; // laptop luôn gửi số byte chẵn (mỗi mẫu 2 byte)
    if (samples == 0)
    {
      continue; // im lặng: tx_desc_auto_clear tự phát số 0
    }
    for (int i = 0; i < samples; i++)
    {
      stereo[2 * i] = mono[i];
      stereo[2 * i + 1] = mono[i];
    }
    size_t written = 0;
    i2s_write(I2S_NUM_1, stereo, samples * 4, &written, portMAX_DELAY);
  }
}

// Trạng thái đọc lệnh của 1 đường (dây USB hoặc WiFi). Mỗi đường 1 bộ riêng: lệnh đang
// đọc dở trên đường này không bị byte của đường kia chen vào giữa.
struct CmdParser
{
  char line[96];
  size_t len = 0;
  uint32_t pcmLeft = 0;
};
static CmdParser usbParser, wifiParser;

// Đọc lệnh từ laptop (dây hoặc WiFi — "Stream" là kiểu chung của cả 2). Có 2 chế độ:
//  - chữ: ghép từng ký tự tới '\n' (không dùng readStringUntil vì nó đứng chờ tới 1 giây)
//  - nhị phân: sau dòng "pcm <n>", n byte tiếp theo là âm thanh → đổ thẳng vào bể
static void readCommands(Stream &in, CmdParser &p)
{
  char *line = p.line;
  size_t &len = p.len;
  uint32_t &pcmLeft = p.pcmLeft;
  static uint8_t chunk[512];

  while (in.available())
  {
    if (pcmLeft > 0)
    {
      // Chỉ lấy số byte CHẴN để không bao giờ cắt đôi 1 mẫu 16-bit (byte lẻ còn lại
      // nằm chờ trong bộ đệm tới lượt sau).
      size_t n = min((size_t)in.available(), min((size_t)pcmLeft, sizeof(chunk)));
      n &= ~(size_t)1; // laptop luôn gửi số byte chẵn
      if (n == 0)
      {
        break; // mới về 1 byte, chờ byte thứ 2 của mẫu
      }
      n = in.readBytes(chunk, n);
      pcmLeft -= n;
      if (ampReady)
      {
        // Bể đầy (laptop gửi nhanh quá) → chờ cho loa phát bớt. Phải gửi ĐỦ n byte: nếu
        // rơi mất 1 byte lẻ thì mọi mẫu phía sau bị lệch byte → tiếng rè rất to.
        size_t done = 0;
        while (done < n)
        {
          done += xStreamBufferSend(audioBuf, chunk + done, n - done, pdMS_TO_TICKS(200));
        }
      }
      continue;
    }

    char c = (char)in.read();
    if (c == '\r')
    {
      continue;
    }
    if (c != '\n')
    {
      if (len < sizeof(p.line) - 1)
      {
        line[len++] = c;
      }
      continue;
    }
    line[len] = '\0';
    len = 0;

    if (strncmp(line, "pcm ", 4) == 0)
    {
      pcmLeft = strtoul(line + 4, nullptr, 10);
      continue;
    }
    if (strcmp(line, "mic on") == 0 || strcmp(line, "mic off") == 0)
    {
      micEnabled = (line[5] == 'n'); // "mic on"[5]='n', "mic off"[5]='f'
      continue;
    }
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

// Giữ WiFi + kết nối với laptop. Gọi mỗi vòng loop(), không bao giờ đứng chờ lâu
// (loop() còn phải vẽ mặt 33 khung/giây).
static void serviceWifi()
{
  if (strlen(WIFI_SSID) == 0)
  {
    return;
  }
  // Tự nối lại WiFi: thư viện chỉ thử vài lần rồi bỏ cuộc nếu lúc bật board hotspot chưa
  // phát sóng (giống body-test). 8 giây/lần vì 1 lần nối mất 2-5 giây.
  static uint32_t lastTry = 0;
  static bool wasConnected = false;
  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wasConnected)
  {
    server.begin();
    server.setNoDelay(true); // gửi ngay từng gói, không gom lại chờ → lệnh mặt/âm thanh tới nhanh
    beacon.begin(HEAD_BEACON_PORT);
    ArduinoOTA.setHostname("panda-head");
    ArduinoOTA.onStart([]()
                       { otaBusy = true; faceSetExpression("sleepy"); faceSetCaption("DANG NAP CODE"); });
    ArduinoOTA.onError([](ota_error_t)
                       { otaBusy = false; faceSetCaption("NAP LOI"); });
    ArduinoOTA.begin();
    logLine(String("WiFi OK: ") + WIFI_SSID + ", IP " + WiFi.localIP().toString());
  }
  wasConnected = connected;
  if (!connected)
  {
    if (millis() - lastTry >= 8000)
    {
      lastTry = millis();
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
    return;
  }

  ArduinoOTA.handle();

  // Laptop mới nối vào → đổi đường gửi sang WiFi. Đổi khi đang giữ serialLock để
  // cameraTask không đang gửi dở 1 khung vào kết nối cũ.
  WiFiClient incoming = server.available();
  if (incoming)
  {
    incoming.setNoDelay(true);
    xSemaphoreTake(serialLock, portMAX_DELAY);
    client.stop();
    client = incoming;
    clientOn = true;
    xSemaphoreGive(serialLock);
    wifiParser = CmdParser(); // bỏ lệnh đọc dở của kết nối cũ
    faceSetCaption("LAPTOP DA NOI WIFI");
  }

  // Laptop ngắt (tắt chương trình / ra khỏi vùng WiFi) → quay về gửi qua dây.
  // Thử khoá (không chờ): cameraTask đang gửi ảnh thì để lượt sau, khỏi làm mặt robot khựng.
  static uint32_t lastCheck = 0;
  if (millis() - lastCheck >= 500 && xSemaphoreTake(serialLock, 0) == pdTRUE)
  {
    lastCheck = millis();
    // (Không viết "if (client)": phép thử đó tự gọi connected(), client đã chết thì ra false
    //  nên sẽ không bao giờ dọn được.)
    if (!clientOn || !client.connected())
    {
      client.stop(); // dừng 1 client đã dừng rồi cũng không sao
      clientOn = false;
    }
    xSemaphoreGive(serialLock);
  }

  // Chưa có laptop nào nối → 1 giây/lần báo cho cả mạng "tôi ở đây".
  static uint32_t lastBeacon = 0;
  if (!clientOn && millis() - lastBeacon >= 1000)
  {
    lastBeacon = millis();
    beacon.beginPacket(WiFi.broadcastIP(), HEAD_BEACON_PORT);
    beacon.printf("PANDA-HEAD %u\n", HEAD_TCP_PORT);
    beacon.endPacket();
  }
}

void setup()
{
  Serial.setTxBufferSize(32768);
  // Bộ đệm nhận lớn: âm thanh tới 32KB/giây, trong lúc loop() bận vẽ mặt (~30ms) vẫn
  // phải có chỗ chứa ~1KB tiếng mới về.
  Serial.setRxBufferSize(16384);
  Serial.begin(SERIAL_BAUD);
  serialLock = xSemaphoreCreateMutex();
  audioBuf = xStreamBufferCreate(32768, 1);
  delay(300);

  if (!faceBegin())
  {
    logLine("LOI: khong du RAM cho canvas mat");
  }
  faceSetExpression("sleepy");
  faceSetCaption("CHO LAPTOP...");

  if (strlen(WIFI_SSID) > 0)
  {
    // Không chờ WiFi ở đây: dây USB vẫn dùng được ngay, WiFi tự nối dần (serviceWifi()).
    WiFi.persistent(false); // không ghi tên/mật khẩu WiFi vào flash mỗi lần begin()
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false); // tắt tiết kiệm điện WiFi: ảnh đi đều, lệnh tới nhanh
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }

  ampReady = setupAmp();
  if (ampReady)
  {
    xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, 2, nullptr, 1);
  }
  else
  {
    logLine("LOI: khoi tao I2S loa that bai");
  }

  micReady = setupMic();
  if (micReady)
  {
    xTaskCreatePinnedToCore(micTask, "mic", 4096, nullptr, 1, nullptr, 0);
  }
  else
  {
    logLine("LOI: khoi tao I2S mic that bai");
  }

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
  logLine(String("Camera + man hinh OK, loa ") + (ampReady ? "OK" : "LOI") +
          ", mic " + (micReady ? "OK" : "LOI"));
  xTaskCreatePinnedToCore(cameraTask, "camera", 8192, nullptr, 1, nullptr, 0);
}

void loop()
{
  serviceWifi();
  readCommands(Serial, usbParser);
  if (clientOn)
  {
    readCommands(client, wifiParser);
  }
  faceTick();
  delay(1);
}
