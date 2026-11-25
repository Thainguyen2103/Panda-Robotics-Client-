# Tìm lỗi "nói vào mic thì loa rè": mic hư hay loa hư?

Lúc test bằng `mic-selftest`, mic phát thẳng ra loa robot. Khi nghe rè thì có 3 khả năng:
mic hư, loa hoặc khuếch đại hư, hoặc **không cái nào hư**. Khả năng thứ 3 xảy ra khi tiếng rè
đến từ cách test, ví dụ mic đặt sát loa gây hú, hoặc bộ lọc trong code gây méo.
Hai bài dưới đây tách riêng từng linh kiện, nên kết quả không lẫn vào nhau.

| Bài | Dùng | KHÔNG dùng | Nghe bằng |
|---|---|---|---|
| `mic-only/` | Mic INMP441 | Loa và khuếch đại robot | Loa/tai nghe **laptop** (chắc chắn tốt) |
| `speaker-only/` | Khuếch đại MAX98357 + loa | Mic | Loa robot, phát âm **do code tạo ra** (chắc chắn sạch) |

Làm bài nào thì **chỉ nối linh kiện của bài đó**. Rút điện trước khi cắm hoặc rút dây.

---

## Bài 1: chỉ mic (`mic-only/`)

**Nối dây:**

| INMP441 | ESP32-S3 |
|---|---|
| VDD | 3V3 |
| GND | GND |
| L/R | GND |
| SCK | 40 |
| WS | 41 |
| SD | 42 |

**Chạy:**
1. Mở thư mục `mic-only` trong VS Code, bấm PlatformIO **Upload**. Không mở Monitor.
2. Bấm đúp `ghi-am-mic.bat` rồi làm theo hướng dẫn trên màn hình:
   - Bước 1: giữ im lặng 3 giây.
   - Bước 2: nói 5 giây.
   - Bước 3: chương trình tự phát lại bản ghi bằng loa laptop.
3. Chương trình in số đo, kết luận, rồi hỏi bạn "có rè không".

Các file `.wav` được lưu trong `mic-only/ket-qua/`. Có thể gửi cho nhóm nghe cùng.

| Kết quả | Nghĩa là |
|---|---|
| Bản ghi **sạch** | **Mic tốt.** Chuyển sang bài 2. |
| Bản ghi **rè/xè** | **Mic có vấn đề**, vì bản ghi này không hề đi qua loa robot. Cắm lại dây mic cho chắc rồi thử lại; vẫn rè thì mua mic mới. |
| "Mic KHÔNG có tín hiệu" | Sai dây hoặc lỏng dây (SD, SCK, WS, L/R). Dây đúng mà vẫn vậy thì mic chết. |
| "Giọng nói chỉ to hơn ồn nền … dB" (dưới 10 dB) | Mic rất nhiễu hoặc yếu. Thử cổng USB hoặc dây khác, để mic xa dây nguồn. |

---

## Bài 2: chỉ loa (`speaker-only/`)

**Nối dây:**

| MAX98357 | ESP32-S3 |
|---|---|
| VIN | **5V** (nên dùng; 3V3 cũng chạy nhưng yếu, dễ rè khi to) |
| GND | GND |
| BCLK | 47 |
| LRC | 48 |
| DIN | 21 |
| Loa 8Ω | 2 cực `+` / `−` trên module (**không** nối cực nào xuống GND) |

**Chạy:**
1. Mở thư mục `speaker-only`, **Upload**, rồi mở **Monitor** (115200).
2. Board tự phát lần lượt 8 bài và in ra "bình thường thì nghe thế nào".
3. Gõ `0`–`7` rồi Enter để nghe lại một bài, `a` để chạy lại cả lượt, `s` để dừng.

| Nghe thấy | Lỗi nằm ở |
|---|---|
| Bài **0 (im lặng)** mà vẫn ù/rè/lách tách | **Nguồn hoặc khuếch đại** (không phải loa, không phải mic). Kiểm tra GND chung, dây VIN, thử VIN = 5V, dùng dây ngắn. |
| Rè **ngay cả bài 1 (nhỏ 5%)** | **Loa hỏng** (màng rách, cuộn dây cọ) **hoặc module khuếch đại hỏng**. Đo loa bằng đồng hồ: khoảng 6–8Ω là còn; ∞ là đứt, ~0 là chập. Loa đo ổn → nghi module khuếch đại. |
| Bài 1–2 sạch, **chỉ bài 3 (to 60%) rè** hoặc board tự khởi động lại | **Quá tải hoặc sụt nguồn**, linh kiện chưa chắc hư. Chuyển VIN sang 5V; loa nhỏ (0,5W) thì giảm âm lượng. |
| Bài **5 (âm trầm 150Hz)** kêu lạch xạch | Màng loa rách, hoặc loa chạm vỏ, dây hay vật gì đó. Kê loa lên cho thoáng rồi thử lại. |
| Rè ở **một đoạn** của bài 6 (quét tần số) | Màng loa hỏng, hoặc vỏ hay hộp loa cộng hưởng. |
| Không ra tiếng gì | Dây BCLK/LRC/DIN, VIN; chân SD của module phải để trống hoặc nối VIN, **không** nối GND. |
| Tất cả đều sạch | **Loa và khuếch đại tốt.** |

---

## Kết luận cuối

| Bài 1 (mic) | Bài 2 (loa) | Kết luận | Mua |
|---|---|---|---|
| Rè | Sạch | Mic lỗi | Mic INMP441 |
| Sạch | Rè | Loa hoặc khuếch đại lỗi (xem bảng bài 2 để biết cái nào) | Loa 8Ω hoặc MAX98357 |
| Rè | Rè | Cả hai có vấn đề, hoặc chung một nguồn nhiễu (thử nguồn/USB khác trước khi mua) | Tuỳ |
| **Sạch** | **Sạch** | **Không hư gì.** Tiếng rè cũ do cách test: mic sát loa gây hú, bộ lọc `MAX_JUMP` trong `mic-selftest` cắt méo tiếng to, WiFi bật cùng lúc gây nhiễu nguồn, hoặc chế độ mono `ONLY_LEFT` | **Không cần mua.** Sửa code. |

Thư mục này nằm trên nhánh tạm `test/khoa-mic-loa`, test xong thì xoá nhánh.
