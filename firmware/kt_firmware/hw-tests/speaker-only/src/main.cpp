#include <Arduino.h>
#include <driver/i2s.h>

// ---------------------------------------------------------------------------
// speaker-only — kiểm tra RIÊNG khuếch đại MAX98357 + loa 8Ω, KHÔNG dùng mic.
//
// Vì sao: tiếng phát ra là sóng sin do chính code tính ra → sạch tuyệt đối. Nếu loa vẫn
// rè thì chắc chắn lỗi nằm ở đường ra (loa / mạch khuếch đại / nguồn / dây), không phải mic.
//
// Mở Serial Monitor (115200). Lúc khởi động board tự chạy 1 lượt 8 bài, mỗi bài in ra
// "nghe gì là bình thường". Sau đó gõ phím để phát lại từng bài:
//   0..7  phát bài tương ứng (lặp lại tới khi gõ phím khác)
//   a     chạy lại cả lượt 8 bài
//   s     dừng (im lặng)
//   + / - tăng / giảm âm lượng tổng (bài đang lặp vẫn phát tiếp)
//
// Chỉ cần nối khuếch đại: VIN→5V (hoặc 3V3, xem README), GND→GND, BCLK→47, LRC→48, DIN→21,
// loa vào 2 cực +/− của module. KHÔNG cần nối mic.
// ---------------------------------------------------------------------------
#define AMP_BCLK 47
#define AMP_LRC 48
#define AMP_DIN 21

#define SAMPLE_RATE 16000 // giống tần số robot dùng thật cho giọng nói

struct Test
{
  const char *name;
  float freqStart; // Hz, 0 = im lặng
  float freqEnd;   // khác freqStart = quét tần số
  float volume;    // 0..1 so với mức to nhất
  float seconds;
  const char *listenFor;
};

static const Test TESTS[] = {
    {"Im lang (gui toan so 0)", 0, 0, 0, 4,
     "Phai IM HOAN TOAN (ghe sat tai chi nghe xi rat nho). Nghe u/re/lach tach -> loi NGUON hoac MACH KHUECH DAI, khong phai loa/mic."},
    // Cập nhật: tăng âm lượng các bài (bản đầu 5/20/60% nghe quá nhỏ trên loa thật).
    {"Bip 440Hz - NHO (15%)", 440, 440, 0.15f, 2.5f,
     "Tieng 'tu' tron, nho, deu. Re ngay o muc nho -> LOA hong (mang rach / cuon day co) hoac mach khuech dai hong."},
    {"Bip 440Hz - VUA (45%)", 440, 440, 0.45f, 2.5f,
     "Nhu tren, to hon, van tron."},
    {"Bip 440Hz - TO (90%)", 440, 440, 0.90f, 2.5f,
     "Re CHI o muc nay ma nho/vua thi sach -> qua tai: nguon yeu (VIN 3V3) hoac loa cong suat nho. Board tu reset -> sut nguon."},
    {"Bip 1000Hz - VUA", 1000, 1000, 0.45f, 2.5f,
     "Tieng 'tit' cao, sach."},
    {"Am tram 150Hz - VUA", 150, 150, 0.60f, 3,
     "Tieng 'u' tram. Nghe lach xach / re rung -> mang loa rach, hoac loa cham vo/day/vat gi do."},
    {"Quet 100Hz -> 5000Hz", 100, 5000, 0.45f, 5,
     "Tieng tang dan deu tu tram len cao. Re o 1 doan tan so -> mang loa hong hoac vo loa cong huong."},
    {"Giai dieu 5 not", -1, -1, 0.60f, 2.5f,
     "Do-Re-Mi-Fa-Sol ro rang, khong re."},
};

// Âm lượng tổng, nhân vào mọi bài. Gõ '+' / '-' trong Monitor để đổi lúc đang chạy.
// Mẫu âm thanh không được vượt ±32767 (giới hạn của số 16-bit), nên kết quả cuối được
// kẹp lại; vặn quá to sẽ bị "cắt đỉnh" và nghe rè: đó là do vặn quá, không phải loa hư.
static float masterVolume = 1.0f;
static const int TEST_COUNT = sizeof(TESTS) / sizeof(TESTS[0]);

