# Đối chiếu lại model FERPlus và EmotionCNN

Kiểm tra ngày 24/10/2026. Đây là phân tích bổ sung của thí nghiệm seed 42,
không thay mô hình, không huấn luyện lại và không chọn lại checkpoint theo test.

## Kiểm tra dữ liệu và cách tính

- SHA256 file A khớp Git LFS pointer của ONNX Model Zoo:
  `a2a2ba6a335a3b29c21acb6272f962bd3d47f84952aaffa03b60986e04efa61c`.
- SHA256 của CSV gốc tại Downloads và nhãn tải từ Microsoft khớp manifest.
- Đối chiếu trực tiếp 3.376 ảnh test với dòng CSV, Usage và target FER+ sau lọc:
  không phát hiện lệch hàng hoặc nhãn so với báo cáo đã lưu.
- A/B/C có cùng ID và nhãn thật theo cùng thứ tự; đầu ra đủ tám logits hữu hạn.
  Argmax khớp nhãn dự đoán. Tính lại accuracy, macro-F1, balanced accuracy,
  per-class metrics và confusion matrix: khớp hoàn toàn báo cáo.
- Cả A và B có chuẩn hóa bên trong ONNX, nhưng công thức khác nhau theo mạng
  đã huấn luyện: A trừ 127,5 rồi chia 255; B chia 127,5 rồi trừ 1.
  Không được chuẩn hóa thêm bên ngoài hoặc ép công thức B sang A.

## Kiểm tra cách resize cho model A

Model card A dùng PIL ANTIALIAS, tên hiện tại là LANCZOS. Phép đo ban đầu dùng
OpenCV INTER_AREA cho cả ba model. Đã chạy lại A trên toàn bộ 3.376 ảnh bằng
cả AREA và LANCZOS trong cùng môi trường OpenCV 5.0.0 CPU hai thread.

| Cách xử lý | Accuracy | Macro-F1 | Balanced accuracy |
|---|---:|---:|---:|
| A với INTER_AREA | 81,8720% | 61,0557% | 57,4857% |
| A với PIL LANCZOS theo model card | 82,5533% | 61,8417% | 58,3894% |
| B với INTER_AREA như lúc train | 84,9526% | 73,0848% | 69,3979% |

AREA chạy lại có 0/3.376 dự đoán thay đổi so với báo cáo Colab. LANCZOS có
109 dự đoán thay đổi so với AREA. Vì vậy mốc A theo model card phải được ghi
bổ sung, không chỉ dùng mốc A thấp hơn từ resize chung.

Đối chiếu OpenCV và ONNX Runtime 1.29.0 trên 32 ảnh test ngẫu nhiên seed 42
cho từng model: 0 bất đồng argmax. Sai số logits tuyệt đối lớn nhất A/B/C lần
lượt là 0,00000572 / 0,00001144 / 0,00000477. Đây là kiểm tra runtime trên mẫu,
không thay thế tái kiểm tra toàn bộ dữ liệu qua cả hai backend.

## Phân tích độ nhạy với ảnh trùng

Từ pixel hash đã lưu, loại 302 ảnh test trùng chính xác với train hoặc
validation, còn 3.074 ảnh đủ tám lớp. Chưa loại near-duplicate hay cùng người.

| Model trên 3.074 ảnh còn lại | Accuracy | Macro-F1 | Balanced accuracy |
|---|---:|---:|---:|
| A với AREA | 81,8803% | 58,7148% | 55,5112% |
| A với LANCZOS theo model card | 82,3357% | 58,9519% | 55,9084% |
| B với AREA | 83,7671% | 68,1409% | 64,6619% |
| C với AREA | 82,4658% | 66,4750% | 64,7299% |

Đây chỉ là chấm lại dự đoán trên một subset. Không phải huấn luyện lại với
bộ chia sạch: validation cũ đã tham gia chọn checkpoint; tập đánh giá và phân
bố lớp cũng đã đổi. Không coi mức giảm điểm là ước lượng nhân quả chính xác
của riêng rò rỉ. Không biết đầy đủ dữ liệu huấn luyện lịch sử của model A.

## Kết luận và bước tiếp theo

B vẫn cao hơn A trong các phép kiểm tra bổ sung này, nhưng lợi thế còn khoảng
1,43 điểm phần trăm accuracy và 9,19 điểm macro-F1 khi dùng A LANCZOS trên
subset 3.074 ảnh. C có balanced accuracy nhỉnh hơn B trên subset này; B không
thắng mọi tiêu chí. Các kết quả không chứng minh khả năng camera hay ưu thế
so với mọi mô hình FER+ công bố.

Để xác nhận khả năng tổng quát hóa: chốt bộ chia theo nhóm không trùng trước
huấn luyện, chọn model bằng validation sạch, chạy nhiều seed và đánh giá camera
độc lập. Không chỉnh cấu hình theo test hiện tại rồi coi lần chấm sau là một
kiểm định mới. Điểm được công bố ban đầu là benchmark artifact trong giao thức
shared-v1, không phải tái lập nguyên giao thức hoặc kết quả bài báo gốc.

Nguồn model card:
https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus

Nguồn Git LFS pointer:
https://raw.githubusercontent.com/onnx/models/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx

Không chỉnh sửa báo cáo Word đang được mở hoặc có thay đổi của người dùng.
