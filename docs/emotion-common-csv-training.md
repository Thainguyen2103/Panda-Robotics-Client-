# Huấn luyện EmotionCNN trên bộ CSV phân tầng dùng chung

## Trạng thái

Đã kiểm tra và chuẩn bị bộ chia; chưa chạy huấn luyện GPU đầy đủ và chưa có kết quả accuracy mới. Báo cáo Word hiện có mô tả thí nghiệm cũ, chưa được thay bằng số liệu của bộ chia mới.

## Dữ liệu cố định

Nguồn nhận: du_lieu_dung_chung/du_lieu_dung_chung. Ba CSV chứa ảnh xám 48×48 gốc, hard label và soft label. Không lọc, chia hoặc sắp lại dữ liệu khi nhập. Đổi thứ tự mẫu trong DataLoader train không thay đổi thành viên tập.

| Tập | File | Số ảnh |
|---|---|---:|
| Train | train.csv | 22295 |
| Validation | val.csv | 4777 |
| Test | test.csv | 4778 |

Mã băm đã chốt tại training/emotion/common_csv_lock.json. Bộ nhập từ chối CSV khác phiên bản và từ chối ảnh trùng pixel hoặc ID. Thứ tự nhãn được ánh xạ: Neutral→neutral, Happiness→happy, Surprise→surprised, Sadness→sad, Anger→angry, Disgust→disgust, Fear→fear, Contempt→contempt. Không dùng bảng nhãn FER2013 gốc.

Theo hướng dẫn người cung cấp: gộp dữ liệu gốc, lọc phiếu, exact/near dedup, stratify theo hard label với seed 42 và chia 70/15/15. Đã xác minh số lượng và phân bố lớp trên CSV, chưa tái tạo bộ chia từ mã nguồn của người cung cấp. Giao thức mới khác official Usage và shared-v1 cũ.

Kiểm tra thực tế toàn bộ 31850 ảnh: pixel hợp lệ, ID đúng SHA256 chuỗi pixel, không trùng pixel/ID giữa các tập, hard label khớp soft argmax; tổng nhãn mềm được chuẩn hóa lại. Bổ sung kiểm tra xuyên tập: cùng 64-bit dHash (resize INTER_AREA 9×8, pixel phải > trái) và MAD ảnh gốc ≤15: 0 cặp. Điều này không bảo đảm loại mọi ảnh gần trùng hoặc tách theo danh tính.

Test mới có 3845 ảnh trùng pixel với mẫu train B/C cũ và 522 ảnh trùng validation cũ; các nhóm có thể giao nhau. Cần train từ đầu cho thí nghiệm mới. Không dùng model cũ hoặc resume cũ để báo kết quả test mới độc lập.

## Chạy Colab

Notebook: notebooks/ferplus_common_csv_colab.ipynb. Chọn GPU T4, sao chép notebook vào Drive, upload ba CSV vào MyDrive/PBL4-FERPlus/common-csv-70-15-15-v1. Đặt model A đúng hash tại MyDrive/PBL4-FERPlus/models/emotion-ferplus-8.onnx. Chạy mục 1–7 theo thứ tự. Notebook mới không tải lại raw FER2013/FER+ và không thay đổi bộ chia.

Kiến trúc giữ EmotionCNN fer-cnn-v1: 8 Conv, kênh 32/64/128/256, GAP, dropout 0.35, linear 256→8. B hard và C soft, khởi tạo ngẫu nhiên seed 42; AdamW lr .001, WD .0001, batch128, max80, patience12, cosine scheduler. Chọn best.pt theo validation macro-F1. Thêm seed123/2026 trước khi mở test nếu thời gian cho phép; không chọn seed theo test.

CSV chưa CLAHE hoặc chuẩn hóa. B/C resize64 INTER_AREA và chuẩn hóa x/127.5−1 trong mạng; không thêm CLAHE trong lượt đầu. A giữ normalization nội tại và resize PIL Lanczos theo model card. Đây là so sánh các hệ thống với tiền xử lý tương ứng, không ép tiền xử lý của model này vào model khác.

Mỗi epoch in ngay tiến độ; last.pt dùng tiếp tục đúng cấu hình, best.pt dùng xuất ONNX. Tên experiment mới common701515-cnn-v1. Đổi cấu hình thì đổi tên experiment. Export kiểm tra PyTorch/ORT/OpenCV trên validation và pixel biên. Nếu bị ngắt Colab, kết nối lại GPU và chạy mục1–4; fingerprint/cấu hình ngăn nạp checkpoint cũ.

Mục8 test mặc định tắt. Chỉ bật RUN_FINAL_TEST sau khi chốt cấu hình. Báo accuracy, macro-F1, balanced accuracy, precision/recall/F1 từng lớp. predictions.csv gồm model, image_id, reference_label, predicted_label và p_ cho tám nhãn; chia sẻ kết quả này để đối chiếu không cần trao đổi weights. Hai bên phải giữ đúng CSV và ánh xạ nhãn. Chọn Single-Crop cho bảng chính; Ten-Crop nếu khảo sát phải chọn bằng validation và báo riêng chi phí tính toán.

A pretrained có lịch sử dữ liệu train chưa xác minh; chia lại FER2013 không bảo đảm test mới chưa từng xuất hiện trong quá trình train A. Không gọi kết quả A là đánh giá độc lập chắc chắn. Thời gian chỉ so cùng máy/runtime/thread/warmup; không suy ra FPS camera từ thời gian classifier.

## Kiểm thử và kết quả cần thu

Bộ kiểm thử tự động bao gồm hash sai, ảnh trùng, bảo toàn ID/nhãn, giao thức mới, train/resume/export/CSV dự đoán trên dữ liệu tổng hợp và hồi quy giao thức cũ. Dữ liệu tổng hợp chỉ chứng minh luồng phần mềm, không chứng minh accuracy FER+.

Sau train đầy đủ cần thu config/history/status/checkpoint, ONNX+metadata, manifest, summary/predictions, đồ thị loss/validation, ma trận nhầm lẫn và ví dụ đúng/sai chọn theo quy tắc ghi rõ. Sau đó mới cập nhật báo cáo Word và thử camera. Không thay file model mặc định bằng checkpoint thử nghiệm.
