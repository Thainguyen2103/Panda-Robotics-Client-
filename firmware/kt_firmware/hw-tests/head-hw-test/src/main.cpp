#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

// ---------------------------------------------------------------------------
// head-hw-test — firmware TEST PHẦN CỨNG cho board HEAD thật, dùng tối nay khi lắp mic +
// khuếch đại. KHÔNG liên quan tới firmware-demo/ (project Wokwi cho màn hình mắt).
//
// Vì sao dùng driver/i2s.h (ESP-IDF) thay vì thư viện I2S.h như audio_i2s.cpp cũ:
// thư viện Arduino I2S.h chỉ điều khiển được 1 cổng I2S tại một thời điểm. Ở đây cần CẢ
// mic (nhận) VÀ khuếch đại (gửi) chạy cùng lúc cho lệnh "loop" — ESP32-S3 có 2 cổng phần
// cứng độc lập (I2S_NUM_0, I2S_NUM_1), driver/i2s.h mới cho phép dùng cả hai song song.
//
// 6 chân GPIO dưới đây khớp đúng với trang hướng dẫn lắp dây (panda-head-wiring.html) —
// đổi dây thì nhớ đổi số ở đây theo đúng số đã đổi.
// ---------------------------------------------------------------------------

// Đổi từ GPIO4/5/6/7/8/9 (bản đầu) sang nhóm này ngày 23/09 — sau khi test thật xác nhận
// camera OV3660 chiếm đúng GPIO4-13 + 15-18, bộ chân cũ đá thẳng vào camera. Nhóm mới dưới
// đây tránh sạch camera VÀ 5 chân của màn hình TFT (GPIO1/2/14/38/39) — xem "Đã chốt theo
// ảnh board thật" trong panda-head-wiring.html để thấy đủ cả 3 nhóm không đè lên nhau.
#define MIC_SCK 40  // BCLK — xung nhịp bit, ESP32 phát ra
#define MIC_WS 41   // WS/LRC — chọn khung trái/phải, ESP32 phát ra
#define MIC_SD 42   // SD — dữ liệu âm thanh, mic phát vào ESP32 (input-only theo hướng này)

#define AMP_BCLK 47 // BCLK của khuếch đại — ESP32 phát ra
#define AMP_LRC 48  // LRC của khuếch đại — ESP32 phát ra
#define AMP_DIN 21  // DIN — dữ liệu ESP32 gửi ra khuếch đại

#define SAMPLE_RATE 16000

static bool micReady = false;
static bool ampReady = false;

// ---------------------------------------------------------------------------
// Khởi tạo mic ở cổng I2S_NUM_0, chế độ NHẬN (RX).
//
// bits_per_sample = 32: INMP441 thật ra chỉ có 24 bit dữ liệu, nhưng đóng gói trong khung
// 32-bit và CĂN TRÁI (dữ liệu thật nằm ở 24 bit cao). Khai 16-bit ở đây sẽ đọc ra rác vì
// phần cứng mic không hỗ trợ khung 16-bit — đây là lỗi rất hay gặp khi mới ráp I2S.
// ---------------------------------------------------------------------------
static bool setupMic()
{
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT, // chân L/R của mic đã nối GND = kênh trái
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      // Tăng tu 4x256 len 12x512 (~192ms dem thay vi ~64ms) — them khoang du phong chong rot
      // mau khi vong lap loopback ban ron ghi ra loa giua 2 lan doc mic.
      .dma_buf_count = 12,
      .dma_buf_len = 512,
      .use_apll = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk = 0};

  i2s_pin_config_t pins = {
      .mck_io_num = I2S_PIN_NO_CHANGE,
      .bck_io_num = MIC_SCK,
      .ws_io_num = MIC_WS,
      .data_out_num = I2S_PIN_NO_CHANGE,
      .data_in_num = MIC_SD};

  bool ok = i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL) == ESP_OK;
  ok = ok && i2s_set_pin(I2S_NUM_0, &pins) == ESP_OK;
  Serial.print("[mic] Khoi tao I2S0 (SCK=");
  Serial.print(MIC_SCK);
  Serial.print(" WS=");
  Serial.print(MIC_WS);
  Serial.print(" SD=");
  Serial.print(MIC_SD);
  Serial.print("): ");
  Serial.println(ok ? "OK" : "THAT BAI");
  return ok;
}

