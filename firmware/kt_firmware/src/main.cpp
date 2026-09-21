#include <Arduino.h>
#include "pins.h"
#include "display.h"
#include "input.h"
#include "network.h"
#include "audio_i2s.h"

// main.cpp chỉ đóng vai trò "nhạc trưởng": setup()/loop() gọi các module, không tự đụng
// vào chi tiết TFT/WiFi/MQTT/nút bấm (những phần đó nằm ở display.*, network.*, input.*).
// Xem WEEKLY_LOGIC.md để hiểu lý do tách module theo cách này.

// Bản demo không còn chấm đúng/sai (bỏ 21/09/2026) nên chỉ còn 1 topic: báo cho server
// biết robot đang hiện từ nào trên màn.
const char *TOPIC_WORD = "panda/demo/khoa/word";

// ---------------------------------------------------------------------------
//  Danh sách từ vựng demo (tiếng Anh + tiếng Nhật)
//
//  Phạm vi dự án từ 21/09/2026 có thêm tiếng Nhật bên cạnh tiếng Anh, nên mỗi từ mang 3
//  phần: chữ Latin, Kanji, và cách đọc bằng Kana. Từ nào tiếng Nhật không dùng Kanji thì
//  để trống ô kanji — display.cpp sẽ tự phóng to phần Kana thay vào chỗ đó.
//
//  LƯU Ý khi sửa file này: phải lưu bằng mã hoá UTF-8 (VS Code mặc định là UTF-8, xem góc
//  dưới bên phải). Nếu lưu nhầm bảng mã khác, các chữ Nhật bên dưới biến thành byte rác và
//  màn hình sẽ hiện ra khoảng trắng.
//
//  Đây chỉ là dữ liệu tạm để test khi chưa có server: sau này khi bật lại MQTT, từ vựng sẽ
//  do server gửi xuống qua topic panda/cmd/word và gọi đúng hàm displaySetWord().
// ---------------------------------------------------------------------------
struct VocabWord
{
  const char *english;
  const char *kanji;
  const char *kana;
};

static const VocabWord VOCAB[] = {
    {"dog", "犬", "いぬ"},
    {"cat", "猫", "ねこ"},
    {"water", "水", "みず"},
    {"fish", "魚", "さかな"},
    {"mountain", "山", "やま"},
    {"flower", "花", "はな"},
    {"book", "本", "ほん"},
    {"rain", "雨", "あめ"},
    {"cake", "", "ケーキ"}, // từ mượn, tiếng Nhật viết bằng Katakana, không có Kanji
};
static const int VOCAB_LEN = sizeof(VOCAB) / sizeof(VOCAB[0]);

// -1 = chưa hiện từ nào lần nào, nên lần bấm nút đầu tiên sẽ hiện đúng từ số 0.
static int vocabIndex = -1;

// Hiện từ kế tiếp ra giữa màn (và báo lên MQTT nếu đang bật). Hết danh sách thì quay
// vòng về từ đầu tiên.
static void showNextWord()
{
  vocabIndex = (vocabIndex + 1) % VOCAB_LEN;
  const VocabWord &w = VOCAB[vocabIndex];
  displaySetWord(w.english, w.kanji, w.kana);

  char payload[192];
  snprintf(payload, sizeof(payload),
           "{\"word\":\"%s\",\"kanji\":\"%s\",\"kana\":\"%s\",\"ts\":%lu}",
           w.english, w.kanji, w.kana, millis());
  networkPublish(TOPIC_WORD, payload);
}

// ---------------------------------------------------------------------------
//  Danh sách biểu cảm để nút thứ nhất lần lượt đi qua.
//
//  Trước đây robot tự đổi biểu cảm khi không ai bấm gì trong 6 giây. Bỏ cơ chế đó ngày
//  21/09/2026 vì giờ đã có hẳn một nút riêng để đổi — tự đổi nữa sẽ ghi đè mất biểu cảm
//  vừa chọn và làm hành vi khó đoán.
// ---------------------------------------------------------------------------
static const char *FACES[] = {
    "neutral", "happy", "sad", "angry", "surprised", "sleepy", "wink", "love",
    "cool", "cute", "dizzy", "questioning", "hearing", "thinking", "speaking"};
static const int FACES_LEN = sizeof(FACES) / sizeof(FACES[0]);

static int faceIndex = 0;

// Sang biểu cảm kế tiếp. Nếu đang hiện từ vựng thì thao tác này cũng đưa màn hình quay
// về khuôn mặt (xem displaySetExpression trong display.cpp).
static void showNextFace()
{
  faceIndex = (faceIndex + 1) % FACES_LEN;
  displaySetExpression(FACES[faceIndex]);
}

