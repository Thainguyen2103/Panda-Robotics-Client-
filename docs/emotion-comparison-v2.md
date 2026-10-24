# Báo cáo kiểm chứng FERPlus phiên bản 2

File Word mới: `Bao_cao_Kiem_chung_FERPlus_PBL4_v2.docx`.
Giữ nguyên bản Word cũ có chỉnh sửa của người dùng.

## Dữ liệu và phương pháp

Giữ nguyên ba file ONNX, seed và checkpoint; không train hoặc chọn lại theo test.
Model A dùng PIL LANCZOS theo model card. B/C dùng OpenCV INTER_AREA như train.
Kiểm tra hash ảnh CSV, nhãn Microsoft, từng model và thứ tự mẫu trong báo cáo
gốc trước khi chạy lại toàn bộ 3.376 ảnh. Chấm thêm 3.074 ảnh sau khi bỏ 302 ảnh
test trùng pixel với train/validation theo manifest cũ. Đây là subset sensitivity,
không phải huấn luyện lại với một bộ chia sạch; không loại ảnh gần giống/cùng người.

| Model | Accuracy 3376 | Macro F1 3376 | Accuracy 3074 | Macro F1 3074 |
|---|---:|---:|---:|---:|
| A LANCZOS | 82,55% | 61,84% | 82,34% | 58,95% |
| B hard | 84,95% | 73,08% | 83,77% | 68,14% |
| C soft | 83,12% | 69,71% | 82,47% | 66,48% |

## Ví dụ thực tế và chống suy diễn từ vài ảnh

Ảnh minh họa nằm trong subset 3.074 mẫu, chọn theo mẫu đúng/sai A/B/C, ưu tiên
tỷ lệ phiếu FER+ cho nhãn tham chiếu cao nhất, rồi dòng CSV nhỏ nhất. Không phải
mẫu ngẫu nhiên để ước lượng chất lượng. Đúng/sai chỉ so argmax với nhãn FER+.

| Dòng CSV zero based | Nhãn FER+ | A | B | C |
|---|---|---|---|---|
| 32415 | happy 10/10 phiếu | neutral sai | happy đúng | happy đúng |
| 32327 | happy 10/10 phiếu | happy đúng | neutral sai | fear sai |
| 33520 | happy 10/10 phiếu | neutral sai | neutral sai | happy đúng |
| 32695 | surprised 10/10 phiếu | happy sai | happy sai | sad sai |

Toàn subset: cả ba đúng 2235; A B đúng 135; A C đúng 83; B C đúng 141;
chỉ A đúng 78; chỉ B đúng 64; chỉ C đúng 76; cả ba sai 262. Tổng 3074.
Điểm softmax không được hiệu chuẩn, không coi là xác suất tâm lý thực.

## Chạy lại công cụ kiểm chứng

Cần dependencies trong `training/emotion/requirements.txt`. Ví dụ tại gốc repo:

```powershell
.\server\venv\Scripts\python.exe tools\audit_ferplus_models.py --fer2013 C:\Users\thaiv\Downloads\archive\fer2013.csv --source-report models/vision/ferplus-custom-v1/comparison.json --model-dir models/vision/ferplus-custom-v1 --baseline models/vision/emotion-ferplus-8.onnx --output C:\FERPlus\audit-v2
```

Đầu ra trong thư mục mới: audit.json, predictions.jsonl, ảnh minh họa và NPZ ảnh
test. Không ghi đè model hoặc ảnh gốc. Công cụ cần truy cập file nhãn Microsoft;
hash phải khớp manifest, nếu nguồn thay đổi thì dừng thay vì tiếp tục âm thầm.
Không chia sẻ thư mục chứa trọng số nếu chỉ muốn chia sẻ kết quả.

`docs/ferplus_v2_evidence.json` lưu nguồn hash, metrics, số mẫu, từng lớp, ma trận
nhầm lẫn, kết quả kiểm tra runtime và tám điểm của ba model cho từng ảnh ví dụ.
Điểm tốc độ Colab từ bản cũ không được dùng làm bằng chứng tốc độ máy PBL4.

## Kiểm tra tài liệu

Báo cáo Word được xuất PDF bằng Microsoft Word và raster hóa để kiểm tra từng
trang. Trang ảnh giữ pixel gốc, phóng bằng nearest neighbor, không tạo ảnh bằng AI.
Các ví dụ là biểu cảm gán nhãn bởi cộng đồng; không khẳng định tâm lý của người.

Nguồn chính: Microsoft FERPlus và bài báo Barsoum et al. ICMI 2016; ONNX Model
Zoo model card và Git LFS pointer. Đường dẫn đầy đủ nằm trong báo cáo Word.