// Khởi tạo khuếch đại ở cổng I2S_NUM_1, chế độ GỬI (TX), 16-bit — MAX98357 chấp nhận cả
// 16 lẫn 32-bit nhưng 16-bit là cấu hình phổ biến nhất trong các ví dụ mẫu, dễ debug hơn.
static bool setupAmp()
{
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 12,
      .dma_buf_len = 512,
      .use_apll = false,
      .tx_desc_auto_clear = true, // tự chèn 0 khi buffer cạn, tránh tiếng rè khi ngừng gửi
      .fixed_mclk = 0};

  i2s_pin_config_t pins = {
      .mck_io_num = I2S_PIN_NO_CHANGE,
      .bck_io_num = AMP_BCLK,
      .ws_io_num = AMP_LRC,
      .data_out_num = AMP_DIN,
      .data_in_num = I2S_PIN_NO_CHANGE};

  bool ok = i2s_driver_install(I2S_NUM_1, &cfg, 0, NULL) == ESP_OK;
  ok = ok && i2s_set_pin(I2S_NUM_1, &pins) == ESP_OK;
  Serial.print("[amp] Khoi tao I2S1 (BCLK=");
  Serial.print(AMP_BCLK);
  Serial.print(" LRC=");
  Serial.print(AMP_LRC);
  Serial.print(" DIN=");
  Serial.print(AMP_DIN);
  Serial.print("): ");
  Serial.println(ok ? "OK" : "THAT BAI");
  return ok;
}

// ---------------------------------------------------------------------------
// Lệnh "tone": phát 1 nốt 440Hz (nốt La) ra loa trong 1.5 giây, TỰ TÍNH sóng sin —
// không cần file âm thanh nào. Đây là bài test đơn giản nhất cho đường ra: nếu nghe được
// tiếng bíp rõ ràng, cả module khuếch đại lẫn loa đều đang ổn.
// ---------------------------------------------------------------------------
static void runTone()
{
  if (!ampReady)
  {
    Serial.println("[tone] Khuech dai chua san sang, kiem tra day AMP_BCLK/AMP_LRC/AMP_DIN.");
    return;
  }
  Serial.println("[tone] Phat 440Hz trong 1.5 giay...");

  const float freq = 440.0f;
  const int totalSamples = SAMPLE_RATE * 3 / 2; // 1.5 giây
  const int chunk = 256;
  int16_t buf[chunk];
  size_t written;

  for (int base = 0; base < totalSamples; base += chunk)
  {
    for (int i = 0; i < chunk; i++)
    {
      float t = (float)(base + i) / SAMPLE_RATE;
      // Biên độ 0.3 lần full-scale để không quá to/rè khi loa nhỏ.
      buf[i] = (int16_t)(sinf(2.0f * PI * freq * t) * 0.3f * 32767.0f);
    }
    i2s_write(I2S_NUM_1, buf, sizeof(buf), &written, portMAX_DELAY);
  }
  Serial.println("[tone] Xong. Nghe duoc tieng biip khong?");
}

// ---------------------------------------------------------------------------
// Lệnh "mic": đọc mic trong 5 giây, in ra biên độ đỉnh mỗi 200ms dạng thanh "#" — vỗ tay
// hoặc nói to thì thanh phải dài ra rõ rệt, im lặng thì gần như không có gì.
// ---------------------------------------------------------------------------
static void runMicTest()
{
  if (!micReady)
  {
    Serial.println("[mic] Mic chua san sang, kiem tra day MIC_SCK/MIC_WS/MIC_SD.");
    return;
  }
  Serial.println("[mic] Dang nghe 5 giay — thu vo tay hoac noi to...");

  const int32_t bufLen = 256;
  int32_t buf[bufLen];
  unsigned long start = millis();
  unsigned long lastPrint = 0;
  int32_t windowPeak = 0;

  while (millis() - start < 5000)
  {
    size_t bytesRead = 0;
    i2s_read(I2S_NUM_0, buf, sizeof(buf), &bytesRead, 100 / portTICK_PERIOD_MS);
    int samples = bytesRead / sizeof(int32_t);
    for (int i = 0; i < samples; i++)
    {
      // Dữ liệu 24-bit căn trái trong khung 32-bit -> dịch phải 11 bit để ra biên độ
      // dễ đọc (khoảng 0..~130000), không cần chính xác tuyệt đối cho việc test này.
      int32_t v = abs(buf[i] >> 11);
      if (v > windowPeak)
        windowPeak = v;
    }

    if (millis() - lastPrint >= 200)
    {
      lastPrint = millis();
      int bars = constrain(windowPeak / 2000, 0, 40);
      Serial.print("[mic] ");
      for (int i = 0; i < bars; i++)
        Serial.print('#');
      Serial.print("  (dinh=");
      Serial.print(windowPeak);
      Serial.println(")");
      windowPeak = 0;
    }
  }
  Serial.println("[mic] Xong.");
}

