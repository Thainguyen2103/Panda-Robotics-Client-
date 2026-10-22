#include <Arduino.h>
#include "esp_camera.h"

// ---------------------------------------------------------------------------
// cam-selftest — xem video camera TRỰC TIẾP TRÊN LAPTOP qua chính dây USB đang cắm.
// Không WiFi, không điện thoại. Nạp xong → đóng Serial Monitor → bấm đúp xem-camera.bat.
//
// Cách hoạt động: camera chụp liên tục, mỗi khung JPEG được gửi xuống laptop qua cổng
// Serial (USB) kèm 1 "đầu gói" nhận dạng; chương trình tools/viewer.py trên laptop tách
// từng khung ra và vẽ lên cửa sổ liên tục → thành video.
//
// Vì sao phải nâng tốc độ Serial lên 4.000.000 (thay vì 115200 như các test khác):
// 115200 baud ≈ 11KB/giây — 1 khung ảnh 640x480 đã ~12KB, tức chưa tới 1 khung/giây.
// 4.000.000 baud ≈ 400KB/giây → dư sức cho ~16 khung/giây (đo thật: dùng ~200KB/giây).
// Đã thử 5.000.000: chip USB CH343 trên board truyền sai bit → ảnh hỏng, nên dừng ở 4M.
// Hệ quả: Serial Monitor của PlatformIO sẽ chỉ thấy ký tự rác — BÌNH THƯỜNG, vì giờ xem
// bằng viewer.py (nó vẫn in các dòng log [cam] ra cửa sổ đen cho bạn đọc).
//
// Cảm biến thật trên board là OV5640 (5MP, PID=0x5640) — không phải OV3660 như ghi trước đây.
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 4000000

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

// 4 byte đánh dấu "bắt đầu 1 khung ảnh". Laptop dò chuỗi này trong dòng dữ liệu để biết
// chỗ nào là ảnh, chỗ nào là chữ log — giống dấu mở ngoặc trong 1 câu dài.
static const uint8_t FRAME_MAGIC[4] = {'P', 'N', 'D', 'A'};

static bool camReady = false;

static const framesize_t SIZES[] = {FRAMESIZE_QVGA, FRAMESIZE_VGA, FRAMESIZE_SVGA, FRAMESIZE_HD};
static const char *SIZE_NAMES[] = {"320x240", "640x480", "800x600", "1280x720"};
static int sizeIdx = 1;
// Nén JPEG 10 (bản trước 14): ảnh giữ nhiều chi tiết hơn, mỗi khung nặng hơn ~30%. Giới
// hạn thật là đường USB ~300KB/giây — nén ít quá (số rất nhỏ) thì khung/giây tụt.
static int quality = 10;

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
  // 24MHz thay vì 20MHz: xung nhịp cấp cho camera nhanh hơn → camera chụp nhanh hơn. Đo
  // thật trên board này: 20MHz = 11 khung/giây, 24MHz = 16,5 khung/giây, cùng chất lượng.
  config.xclk_freq_hz = 24000000;
  config.pixel_format = PIXFORMAT_JPEG;
  // Luôn lấy khung MỚI NHẤT: nếu dây USB gửi chậm hơn camera chụp, khung cũ bị bỏ qua thay
  // vì xếp hàng chờ — video không bị trễ dần so với thực tế.
  config.grab_mode = CAMERA_GRAB_LATEST;

  // Init ở cỡ lớn (HD) để bộ đệm đủ chỗ khi bấm phím đổi độ phân giải lúc đang chạy; ngay
  // sau đó hạ về 640x480. Bộ đệm nằm ở PSRAM 8MB nên thoải mái.
  config.frame_size = FRAMESIZE_HD;
  config.jpeg_quality = quality;
  config.fb_count = 2;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  if (!psramFound())
  {
    config.frame_size = FRAMESIZE_QVGA;
    config.fb_count = 1;
    sizeIdx = 0;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK)
  {
    Serial.printf("[cam] Camera init THAT BAI, ma loi: 0x%x\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  s->set_framesize(s, SIZES[sizeIdx]);
  s->set_quality(s, quality);
  s->set_brightness(s, 1);  // OV3660 mặc định hơi tối
  s->set_saturation(s, -1); // và hơi rực màu
  s->set_contrast(s, 1);    // tách sáng/tối rõ hơn → mắt thấy "nét" hơn
  s->set_sharpness(s, 2);   // làm sắc cạnh mức cao nhất của cảm biến
  s->set_denoise(s, 0);     // tắt lọc nhiễu của cảm biến — bộ lọc này làm nhoè chi tiết nhỏ
  // Xoay ảnh 180° (camera lắp ngược trên board): lật dọc + lật ngang cùng lúc. Chỉ lật dọc
  // thôi thì ảnh sẽ vừa ngược vừa bị soi gương (chữ bị ngược).
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
  s->set_lenc(s, 1);
  s->set_bpc(s, 1);
  s->set_wpc(s, 1);
  s->set_raw_gma(s, 1);

  Serial.printf("[cam] Camera init OK, cam bien PID=0x%x, PSRAM %u KB, khung %s\n", s->id.PID,
                (unsigned)(ESP.getPsramSize() / 1024), SIZE_NAMES[sizeIdx]);
  return true;
}

// Phím bấm trong cửa sổ viewer được gửi ngược lên board qua Serial (1 ký tự).
static void handleKey(char c)
{
  sensor_t *s = esp_camera_sensor_get();
  if (c >= '1' && c <= '4')
  {
    sizeIdx = c - '1';
    s->set_framesize(s, SIZES[sizeIdx]);
  }
  else if (c == '+' && quality > 4)
  {
    quality -= 2; // số nhỏ = nét hơn
    s->set_quality(s, quality);
  }
  else if (c == '-' && quality < 40)
  {
    quality += 2;
    s->set_quality(s, quality);
  }
  else if (c == 'm')
  {
    s->set_hmirror(s, !s->status.hmirror);
  }
  else if (c == 'f')
  {
    s->set_vflip(s, !s->status.vflip);
  }
  else
  {
    return;
  }
  Serial.printf("[cam] Do phan giai %s, nen JPEG %d, lat ngang %d, lat doc %d\n",
                SIZE_NAMES[sizeIdx], quality, s->status.hmirror, s->status.vflip);
}

void setup()
{
  // Bộ đệm gửi lớn: cho phép nhét cả 1 khung ảnh vào hàng đợi rồi để phần cứng UART tự
  // đẩy ra dần, thay vì CPU phải đứng chờ từng byte. Phải đặt TRƯỚC Serial.begin().
  Serial.setTxBufferSize(32768);
  Serial.begin(SERIAL_BAUD);
  delay(300);
  Serial.println();
  Serial.println("[cam] === cam-selftest: video qua USB len laptop ===");
  camReady = setupCamera();
}

void loop()
{
  while (Serial.available())
  {
    handleKey((char)Serial.read());
  }

  if (!camReady)
  {
    Serial.println("[cam] Camera chua san sang — xem loi o tren. Thu rut cap FPC cam lai cho chat.");
    delay(2000);
    return;
  }

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb)
  {
    Serial.println("[cam] Chup khung loi, thu lai...");
    delay(50);
    return;
  }

  // Gói 1 khung = [PNDA][độ dài 4 byte][dữ liệu JPEG]. Có độ dài thì laptop biết đọc bao
  // nhiêu byte là hết ảnh, không phải đoán.
  uint32_t len = fb->len;
  Serial.write(FRAME_MAGIC, 4);
  Serial.write((const uint8_t *)&len, 4);
  Serial.write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}
