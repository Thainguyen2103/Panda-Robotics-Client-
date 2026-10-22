#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <driver/i2s.h>

// ---------------------------------------------------------------------------
// mic-selftest — mic INMP441 -> loa thật (MAX98357 + loa 8Ω) NGAY LẬP TỨC, liên tục,
// không cần gõ lệnh gì cả — cắm điện, nối đủ dây là nói vào mic nghe ra loa luôn.
//
// Cập nhật 23/09: ban đầu file này chỉ phát ngược ra WiFi cho máy tính/điện thoại nghe
// (lúc đó chưa lắp khuếch đại+loa). Giờ đã lắp đủ nên thêm hẳn đường ra loa thật qua I2S —
// KHÔNG CẦN WiFi/trình duyệt nữa vẫn nghe được, tính năng WiFi cũ vẫn giữ lại làm cách
// nghe thứ 2 (tiện lúc loa chưa lắp hoặc muốn nghe qua tai nghe điện thoại).
//
// 6 chân dưới đây khớp "Sơ đồ 1/3" và "Sơ đồ 2/3" trong panda-head-wiring.html.
// ---------------------------------------------------------------------------
#define MIC_SCK 40
#define MIC_WS 41
#define MIC_SD 42

#define AMP_BCLK 47
#define AMP_LRC 48
#define AMP_DIN 21

#define SAMPLE_RATE 16000

static const char *AP_SSID = "PANDA-MIC-TEST";
static WebServer server(80);
static bool micReady = false;
static bool ampReady = false;