// ---------------------------------------------------------------------------
// Lệnh "loop": đọc mic, chuyển sang định dạng của khuếch đại, gửi ra loa NGAY LẬP TỨC —
// nói vào mic nghe ra loa gần như tức thời. Đây là bài test gộp cả 2 module cùng lúc.
// Bấm phím bất kỳ trên Serial Monitor để dừng.
// ---------------------------------------------------------------------------
static void runLoopback()
{
  if (!micReady || !ampReady)
  {
    Serial.println("[loop] Can ca mic lan khuech dai san sang truoc.");
    return;
  }
  Serial.println("[loop] Dang lap mic->loa. Go Enter de dung.");

  const int32_t inLen = 512;
  int32_t inBuf[inLen];
  int16_t outBuf[inLen];

  // 3 bo loc DSP giong het mic-selftest — trang thai phai nam NGOAI vong lap doc de nho
  // duoc giua cac lan doc, dung ban chat bo loc IIR (dau ra phu thuoc mau qua khu).
  float dcPrevX = 0.0f, dcPrevY = 0.0f;
  const float DC_R = 0.995f; // (1) loc chan DC — R cang gan 1, tan so cat cang thap
  int16_t despikePrev = 0;
  const int16_t MAX_JUMP = 6000; // (2) khu dot bien — keo mau nhay xa ve gan mau truoc
  const int16_t NOISE_FLOOR = 200; // (3) cong nhieu mem — nen tap am nen ve 0 theo ham bac 2

  while (!Serial.available())
  {
    size_t bytesRead = 0;
    i2s_read(I2S_NUM_0, inBuf, sizeof(inBuf), &bytesRead, 50 / portTICK_PERIOD_MS);
    int samples = bytesRead / sizeof(int32_t);
    for (int i = 0; i < samples; i++)
    {
      // Rút 32-bit (24-bit thật, căn trái) xuống 16-bit cho khuếch đại: dịch phải 16 bit.
      int16_t raw = (int16_t)(inBuf[i] >> 16);

      float dcOut = (float)raw - dcPrevX + DC_R * dcPrevY;
      dcPrevX = (float)raw;
      dcPrevY = dcOut;
      int32_t v = (int32_t)dcOut;

      int32_t diff = v - despikePrev;
      if (diff > MAX_JUMP)
        v = despikePrev + MAX_JUMP;
      else if (diff < -MAX_JUMP)
        v = despikePrev - MAX_JUMP;
      despikePrev = (int16_t)v;

      int32_t av = abs(v);
      if (av < NOISE_FLOOR)
      {
        v = (int32_t)(v * ((float)av / (float)NOISE_FLOOR));
      }

      if (v > 32767)
        v = 32767;
      if (v < -32768)
        v = -32768;
      outBuf[i] = (int16_t)v;
    }
    size_t written = 0;
    i2s_write(I2S_NUM_1, outBuf, samples * sizeof(int16_t), &written, portMAX_DELAY);
  }
  while (Serial.available())
    Serial.read(); // xả hết phím Enter vừa gõ để không lẫn vào lệnh kế tiếp
  Serial.println("[loop] Da dung.");
}

// ---------------------------------------------------------------------------
// Lệnh "cam": CHƯA LÀM — cần biết đúng model/board camera để lấy đúng chân nội bộ của khe
// FPC (khe cắm cáp không đi qua dây jumper nên không thể suy ra chân từ ảnh mặt ngoài
// board). Gửi tên/link sản phẩm board ESP32-S3 (hoặc board OV3660) là điền được ngay.
// ---------------------------------------------------------------------------
static void runCamTest()
{
  Serial.println("[cam] Chua ho tro — can biet model board de lay dung chan FPC camera.");
  Serial.println("[cam] Gui ten/link san pham board cho Claude de bo sung lenh nay.");
}

static void handleCommand(const String &cmdRaw)
{
  String cmd = cmdRaw;
  cmd.trim();
  if (cmd == "tone")
    runTone();
  else if (cmd == "mic")
    runMicTest();
  else if (cmd == "loop")
    runLoopback();
  else if (cmd == "cam")
    runCamTest();
  else if (cmd.length() > 0)
    Serial.println("[main] Lenh khong hop le. Dung: tone | mic | loop | cam");
}

void setup()
{
  Serial.begin(115200);
  delay(300); // chờ cổng Serial ổn định trước khi in dòng đầu tiên, tránh mất log lúc mới cắm USB
  Serial.println();
  Serial.println("=== head-hw-test: firmware kiem tra mic + khuech dai board HEAD ===");

  micReady = setupMic();
  ampReady = setupAmp();

  Serial.println("San sang. Go 1 trong 4 lenh roi Enter: tone | mic | loop | cam");
}

void loop()
{
  if (Serial.available())
  {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }
  delay(1); // nhường CPU cho FreeRTOS, giống nguyên tac da hoc o firmware-demo/main.cpp
}
