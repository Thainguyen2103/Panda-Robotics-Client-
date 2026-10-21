# Kiểm thử biểu cảm — 14/10/2026

Khởi động lại bằng `start.bat`, tải lại dashboard với **Ctrl+F5**.
Đọc dòng **Cảm xúc** để xem nhãn đã xác nhận. **Điểm tổng hợp** là các điểm hỗ trợ
chưa hiệu chuẩn; mục **Điểm FER+ liên tục** giữ riêng đầu ra mô hình đã làm mượt.
Phần trăm từ mốc mặt là mức kích hoạt biểu cảm, không phải xác suất tâm lý.

## Thay đổi

- FER+ vẫn dùng mô hình pretrained tám lớp, không train/fine-tune lại.
- Căn độ nghiêng mặt khi cặp mắt YuNet hợp lệ, resize grayscale bằng INTER_AREA,
  giữ dải pixel 0–255 theo [hướng dẫn FER+ ONNX](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus).
  Có thể tắt căn nghiêng bằng `VISION_EMOTION_ALIGN_ROLL` để so trên cùng tập kiểm định.
- Ưu tiên FER+ khi nhãn khác trung tính đủ rõ. Tổ hợp mốc mặt giúp phục hồi
  biểu cảm bị lẫn vào trung tính; hỗ trợ cả ứng viên FER đứng thứ ba trở xuống
  nếu đủ điểm và có tổ hợp mốc mặt phù hợp. Không sửa trọng số hay điểm FER gốc.
- So các ứng viên cùng xuất hiện theo bằng chứng thay vì thứ tự `if`; giữ
  `unknown` khi khó phân biệt. Cười lệch không tự vào vui; sợ/ngạc nhiên cần
  dấu hiệu phân biệt khi chỉ có mốc mặt. Các luật này còn cần đo trên người thật.
- Trung tính cần giữ 0,65 giây để thay nhãn. Tối thiểu hai mẫu mới xác nhận;
  cache không bắt đầu hoặc kéo dài xác nhận FER. Mất mặt, đổi người, mất camera
  và dữ liệu quá hạn vẫn xóa kết quả. EMA thay đổi theo thời gian suy luận thực.

## Đánh giá bằng ảnh có nhãn

Dùng ảnh một người, mặt rõ, trong các thư mục sau:

```text
emotion-test/
  neutral/
  happy/
  surprised/
  sad/
  angry/
  disgust/
  fear/
  contempt/
```

Không đưa ảnh cá nhân vào Git. Có thể đặt tập ảnh và báo cáo ngoài repository:

```powershell
.\server\venv\Scripts\python.exe tools\evaluate_emotions.py C:\EmotionTest --output C:\EmotionResults\report.json
```

Mặc định yêu cầu đủ tám lớp. `--allow-partial` cho phép kiểm tra một vài lớp,
nhưng báo cáo ghi rõ thiếu lớp nào; macro-F1 chỉ tính trên các lớp có mẫu.

Báo cáo gồm accuracy, macro-F1, balanced accuracy, precision/recall/F1 từng lớp,
ma trận nhầm lẫn có cột `unknown`, coverage, lỗi đọc ảnh/phát hiện mặt, hash mô
hình và cấu hình. Lỗi hoặc không rõ vẫn được tính là sai, không loại khỏi mẫu.
Ảnh nhiều người bị ghi lỗi vì không biết ai mang nhãn được gán.

Hai bảng `fer_argmax` và `fused_candidate` dùng cùng tiền xử lý mới, lần lượt
so argmax FER với ứng viên kết hợp mốc mặt. Đây **không phải** phép đo trước/sau
toàn bộ thay đổi. Ảnh độc lập chạy Face Landmarker ở IMAGE mode, không dùng lịch
sử tracking của ảnh trước và không giả lập xác nhận thời gian bằng cách lặp ảnh.
Độ trễ báo cáo của công cụ này gồm đọc ảnh và phát hiện mặt; không phải FPS video.

Để đo cải thiện đáng tin cậy, giữ nguyên một tập kiểm định độc lập rồi chạy cả
phiên bản trước và sau. Chia theo người/phiên quay, tránh chia ngẫu nhiên các
frame cùng video sang tập chỉnh ngưỡng và tập kiểm định. Giữ cả trung tính và
các tình huống dễ nhận nhầm như nói chuyện, ngáp, tập trung, quay đầu, thiếu sáng.
Không chỉnh ngưỡng dựa vào tập kiểm định cuối cùng.

## Thử camera và chuyển nhãn

```powershell
.\server\venv\Scripts\python.exe tools\check_vision.py --camera --frames 120
.\server\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_vision*.py' -v
node tests/test_vision_ui.cjs
```

Diagnostic camera không lưu ảnh và không phát MQTT/lệnh robot. Nó đếm nhãn
đã xác nhận, nguồn xác nhận, nhãn FER cao nhất, số frame có mặt và mốc mặt.
Nếu `face_cue_frames` bằng 0, chưa kiểm tra được nhánh mốc mặt trên người thật.

Trong dashboard, giữ từng biểu cảm 2–3 giây, thư giãn 2 giây rồi chuyển biểu
cảm. Thử đủ tám lớp, mỗi lớp ít nhất 10 lần, ở nhiều người/điều kiện sáng.
Ghi nhãn dự kiến, nhãn hiện, số nhận sai về trung tính, số trung tính bị gán
biểu cảm, và độ trễ chuyển nhãn. Riêng sợ, chán ghét, khinh miệt thường khó tạo
và khó gán nhãn; không chỉ đánh giá bằng biểu cảm phóng đại. Video có nhãn mới
đánh giá được độ ổn định, giật nhãn và độ trễ mà tập ảnh không phản ánh.

## Kết quả xác minh tại máy phát triển

- 54 test logic Vision và bộ test giao diện qua. Các mốc/điểm tổng hợp trong
  unit test là dữ liệu nhân tạo, không phải accuracy trên ảnh người thật.
- Camera 40 frame: nạp đủ bảy nhánh model, không báo lỗi; chỉ 4 frame phát hiện
  mặt, 0 frame có mốc mặt, 40 nhãn `unknown`. Trung vị 46,9 ms, p95 121,4 ms.
  Lượt này chưa đủ dữ liệu mặt để kết luận chất lượng nhận diện biểu cảm.
- Chưa có tập kiểm định gán nhãn trong repository để công bố accuracy hoặc
  khẳng định tăng bao nhiêu phần trăm. Cần dùng tập ảnh/video riêng trước khi
  chọn ngưỡng hay kết luận đạt một mức chất lượng cụ thể.
