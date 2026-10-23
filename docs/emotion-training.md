# Tự huấn luyện biểu cảm bằng FER+

## Phạm vi và nhánh

Làm việc trên `thai+emotion-recognition-training`, tách từ commit `67b7185`.
Giữ model `emotion-ferplus-8.onnx` và hành vi mặc định của Vision.
Cloud dùng để train; model xuất ONNX chạy tại máy PBL4.

Ba thí nghiệm: A = model pretrained hiện tại; B = CNN khởi tạo ngẫu nhiên,
nhãn cứng; C = cùng CNN, nhãn mềm. B/C dùng chung ảnh, tiền xử lý, seed và
ngân sách train. Không coi B/C là tái lập kiến trúc/kết quả công bố của Microsoft.

## Quy trình

1. Chuẩn bị `fer2013.csv` (ảnh) và `fer2013new.csv` (phiếu FER+); ghép theo
   thứ tự dòng, kiểm tra Usage và đủ số dòng. Không dùng nhãn bảy lớp FER2013.
2. Giữ Training / PublicTest / PrivateTest tương ứng train / validation / test.
   Kiểm tra ảnh lỗi, phân bố lớp, hash và trùng ảnh giữa các tập.
3. Train CNN nhỏ, ảnh xám 64×64, tám logits đúng thứ tự nhãn của PBL4.
   Chuẩn hóa nằm trong model xuất để giao diện nhận pixel float32 0–255.
4. Chọn checkpoint bằng macro-F1 validation, không chọn theo test. Lưu trạng thái
   optimizer, scheduler, RNG, cấu hình và định danh dataset để tiếp tục phiên.
5. Đánh giá A/B/C trực tiếp trên cùng ảnh mặt của tập test, không chạy detector.
   Báo cáo macro-F1, balanced accuracy, accuracy, từng lớp, confusion matrix,
   kích thước và thời gian suy luận trên cùng thiết bị.
6. Kiểm tra ONNX với PyTorch và OpenCV trước khi thử model trong Vision.
   Webcam là thí nghiệm riêng: cần ảnh/video gán nhãn độc lập theo người/phiên.

## Giao thức nhãn shared-v1

Giao thức riêng, công bố rõ để tránh nhầm với bộ lọc trong code CNTK gốc:

- Bỏ phiếu đơn lẻ (cột có <= 1 phiếu).
- Bỏ mẫu không còn phiếu, unknown/NF ngang hoặc cao hơn biểu cảm đứng đầu,
  hoặc tổng phiếu tám biểu cảm không chiếm quá nửa số phiếu còn lại.
- Bỏ mẫu hòa ở biểu cảm đứng đầu, tránh thiên lệch do thứ tự nhãn.
- Chuẩn hóa phiếu của tám biểu cảm còn lại thành phân bố mềm. Nhãn cứng và
  nhãn đánh giá là argmax của phân bố này. Dùng cùng bộ lọc cho A/B/C.
- Báo số mẫu bị bỏ theo nguyên nhân và số mẫu mỗi lớp. Báo đủ tám lớp, kể cả
  lớp không có mẫu; đánh dấu tập thiếu lớp, không gọi đó là benchmark đầy đủ.

Trùng ảnh giữa các tập được báo cáo; không tự di chuyển ảnh khỏi split chính
thức. Kết quả có trùng ảnh cần được ghi hạn chế, không tuyên bố không rò rỉ.

## Nguồn

- [Nhãn và split FER+](https://github.com/microsoft/FERPlus)
- [Bộ lọc tham chiếu gốc](https://github.com/microsoft/FERPlus/blob/master/src/ferplus.py)
- [Đặc tả model pretrained](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus)
- [Giới hạn Colab](https://research.google.com/colaboratory/faq.html)

Dữ liệu thô, ảnh mặt, checkpoint và kết quả chạy nằm ngoài Git. Chỉ commit
code, notebook sạch output và tài liệu. Chưa có lượt train FER+ thật hay kết
quả accuracy chỉ từ việc tạo công cụ hoặc chạy kiểm thử bằng dữ liệu nhân tạo.
