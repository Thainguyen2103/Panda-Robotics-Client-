# Tự huấn luyện biểu cảm bằng FER+

## Phạm vi và nhánh

Làm việc trên `thai+emotion-recognition-training`, tách từ commit `67b7185`.
Giữ model `emotion-ferplus-8.onnx` và hành vi mặc định của Vision.
Cloud dùng để train; model xuất ONNX chạy tại máy PBL4.

Notebook: [ferplus_training_colab.ipynb](../notebooks/ferplus_training_colab.ipynb).
[Mở trực tiếp bằng Google Colab](https://colab.research.google.com/github/Thainguyen2103/Panda-Robotics-Client-/blob/thai%2Bemotion-recognition-training/notebooks/ferplus_training_colab.ipynb).
Mở notebook trong Google Colab, chọn GPU và chạy từng mục. Notebook lấy code
đúng nhánh, hướng dẫn lấy ảnh FER2013 trên Kaggle, tải nhãn FER+ từ Microsoft,
giữ dữ liệu/checkpoint trên Drive và vẽ biểu đồ từ kết quả chạy thật.

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

Ghép bằng thứ tự dòng CSV và Usage. Tên ảnh trong file nhãn gốc không luôn
bằng chỉ số dòng và có bốn tên bị lặp; chỉ báo các tên lặp trong manifest,
không loại hay đổi thứ tự mẫu vì tên ảnh. ID mẫu nội bộ dựa trên dòng CSV.

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

## Chuẩn bị trên Colab

1. Tải `fer2013.csv` từ [Kaggle challenge gốc](https://www.kaggle.com/c/challenges-in-representation-learning-facial-expression-recognition-challenge/data),
   giải nén và đặt vào `MyDrive/PBL4-FERPlus/raw/`. Cần tự đăng nhập/chấp nhận
   điều kiện truy cập Kaggle. Không lưu token trong notebook.
2. Notebook tải `fer2013new.csv` từ repository FER+; không thay bằng tập bảy lớp.
3. Chép `C:\PBL4\models\vision\emotion-ferplus-8.onnx` lên
   `MyDrive/PBL4-FERPlus/models/` để giữ đúng file đối chứng. SHA256 hiện tại:
   `a2a2ba6a335a3b29c21acb6272f962bd3d47f84952aaffa03b60986e04efa61c`.
4. Chạy một seed để kiểm tra và lựa chọn cấu hình trên validation; sau đó dùng
   ba seed `[42, 123, 2026]` cho cùng cấu hình B/C. Notebook mặc định chưa mở test.

## Chạy ngoài Colab

Cài `training/emotion/requirements.txt` trong môi trường Python riêng. Không
thay `server/requirements.txt` bằng bộ thư viện train. Ví dụ các lệnh sau chạy
tại gốc repository; dùng đường dẫn ngoài Git cho dữ liệu và kết quả:

```powershell
python -m training.emotion.data --fer2013 C:\FERPlus\raw\fer2013.csv --ferplus C:\FERPlus\raw\fer2013new.csv --output C:\FERPlus\prepared-v1

python -m training.emotion.train --data C:\FERPlus\prepared-v1 --output C:\FERPlus\runs\hard-seed42 --mode hard --seed 42
python -m training.emotion.train --data C:\FERPlus\prepared-v1 --output C:\FERPlus\runs\soft-seed42 --mode soft --seed 42
```

Lặp lại lệnh train có thêm `--resume` để tiếp tục `last.pt`; giữ nguyên toàn bộ
hyperparameter, kể cả ngân sách `--epochs`. Có thể dùng `--session-epochs 10`
để chủ động dừng sau 10 epoch mỗi phiên. Dừng giữa epoch sẽ quay lại từ cuối
epoch đã lưu; không hứa khôi phục đúng batch chưa lưu. RNG được phục hồi; tính
khớp bit chỉ được kiểm tra trên cùng môi trường CPU, không bảo đảm giữa các
GPU/phiên bản thư viện khác nhau. Phiên bản thư viện và Git revision được lưu.

```powershell
python -m training.emotion.export --checkpoint C:\FERPlus\runs\soft-seed42\best.pt --data C:\FERPlus\prepared-v1 --output C:\FERPlus\exports\soft-seed42.onnx

python -m training.emotion.evaluate --data C:\FERPlus\prepared-v1 --model pretrained=models/vision/emotion-ferplus-8.onnx --model custom=C:\FERPlus\exports\soft-seed42.onnx --output C:\FERPlus\reports\validation-v1
```

Thêm `--split test` chỉ sau khi chốt cấu hình. Đánh giá trực tiếp không chạy
detector, không fusion và không luật thời gian. Độ trễ gồm setInput/forward và
kiểm tra đầu ra, không gồm resize/phát hiện mặt. Dùng `summary.csv` để so số;
`comparison.json` chứa cấu hình, nhãn, hash, confusion matrix và dự đoán mỗi ảnh.
Muốn so ba seed, truyền cả sáu file B/C bằng sáu đối số `--model` cùng baseline.

Export cố ý dùng TorchScript exporter (`dynamo=False`, opset 13) để tương thích
`cv2.dnn`; PyTorch mới có thể báo deprecated. Chỉ dùng artifact sau khi cả
ONNX Runtime và OpenCV qua parity. Giữ file `.onnx.json` cạnh `.onnx` để công cụ
so sánh xác minh hash và thứ tự nhãn.

## Thử với Vision hiện tại

```powershell
$env:MOON_EMOTION_MODEL = 'C:\FERPlus\exports\soft-seed42.onnx'
.\start.bat
```

Khởi động từ đúng phiên PowerShell đã đặt biến. Khi muốn quay lại mặc định:
`Remove-Item Env:MOON_EMOTION_MODEL` rồi khởi động lại. Không ghi đè file model gốc.
Ảnh camera có nhãn đánh giá bằng công cụ hiện có, chọn file riêng từng lần:

```powershell
.\server\venv\Scripts\python.exe tools\evaluate_emotions.py C:\EmotionTest --model C:\FERPlus\exports\soft-seed42.onnx --output C:\EmotionResults\custom.json
```

Ảnh camera cần đủ tám lớp, tách theo người/phiên; giữ detector, crop, landmark
và ngưỡng khi so lần đầu. Tối ưu ngưỡng riêng phải là thử nghiệm bổ sung dùng
validation. Video gán nhãn mới đo được nhảy nhãn và độ trễ xác nhận; bộ công cụ
hiện tại chưa tự động chấm hai chỉ số video này.

## Xác minh triển khai

- 7 kiểm thử offline mới: ghép/lọc dữ liệu, hash/trùng split, metric đủ tám lớp,
  target hard/soft, train thật trên dữ liệu nhân tạo, resume chính xác trên CPU,
  khôi phục lần lưu bị ngắt, xuất ONNX và parity PyTorch/ORT/OpenCV, so cùng ảnh.
- 54 kiểm thử Vision hiện có và kiểm thử giao diện Vision đã qua.
- Notebook kiểm tra cú pháp tất cả ô code, không chứa output/ảnh/dataset/token.
- Đã chạy các ô train B/C, xuất model, so A/B/C, vẽ biểu đồ, chạy lại từ
  checkpoint và đọc báo cáo đã lưu trên dữ liệu nhân tạo 24 ảnh (tám lớp mỗi
  split), với file pretrained thật làm đối chứng. Đây chỉ là kiểm tra luồng.
- Các kiểm thử này không phải kết quả FER+ thật, không chứng minh model mới
  vượt pretrained. Chưa chạy GPU Colab và chưa có kết quả camera từ model mới.
