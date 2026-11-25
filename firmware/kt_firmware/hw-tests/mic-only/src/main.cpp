#include <Arduino.h>
#include <driver/i2s.h>

// ---------------------------------------------------------------------------
// mic-only — kiểm tra RIÊNG mic INMP441 để biết mic có hư không.
//
// Vì sao không phát ra loa robot như mic-selftest: nếu loa robot (hoặc mạch khuếch đại) hư
// thì nghe rè dù mic tốt → không biết lỗi ở đâu. Ở đây âm thanh đi qua dây USB lên laptop,
// nghe bằng loa laptop (chắc chắn tốt). Nghe rè → lỗi ở mic; nghe sạch → mic tốt.
//
// Cũng KHÔNG qua bộ lọc DSP nào (mic-selftest có lọc DC, khử đột biến, cổng nhiễu): bộ lọc
// có thể tự gây méo, mà ta cần nghe đúng tín hiệu THÔ của mic.
//
// 2 việc:
//  1. Mỗi 0,5 giây in 1 dòng số đo (laptop hoặc Serial Monitor đọc được):
//     "STAT dc=.. rms=.. peak=.. clip=..% stuck=.."
//  2. Laptop gửi "rec <giây>\n" → board gửi "PCM <số byte>\n" rồi đúng chừng đó byte âm thô
//     (16-bit, 16kHz, mono). Laptop lưu thành file .wav để nghe lại.
//
// Chỉ cần nối mic: VDD→3V3, GND→GND, L/R→GND, SCK→40, WS→41, SD→42. KHÔNG cần nối loa.
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 921600

#define MIC_SCK 40
#define MIC_WS 41
#define MIC_SD 42

#define SAMPLE_RATE 16000
#define MAX_REC_SEC 10

static bool setupMic()
{
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT, // INMP441 gửi 24-bit nằm trong khung 32-bit
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,   // chân L/R của mic nối GND = kênh trái
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = 8,
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

  return i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL) == ESP_OK &&
         i2s_set_pin(I2S_NUM_0, &pins) == ESP_OK;
}

// Đọc 1 khối mẫu từ mic, đổi về 16-bit. Trả về số mẫu đọc được.
// ">> 16": giữ 16 bit cao nhất của khung 32-bit — đủ dùng, và giống cách mic-selftest làm
// nên bản ghi ở đây phản ánh đúng thứ đã từng phát ra loa.
static int readBlock(int16_t *out, int maxSamples)
{
  static int32_t raw[512];
  int want = min(maxSamples, 512);
  size_t bytesRead = 0;
  i2s_read(I2S_NUM_0, raw, want * sizeof(int32_t), &bytesRead, pdMS_TO_TICKS(100));
  int n = bytesRead / sizeof(int32_t);
  for (int i = 0; i < n; i++)
  {
    out[i] = (int16_t)(raw[i] >> 16);
  }
  return n;
}

// Ghi âm và gửi thẳng qua USB, từng khối nhỏ — không cần bộ nhớ lớn để chứa cả bản ghi.
static void record(int seconds)
{
  seconds = constrain(seconds, 1, MAX_REC_SEC);
  uint32_t total = (uint32_t)seconds * SAMPLE_RATE;
  Serial.printf("PCM %lu\n", (unsigned long)(total * 2));
  static int16_t block[512];
  uint32_t sent = 0;
  while (sent < total)
  {
    int n = readBlock(block, min<uint32_t>(512, total - sent));
    if (n <= 0)
    {
      continue;
    }
    Serial.write((const uint8_t *)block, n * 2);
    sent += n;
  }
  Serial.println();
  Serial.println("END");
}

// Số đo trong 0,5 giây:
//  dc    = giá trị trung bình. Mic tốt dao động quanh 0; lệch rất xa (vd hàng nghìn) và
//          đứng yên → chân SD/L-R nối sai hoặc mic hỏng.
//  rms   = độ ồn trung bình. Phòng im lặng mà rms cao bất thường → mic/dây gây nhiễu.
//  peak  = mẫu to nhất. Nói to mà peak gần 0 → mic "điếc".
//  clip  = % mẫu chạm trần ±32767 → méo vì quá to (nói sát mic quá).
//  stuck = % mẫu y hệt mẫu trước. Gần 100% → không có tín hiệu (dây SD lỏng, mic chết).
static void printStats(const int16_t *buf, int n)
{
  if (n <= 0)
  {
    Serial.println("STAT loi: khong doc duoc mau nao tu mic (kiem tra day SCK/WS)");
    return;
  }
  double sum = 0, sumSq = 0;
  int32_t peak = 0, clip = 0, stuck = 0;
  for (int i = 0; i < n; i++)
  {
    sum += buf[i];
  }
  double dc = sum / n;
  for (int i = 0; i < n; i++)
  {
    double v = buf[i] - dc;
    sumSq += v * v;
    int32_t a = abs((int32_t)buf[i]);
    if (a > peak)
      peak = a;
    if (a >= 32700)
      clip++;
    if (i > 0 && buf[i] == buf[i - 1])
      stuck++;
  }
  Serial.printf("STAT dc=%d rms=%d peak=%ld clip=%.1f%% stuck=%.0f%%\n",
                (int)dc, (int)sqrt(sumSq / n), (long)peak,
                100.0 * clip / n, 100.0 * stuck / n);
}

void setup()
{
  Serial.setRxBufferSize(256);
  Serial.setTxBufferSize(8192);
  Serial.begin(SERIAL_BAUD);
  delay(500);
  Serial.println();
  Serial.println("=== mic-only: test RIENG mic INMP441 (khong dung loa robot) ===");
  if (!setupMic())
  {
    Serial.println("LOI: khoi tao I2S that bai");
    return;
  }
  Serial.println("Mic OK. Chay ghi-am-mic.bat tren laptop de ghi am va nghe lai.");
  // Bỏ ~0,3 giây đầu: INMP441 cần thời gian ổn định sau khi có xung clock, mẫu đầu toàn rác.
  static int16_t warm[512];
  for (int i = 0; i < 10; i++)
  {
    readBlock(warm, 512);
  }
}

// Lệnh từ laptop: "rec 5\n". Ghép từng ký tự để không bị đứng chờ như readStringUntil().
static void readCommand()
{
  static char line[32];
  static size_t len = 0;
  while (Serial.available())
  {
    char c = (char)Serial.read();
    if (c == '\r')
      continue;
    if (c != '\n')
    {
      if (len < sizeof(line) - 1)
        line[len++] = c;
      continue;
    }
    line[len] = '\0';
    len = 0;
    if (strncmp(line, "rec ", 4) == 0)
    {
      record(atoi(line + 4));
    }
  }
}

void loop()
{
  readCommand();

  // Gom ~0,5 giây mẫu (8000 mẫu) rồi in số đo 1 lần.
  static int16_t window[SAMPLE_RATE / 2];
  static int filled = 0;
  int n = readBlock(window + filled, SAMPLE_RATE / 2 - filled);
  if (n == 0 && filled == 0)
  {
    printStats(window, 0);
    delay(500);
    return;
  }
  filled += n;
  if (filled >= SAMPLE_RATE / 2)
  {
    printStats(window, filled);
    filled = 0;
  }
}