// Tách một chuỗi thành tối đa 3 phần ngăn cách bằng dấu cách. Cắt theo BYTE là an toàn với
// tiếng Nhật: trong UTF-8, byte của dấu cách (0x20) không bao giờ xuất hiện bên trong một
// chữ nhiều byte, nên không có nguy cơ cắt đôi chữ 犬 thành byte rác.
static int splitWords(const String &text, String *parts, int maxParts)
{
  int count = 0;
  int i = 0;
  while (count < maxParts && i < (int)text.length())
  {
    while (i < (int)text.length() && text[i] == ' ')
    {
      i++;
    }
    if (i >= (int)text.length())
    {
      break;
    }
    int space = text.indexOf(' ', i);
    if (space < 0)
    {
      space = text.length();
    }
    parts[count++] = text.substring(i, space);
    i = space;
  }
  return count;
}

// 2 lệnh gõ qua Serial Monitor:
//
//   face <ten>              — xem thẳng 1 biểu cảm bất kỳ (cùng quy ước với firmware của bạn
//                             AI trong nhóm, xem ai.md mục 5).
//   word <anh> <kanji> <kana>  — đặt từ vựng tuỳ ý, ví dụ: word dog 犬 いぬ
//
// Lệnh "word" là cách kiểm chứng luồng UTF-8 chạy đúng với chữ BẤT KỲ chứ không chỉ mấy từ
// dựng sẵn trong VOCAB — đúng việc mà MQTT sẽ làm sau này. Gõ tiếng Nhật vào Serial Monitor
// cần bàn phím/IME tiếng Nhật; nếu không gõ được, cứ dùng danh sách VOCAB dựng sẵn.
static void handleSerialCommand()
{
  if (!Serial.available())
  {
    return;
  }
  String line = Serial.readStringUntil('\n');
  line.trim();

  if (line.startsWith("face "))
  {
    String arg = line.substring(5);
    arg.trim();
    displaySetExpression(arg.c_str());
    return;
  }

  if (line.startsWith("word "))
  {
    String parts[3];
    int count = splitWords(line.substring(5), parts, 3);
    if (count == 0)
    {
      Serial.println("[main] Cu phap: word <tieng anh> <kanji> <kana>");
      return;
    }
    displaySetWord(parts[0].c_str(), parts[1].c_str(), parts[2].c_str());
  }
}

void setup()
{
  Serial.begin(115200);
  inputSetup();
  displaySetup();
  networkSetup();
  audioI2sSetup(); // module học I2S của Tuần 3 — xem audio_i2s.cpp để hiểu vì sao chưa đọc được âm thanh thật trong Wokwi

  // Khởi động ở chế độ khuôn mặt — từ vựng chỉ hiện khi người dùng bấm nút hỏi.
  displaySetExpression(FACES[faceIndex]);

  Serial.println("[main] San sang.");
  Serial.println("[main] Nut chan 25 = doi bieu cam ke tiep (15 bieu cam).");
  Serial.println("[main] Nut chan 26 = hien tu vung ke tiep ra giua man (bam lai = tu khac).");
  Serial.println("[main] Go 'face <ten>' hoac 'word <anh> <kanji> <kana>' de test thu cong.");

  // In lượng RAM trống còn lại sau khi mọi thứ đã khởi tạo xong (khung đệm màn hình 62KB,
  // WiFi, MQTT...). Nếu con số này tụt xuống dưới ~40KB thì cần lo: các thao tác mạng sau
  // đó có thể xin thêm bộ nhớ không được và sinh lỗi khó hiểu.
  Serial.print("[main] RAM trong con lai: ");
  Serial.print(ESP.getFreeHeap());
  Serial.println(" byte");
}

void loop()
{
  networkLoop();
  handleSerialCommand();

  ButtonEvent event = inputPoll();
  if (event == ButtonEvent::NextFace)
  {
    showNextFace();
  }
  else if (event == ButtonEvent::NextWord)
  {
    showNextWord();
  }

  displayLoop();
  audioI2sLoop();

  // NHƯỜNG CPU cho hệ điều hành — 1 dòng nhỏ nhưng quan trọng.
  //
  // Từ khi đổi sang màn SPI, không còn chỗ nào trong loop() "nghỉ" nữa: bản OLED cũ vô
  // tình an toàn vì hàm gửi I2C chờ bằng semaphore (lúc chờ là task tự ngủ, CPU được
  // nhường cho việc khác), còn hàm gửi SPI chờ bằng vòng lặp đọc thanh ghi liên tục,
  // không nhường gì cả. Các hàm còn lại đều return ngay. Kết quả: task chính quay
  // 100% CPU không ngừng nghỉ, khiến (1) máy tính phải mô phỏng một con CPU lúc nào cũng
  // bận tối đa nên nóng và quạt kêu to, (2) các task nền của hệ thống (WiFi, TCP/IP) bị
  // chèn ép, dễ sinh lỗi lạ.
  //
  // delay(1) KHÁC HẲN delay() dài đã học ở Bước 10: nó không phải "chờ cho hết giờ" mà là
  // báo cho hệ điều hành "tôi xong việc rồi, ai cần CPU thì dùng đi" — và 1ms là đúng 1
  // nhịp tick của FreeRTOS, tức mức nhường nhỏ nhất có thể. Vòng lặp vẫn chạy ~1000
  // lần/giây, thừa sức bắt kịp nút bấm (debounce 200ms) và khung hình (30ms).
  delay(1);
}
