# FER+ CNN v1 — kết quả tải về từ Colab

Ngày kiểm tra: 23/10/2026. Nhánh: `thai+emotion-recognition-training`.
Nguồn: `comparison.json`, `summary.csv`, hai ONNX và metadata do người dùng tải
từ Drive. Đã đối chiếu hash từng model với cả metadata và báo cáo.

## Kết quả test trên 3.376 ảnh

| Model | Accuracy | Macro-F1 | Balanced accuracy |
|---|---:|---:|---:|
| Pretrained | 81,87% | 61,06% | 57,49% |
| Hard, seed 42 | 84,95% | 73,08% | 69,40% |
| Soft, seed 42 | 83,12% | 69,71% | 68,06% |

Ứng viên chính là hard-seed42, chọn theo validation trước khi mở test. Checkpoint
được xuất ở epoch 73, validation macro-F1 75,3933%. Cấu hình: CNN v1, khởi tạo
ngẫu nhiên, batch 128, AdamW lr 0,001, weight decay 0,0001, tối đa 80 epoch,
patience 12, tăng cường ảnh, protocol shared-v1.

- Hard SHA256: `71c297f36305c1958c4fca3b4b2d9c23f037fe27a78621989d39a06130f37762`.
- Soft SHA256: `a3a7e95768059e8fc816765e3d3992eace7b6adf696869a0b7b7078c63dd91b7`.
- Dataset fingerprint: `031b2f600ccd8c57a8c7a1ce00f5483980b22e0195424689730f51303b7dc000`.

Chỉ có một seed; 531 nhóm ảnh trùng giữa split. Đây không phải phép đánh giá
không rò rỉ hay kết quả webcam. Thời gian suy luận trong báo cáo được đo trên
CPU Colab, chưa phải tốc độ tại máy PBL4. Các lớp hiếm vẫn yếu: recall test của
hard là disgust 45,45%, fear 50%, contempt 42,31%.

## Kiểm tra tại máy PBL4

Cả hai ONNX nạp được bằng OpenCV tại máy. Đã chạy qua hàm
`emotion_probabilities` của Vision với ba ảnh nhân tạo mức pixel 0, 128, 255:
đủ tám giá trị hữu hạn, tổng xác suất bằng một. Đây chỉ là kiểm tra tương thích
đầu vào/đầu ra, chưa xác minh chất lượng trên người thật.

Model và báo cáo đầy đủ lưu cục bộ trong `models/vision/ferplus-custom-v1/`,
được loại khỏi Git. Không ghi đè pretrained.

## Chạy thử

Đóng phiên ứng dụng cũ trước khi mở `start-emotion-custom.bat` để tiến trình
mới nhận đúng cấu hình model. Launcher đặt đường dẫn model B cho phiên chạy
đó rồi gọi `start.bat`; không thay cấu hình mặc định của dự án.

Để quay về pretrained, đóng phiên thử và dùng `start.bat` trong môi trường
không đặt `MOON_EMOTION_MODEL`. Chưa tự khởi động camera/robot khi cài artifact.