static bool setupMic()
{
  i2s_config_t cfg = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT, // INMP441 la 24-bit can trai trong khung 32-bit
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,   // chan L/R cua mic da noi GND = kenh trai
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
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
// 3 bộ lọc DSP — trạng thái đặt Ở CẤP FILE (không phải trong hàm) để dùng chung, liên tục
// giữa mọi lần gọi (bản chất bộ lọc IIR: đầu ra phụ thuộc mẫu quá khứ, không phải chỉ mẫu
// hiện tại — cắt rời trạng thái giữa các lần gọi sẽ tạo tiếng "giật" ở mỗi lần cắt).
// ---------------------------------------------------------------------------
static float dcPrevX = 0.0f, dcPrevY = 0.0f;
static const float DC_R = 0.995f; // (1) loc chan DC (thong cao rat thap) — bo loi lech tam tin hieu
static int16_t despikePrev = 0;
static const int16_t MAX_JUMP = 6000; // (2) khu dot bien — keo mau nhay xa ve gan mau truoc
static const int16_t NOISE_FLOOR = 200; // (3) cong nhieu mem — nen tap am nen ve 0 theo ham bac 2

static int16_t processSample(int16_t raw)
{
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
  return (int16_t)v;
}

static void handleRoot()
{
  String html =
      "<html><head>"
      "<meta name='viewport' content='width=device-width, initial-scale=1'>"
      "</head>"
      "<body style='font-family:sans-serif;text-align:center;background:#111;color:#eee;padding-top:60px'>"
      "<h2>PANDA MIC TEST</h2>"
      "<p>Loa that tren board da tu phat lien tuc, khong can bam gi o day ca.</p>"
      "<p>Nut duoi day chi de nghe THEM qua chinh may nay (VD tai nghe dien thoai).</p>"
      "<button id='startBtn' style='font-size:18px;padding:14px 28px;border-radius:10px;"
      "border:none;background:#0e7c86;color:#fff'>Nghe them qua may nay</button>"
      "<p id='status' style='color:#888;font-size:13px;margin-top:20px'></p>"
      "<script>"
      "const btn = document.getElementById('startBtn');"
      "const status = document.getElementById('status');"
      "btn.addEventListener('click', async () => {"
      "  btn.disabled = true; btn.textContent = 'Dang nghe...';"
      "  const AudioCtx = window.AudioContext || window.webkitAudioContext;"
      "  const ctx = new AudioCtx();"
      "  await ctx.resume();"
      "  const sampleRate = " +
      String(SAMPLE_RATE) + ";"
                             "  let nextTime = 0;"
                             "  try {"
                             "    const CHUNK_SAMPLES = " +
      String(SAMPLE_RATE / 4) + ";" // ~250ms mỗi khối phát
                                 "    const res = await fetch('/mic.raw');"
                                 "    const reader = res.body.getReader();"
                                 "    let leftoverBytes = new Uint8Array(0);"
                                 "    let pending = [];"
                                 "    let firstBuffer = true;"
                                 "    const FADE_S = 0.008;"
                                 "    const flush = () => {"
                                 "      if (pending.length < CHUNK_SAMPLES) return;"
                                 "      const samples = pending.splice(0, CHUNK_SAMPLES);"
                                 "      const buf = ctx.createBuffer(1, samples.length, sampleRate);"
                                 "      const ch = buf.getChannelData(0);"
                                 "      for (let i = 0; i < samples.length; i++) ch[i] = samples[i] / 32768;"
                                 "      const src = ctx.createBufferSource();"
                                 "      const gain = ctx.createGain();"
                                 "      src.buffer = buf; src.connect(gain); gain.connect(ctx.destination);"
                                 "      let startAt = Math.max(ctx.currentTime, nextTime);"
                                 "      if (firstBuffer) { startAt = ctx.currentTime + 0.2; firstBuffer = false; }"
                                 "      const dur = buf.duration;"
                                 "      gain.gain.setValueAtTime(0, startAt);"
                                 "      gain.gain.linearRampToValueAtTime(1, startAt + FADE_S);"
                                 "      gain.gain.setValueAtTime(1, startAt + dur - FADE_S);"
                                 "      gain.gain.linearRampToValueAtTime(0, startAt + dur);"
                                 "      src.start(startAt);"
                                 "      nextTime = startAt + dur - FADE_S;"
                                 "      status.textContent = 'Dang phat...';"
                                 "    };"
                                 "    while (true) {"
                                 "      const { done, value } = await reader.read();"
                                 "      if (done) break;"
                                 "      const combined = new Uint8Array(leftoverBytes.length + value.length);"
                                 "      combined.set(leftoverBytes); combined.set(value, leftoverBytes.length);"
                                 "      const usable = combined.length - (combined.length % 2);"
                                 "      leftoverBytes = combined.slice(usable);"
                                 "      if (usable === 0) continue;"
                                 "      const samples = new Int16Array(combined.buffer, combined.byteOffset, usable / 2);"
                                 "      for (let i = 0; i < samples.length; i++) pending.push(samples[i]);"
                                 "      while (pending.length >= CHUNK_SAMPLES) flush();"
                                 "    }"
                                 "  } catch (e) { status.textContent = 'Loi: ' + e; }"
                                 "});"
                             "</script>"
                             "</body></html>";
  server.send(200, "text/html", html);
}

// /mic.raw — nếu có trình duyệt kết nối, hàm này giữ nguyên 1 kết nối HTTP để phát thêm
// qua đó — NHƯNG loa thật vẫn phát riêng, độc lập, không phụ thuộc vào việc có ai mở
// trang này hay không (xem localLoopbackTick() bên dưới, chạy trong loop() chính).
static void handleMicStream()
{
  if (!micReady)
  {
    server.send(503, "text/plain", "Mic chua san sang");
    return;
  }

  WiFiClient client = server.client();
  client.print("HTTP/1.1 200 OK\r\n");
  client.print("Content-Type: application/octet-stream\r\n");
  client.print("Connection: close\r\n\r\n");

  Serial.println("[mic] Co nguoi mo trinh duyet nghe them...");

  const int bufLen = 1024;
  int32_t inBuf[bufLen];
  int16_t outBuf[bufLen];

  while (client.connected())
  {
    size_t bytesRead = 0;
    i2s_read(I2S_NUM_0, inBuf, sizeof(inBuf), &bytesRead, 100 / portTICK_PERIOD_MS);
    int samples = bytesRead / sizeof(int32_t);
    if (samples == 0)
    {
      continue;
    }
    for (int i = 0; i < samples; i++)
    {
      int16_t raw = (int16_t)(inBuf[i] >> 16); // 24-bit can trai trong khung 32-bit -> dich phai 16 bit
      outBuf[i] = processSample(raw);
    }

    // Loa that: ghi truoc, khong cho ket qua (portMAX_DELAY o day an toan vi dang trong
    // nhanh rieng cua request nay, khong chan vong loop() chinh).
    if (ampReady)
    {
      size_t written = 0;
      i2s_write(I2S_NUM_1, outBuf, samples * sizeof(int16_t), &written, portMAX_DELAY);
    }

    // Trinh duyet: gui them qua WiFi cho nguoi dang nghe qua may nay.
    size_t sentToClient = client.write((const uint8_t *)outBuf, samples * sizeof(int16_t));
    if (sentToClient == 0)
    {
      break; // client da dong ket noi
    }
  }
  Serial.println("[mic] Nguoi nghe them da dong trang.");
}

// Chạy trong loop() chính, MỌI LÚC (không cần ai mở trình duyệt): đọc mic, lọc DSP, ghi
// thẳng ra loa qua I2S. Đây là đường loa thật, luôn hoạt động.
static void localLoopbackTick()
{
  if (!micReady)
  {
    return;
  }

  const int bufLen = 512;
  static int32_t inBuf[bufLen];
  static int16_t outBuf[bufLen];

  size_t bytesRead = 0;
  i2s_read(I2S_NUM_0, inBuf, sizeof(inBuf), &bytesRead, 20 / portTICK_PERIOD_MS);
  int samples = bytesRead / sizeof(int32_t);
  if (samples == 0)
  {
    return;
  }

  int32_t peak = 0;
  for (int i = 0; i < samples; i++)
  {
    int16_t raw = (int16_t)(inBuf[i] >> 16);
    outBuf[i] = processSample(raw);
    int32_t av = abs((int32_t)outBuf[i]);
    if (av > peak)
      peak = av;
  }

  if (ampReady)
  {
    size_t written = 0;
    i2s_write(I2S_NUM_1, outBuf, samples * sizeof(int16_t), &written, 20 / portTICK_PERIOD_MS);
  }

  static unsigned long lastPrintMs = 0;
  unsigned long now = millis();
  if (now - lastPrintMs >= 300)
  {
    lastPrintMs = now;
    int bars = constrain(peak / 500, 0, 40);
    Serial.print("[loa] ");
    for (int i = 0; i < bars; i++)
      Serial.print('#');
    Serial.print("  (dinh=");
    Serial.print(peak);
    Serial.println(")");
  }
}

void setup()
{
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== mic-selftest: mic -> loa that NGAY LAP TUC ===");

  micReady = setupMic();
  ampReady = setupAmp();

  WiFi.softAP(AP_SSID);
  IPAddress ip = WiFi.softAPIP();

  Serial.println("----------------------------------------");
  Serial.println("Noi vao mic la nghe ra loa NGAY — khong can lam gi them.");
  Serial.println("Serial se in thanh # (nhan [loa]) theo do to nho cua tieng noi.");
  Serial.println("----------------------------------------");
  Serial.println("(Tuy chon) Nghe THEM qua may tinh/dien thoai khac:");
  Serial.print("  1. Vao WiFi ten: ");
  Serial.println(AP_SSID);
  Serial.print("  2. Mo trinh duyet: http://");
  Serial.println(ip);
  Serial.println("----------------------------------------");

  server.on("/", handleRoot);
  server.on("/mic.raw", handleMicStream);
  server.begin();
}

void loop()
{
  server.handleClient();
  localLoopbackTick();
  delay(1);
}