static bool setupAmp()
{
  // Gửi STEREO, cùng 1 mẫu cho cả kênh trái và phải. MAX98357 mặc định trộn (trái+phải)/2
  // → ra đúng mẫu đó. Không dùng ONLY_LEFT như mic-selftest: chế độ mono đó trên ESP32-S3
  // có lúc xếp sai khung → tự sinh méo, dễ nhầm là loa hư.
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
      .tx_desc_auto_clear = true, // hết dữ liệu thì tự phát số 0 (im), không lặp khối cũ gây rè
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

// Trả về true nếu người dùng vừa gõ phím (để bài đang phát dừng sớm).
static int pendingKey = -1;
static bool keyPressed()
{
  if (pendingKey < 0 && Serial.available())
  {
    int c = Serial.read();
    if (c != '\r' && c != '\n')
    {
      pendingKey = c;
    }
  }
  return pendingKey >= 0;
}

static const float MELODY[] = {262, 294, 330, 349, 392}; // Do Re Mi Fa Sol

// Phát 1 bài. Có "fade" 15ms ở đầu và cuối: bật/tắt sóng đột ngột tạo tiếng "bụp/tách"
// — tiếng đó là do code, không phải loa hư, nên làm mềm đi để khỏi nghe nhầm.
static void playTest(const Test &t)
{
  const int total = (int)(t.seconds * SAMPLE_RATE);
  const int fade = SAMPLE_RATE * 15 / 1000;
  const int noteLen = SAMPLE_RATE / 2;
  float phase = 0;
  int16_t frame[256 * 2]; // 256 mẫu × 2 kênh
  int i = 0;
  while (i < total && !keyPressed())
  {
    int n = 0;
    for (; n < 256 && i < total; n++, i++)
    {
      float freq;
      float env = 1.0f;
      if (t.freqStart < 0)
      {
        // Giai điệu: mỗi nốt 0,5 giây, fade riêng từng nốt.
        freq = MELODY[min(i / noteLen, 4)];
        int k = i % noteLen;
        env = min(1.0f, min(k, noteLen - k) / (float)fade);
      }
      else
      {
        // Quét tần số theo hàm mũ: tai người nghe "đều" theo cấp số nhân, không phải cộng.
        freq = t.freqStart * powf(t.freqEnd / t.freqStart, (float)i / total);
      }
      env = min(env, min(1.0f, min(i, total - i) / (float)fade));
      int16_t s = 0;
      if (t.freqStart != 0)
      {
        phase += 2.0f * PI * freq / SAMPLE_RATE;
        if (phase > 2.0f * PI)
          phase -= 2.0f * PI;
        float v = sinf(phase) * t.volume * masterVolume * env * 32767.0f;
        s = (int16_t)constrain(v, -32767.0f, 32767.0f);
      }
      frame[2 * n] = s;     // kênh trái
      frame[2 * n + 1] = s; // kênh phải
    }
    size_t written = 0;
    i2s_write(I2S_NUM_1, frame, n * 2 * sizeof(int16_t), &written, portMAX_DELAY);
  }
  i2s_zero_dma_buffer(I2S_NUM_1);
}

static void announce(int idx)
{
  Serial.println();
  Serial.printf("[%d] %s\n", idx, TESTS[idx].name);
  Serial.printf("    Binh thuong: %s\n", TESTS[idx].listenFor);
}

static void runAll()
{
  Serial.println();
  Serial.println("===== Chay lan luot 8 bai (go phim bat ky de ngat) =====");
  for (int k = 0; k < TEST_COUNT && !keyPressed(); k++)
  {
    announce(k);
    playTest(TESTS[k]);
    delay(400);
  }
  Serial.println();
  Serial.println("Xong. Go 0-7 de phat lai 1 bai, 'a' chay lai ca luot, 's' dung, '+'/'-' tang/giam am luong.");
}

void setup()
{
  Serial.begin(115200);
  delay(800);
  Serial.println();
  Serial.println("=== speaker-only: test RIENG khuech dai + loa (khong dung mic) ===");
  if (!setupAmp())
  {
    Serial.println("LOI: khoi tao I2S that bai");
    return;
  }
  runAll();
}

void loop()
{
  static int looping = -1; // bài đang phát lặp lại, -1 = không phát
  keyPressed();
  if (pendingKey >= 0)
  {
    int c = pendingKey;
    pendingKey = -1;
    if (c >= '0' && c < '0' + TEST_COUNT)
    {
      looping = c - '0';
      announce(looping);
      Serial.println("    (phat lap lai, go phim khac de doi / 's' de dung)");
    }
    else if (c == 'a')
    {
      looping = -1;
      runAll();
    }
    else if (c == 's')
    {
      looping = -1;
      i2s_zero_dma_buffer(I2S_NUM_1);
      Serial.println("Da dung.");
    }
    else if (c == '+' || c == '-')
    {
      masterVolume = constrain(masterVolume + (c == '+' ? 0.25f : -0.25f), 0.25f, 3.0f);
      Serial.printf("Am luong tong: x%.2f%s\n", masterVolume,
                    masterVolume > 1.0f ? " (bai to co the bi cat dinh -> re do vang qua to)" : "");
    }
  }
  if (looping >= 0)
  {
    playTest(TESTS[looping]);
  }
  else
  {
    delay(20);
  }
}
