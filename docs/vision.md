# Computer vision cho Panda

> Bản mở rộng hiện tại (08/09/2026): xem [hướng dẫn tín hiệu mới](vision-signals.md)
> cho bàn tay 21 mốc, tổ hợp cử chỉ, hướng nhìn/mắt, khoảng cách, đồ vật và điểm biểu cảm liên tục.

## Phạm vi hiện tại

Một người đứng/ngồi đối diện camera; khung hình thấy mặt, hai vai và cổ tay khi
vẫy chào. Không cần nhìn thấy chân. Chọn khuôn mặt đang theo dõi bằng độ chồng
lấp, ưu tiên mặt lớn nhất khi bắt đầu; ghép phần thân chứa tâm mặt đó.
Đây là theo dõi hình học đơn giản, chưa phải định danh nhiều người khi họ đi
chéo nhau hoặc che khuất nhau.

| Chức năng | Cách xử lý | Giới hạn |
|---|---|---|
| Phát hiện mặt | YuNet, ảnh thu nhỏ 320 px, trả tọa độ về ảnh gốc | Mặt nhỏ, quay ngang, che mặt làm giảm chất lượng |
| Chủ nhân / khách | SFace, so khớp cosine với mẫu đã đăng ký | Chỉ một chủ nhân; không có chống giả mạo bằng ảnh/video |
| Biểu cảm | FER+ trên crop vuông không kéo giãn, kết hợp tín hiệu chân mày/mắt/mũi/môi từ MediaPipe, giữ nhãn ngắn khi chưa chắc | Ước lượng biểu cảm nhìn thấy, không khẳng định trạng thái tâm lý |
| Vẫy tay | YOLOv8n-pose, cổ tay ở trên vai và có chuyển động đi–về, ưu tiên đo tương đối với khuỷu tay | Cần cổ tay trong hình; cử động ngón tay riêng chưa hỗ trợ |
| Giơ tay | Cổ tay cao hơn vai qua nhiều lần đo | Một hoặc hai tay |
| Gật/lắc đầu | Góc pitch/yaw từ ma trận mặt MediaPipe, lọc rung và kiểm tra xoay đi–về | Ngưỡng thử nghiệm 8°/10°, cần hiệu chỉnh bằng video demo thật |

Nhãn hành động: `waving`, `hand_raised`, `both_hands_up`, `head_nod`, `head_shake`,
`unknown`. Cử chỉ đầu được giữ 0,7 giây ở backend; dashboard giữ sự kiện tối đa
1,8 giây để đọc. Một lần quay một hướng không đủ để kích hoạt. MediaPipe tạo
mốc mặt chi tiết và ma trận biến đổi; gật/lắc dựa trên góc đầu, không phụ thuộc
chỉ vào tỷ lệ mũi–miệng như bản trước. Nếu thiếu mô hình mới, hệ thống báo lỗi
mô hình và dùng cách mốc YuNet cũ làm phương án dự phòng.

Buồn/giận/chán ghét/sợ/khinh miệt nhẹ cần cả FER+ xếp nhãn đó trong hai ứng viên
đầu và tín hiệu mốc mặt phù hợp trong khoảng 0,65 giây. Các biểu cảm rõ còn có
thể được xác nhận bằng tổ hợp chân mày, mắt, mũi và môi; một kết quả FER+ khác
trung tính đã đủ rõ sẽ không bị tín hiệu hình học ghi đè. Không nhân trọng số
hoặc chuyển một nhãn FER+ rõ thành cảm xúc khác. Dòng “Dấu hiệu mặt” mô tả tín
hiệu hình học; đó không phải một kết luận về cảm xúc. Nhãn backend giữ tối đa
3 lần đo chưa chắc; mất mặt/đổi người xóa ngay lịch sử. Chưa có tập video gán
nhãn để xác nhận mức cải thiện độ chính xác.

Dashboard cập nhật chữ theo nhịp 250 ms, chờ nhãn ổn định, giữ ngắn khi chưa rõ.
Nhãn chính hiển thị tối đa năm khả năng có điểm hợp nhất cao nhất theo thứ tự giảm
dần, mỗi khả năng trên một dòng, ví dụ `Vui (60%)`, `Trung tính (30%)`, rồi
`Ngạc nhiên (10%)`. Bảng chi tiết vẫn hiển thị riêng phần trăm của đủ tám đầu ra
FER+ và bảy mức kích hoạt hình học để chẩn đoán. Đây là độ tin cậy/độ kích hoạt
ước lượng, không phải phép đo chắc chắn cảm xúc thật của người dùng.
Bỏ log bản tin `panda/user_status` trùng để Activity Log không cuộn từng khung hình.

### Dữ liệu khớp cánh tay

`upper_body_joints` có `left/right_shoulder`, `left/right_elbow`, `left/right_wrist`.
Mỗi khớp có `x`, `y` chuẩn hóa theo ảnh (0–1), `confidence`, `visible`. Khi khớp
bị che/khuất hình, x/y là null; không dùng tọa độ đó điều khiển robot.
`elbow_angles.left/right` là góc 2D trên ảnh, không phải góc cơ thể 3D.
`pose_time` là thời gian đơn điệu của lần suy luận pose để kiểm tra độ cũ trong
cùng tiến trình. Skeleton chỉ vẽ khi kết quả chưa quá 0,5 giây. Sáu khớp cánh tay tiếp tục được giữ; bản mới bổ sung `hands[]` với 21 mốc mỗi bàn tay (xem hướng dẫn tín hiệu mới).


## Luồng xử lý

- Luồng camera chỉ giữ khung hình mới nhất; không xếp hàng ảnh cũ.
- Luồng AI: mục tiêu 10 Hz cho mặt/đầu, tối đa 5 Hz cho tay, 3 Hz cho biểu cảm,
  1 Hz cho danh tính. Mốc mặt chi tiết chạy cùng nhịp tìm mặt. Kết quả biểu cảm/danh tính được giữ giữa các lần đo trên
  cùng mặt; lịch sử bị xóa khi mất mặt, đổi vùng theo dõi hoặc mặt quá nhỏ.
- Luồng chính truyền JPEG tối đa 12 FPS, giữ tỷ lệ khung hình. Các mức FPS là
  giới hạn trên, không phải cam kết hiệu năng của mọi máy.
- Từng mô hình tải và báo lỗi độc lập. Thiếu FER+ vẫn phát hiện mặt và cử chỉ.
- Không có ảnh mới/kết quả mới quá 2 giây: báo mất camera/AI chậm và xóa kết quả
  nhận diện gửi cho robot. Camera đọc lỗi sẽ được mở lại.
- Một số backend RTSP có thể chặn lâu trong `read()`; trạng thái vẫn hết hạn,
  nhưng việc mở lại camera phải đợi backend trả về. Webcam/MJPEG cần thử với
  thiết bị thực tế trước khi triển khai.

Giữ callback ba tham số của `brain.py`; công bố đầy đủ kết quả qua
`panda/vision/status` và topic tương thích `panda/user_status`. Dashboard nhận
trạng thái, danh tính, biểu cảm, cử chỉ đầu/tay và thời gian xử lý. Vision không
phát lệnh motor theo cử chỉ. Cơ chế chào khi thấy người có sẵn của brain vẫn hoạt động.

`panda/camera` là ảnh JPEG base64 **đầu ra** dành cho dashboard; không phải topic
nhận ảnh từ ESP32. Camera mạng dùng URL qua `PANDA_CAMERA_SOURCE`.

## Chạy và kiểm tra

Từ thư mục gốc `C:\PBL4`, dùng môi trường Python sẵn có của dự án:

```powershell
# Kiểm tra mô hình bằng ảnh trống, không kết nối robot
.\server\venv\Scripts\python.exe tools\check_vision.py

# Kiểm tra camera thật; không gửi MQTT/lệnh robot, không lưu ảnh
.\server\venv\Scripts\python.exe tools\check_vision.py --camera --frames 100

# Chạy riêng camera + dashboard MQTT (cần broker đang chạy)
.\server\venv\Scripts\python.exe -m server.vision

# Toàn bộ dự án
.\start.bat

# Dùng camera mạng: thay bằng địa chỉ thiết bị của bạn
$env:PANDA_CAMERA_SOURCE = 'http://<dia-chi-esp32>:81/stream'
.\server\venv\Scripts\python.exe -m server.vision

# Kiểm thử logic và lỗi
.\server\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Các file cần ở `server/`: `face_detection_yunet_2023mar.onnx`,
`face_recognition_sface_2021dec.onnx`, `emotion-ferplus-8.onnx`, `yolov8n-pose.pt`,
`face_landmarker.task` (3,8 MB).
Không tự tải model trong lúc khởi động. Môi trường đã kiểm tra tại máy này:
OpenCV contrib 5.0.0, NumPy 2.5.2, Ultralytics 8.4.120, MediaPipe 0.10.35; phiên bản khác cần chạy lại
diagnostic. Các ngưỡng và lịch xử lý nằm trong `config/settings.py`.

Tải model mốc mặt khi cài trên máy khác (máy phát triển đã tải sẵn):

```powershell
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task' -OutFile server/face_landmarker.task
node tests/test_vision_ui.cjs
```

SHA256 của model đã kiểm tra:
`64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.
Không commit file `.task`; nó đã được bỏ qua trong Git. URL latest có thể đổi,
nên đối chiếu hash khi tái lập kết quả trên máy khác.

### Kiểm tra sau phản hồi demo

19 kiểm thử Python và bộ kiểm thử giữ nhãn giao diện đều qua. Camera thật với
model mới: 40/40 khung hình có mặt, trung vị 81,5 ms, p95 183,9 ms, khoảng 6,2 Hz
trong diagnostic tuần tự. Lượt chạy đầy đủ khác có 43/43 kết quả với góc đầu và
các tín hiệu mặt, không lỗi mô hình. Đây là kiểm tra dữ liệu/hiệu năng, không
phải xác nhận gật/lắc hoặc buồn/giận đúng trên 43 mẫu. Khởi động lạnh có thể mất
hơn 10 giây do nạp và khởi tạo nhiều mô hình.

### Kết quả bản trước khi thêm mốc mặt chi tiết (07/09/2026)

Lượt chạy luồng camera–AI–JPEG đầy đủ trong 22 giây, đầu ra thu bằng hàm kiểm tra
thay MQTT để không phát lệnh robot: 68 kết quả AI hợp lệ, khoảng **8,2 Hz AI**
sau khởi động, **10,8 FPS JPEG**, trung vị suy luận **48,7 ms**, không có lỗi
mô hình. Đoạn chạy ngắn này không đo độ trễ broker, mạng hay dashboard.
Khởi động đầu tiên có chi phí nạp mô hình/khởi tạo đồ thị vài giây.

Lượt diagnostic camera riêng 60 khung hình: phát hiện mặt 60/60, trung vị 71,8 ms,
p95 221,8 ms; đây không phải tập kiểm định nhận diện danh tính/biểu cảm/cử chỉ.
Hiệu năng thay đổi theo ánh sáng, số người và tải CPU khi chạy cả voice/LLM/TTS.

## Đăng ký chủ nhân

Không tự nhận người đầu tiên làm chủ nhân nữa. Mẫu `master_face.npy` có sẵn vẫn
được đọc; nếu trước đây mẫu được tạo nhầm, đăng ký lại bằng ít nhất ba ảnh khác
nhau, chỉ có một người, mặt rõ nét, đủ sáng, chủ yếu nhìn thẳng:

```powershell
.\server\venv\Scripts\python.exe tools\enroll_face.py anh1.jpg anh2.jpg anh3.jpg --replace
```

Bỏ `--replace` khi chưa có mẫu. Công cụ kiểm tra số mặt, độ nét và sự nhất quán
giữa các mẫu rồi mới thay file. Khởi động lại vision để nạp mẫu mới. Không đưa
ảnh đăng ký vào Git; embedding `.npy` đã nằm trong `.gitignore`.

## Kịch bản kiểm tra demo

1. Để mặt và vai trong hình, đứng yên 10 giây: không xuất hiện vẫy/gật/lắc.
2. Giơ tay giữ yên: `hand_raised`, không phải `waving`.
3. Vẫy ngang rõ 2–3 nhịp, cổ tay trên vai; lặp 10 lần mỗi tay.
4. Nhìn thẳng rồi gật xuống–lên, lắc trái–phải; lặp riêng 10 lần mỗi cử chỉ.
5. Nói chuyện, cười, quay mặt một hướng, dịch người: đếm nhận nhầm.
6. Đưa cổ tay khỏi hình, che mặt, rời camera: kết quả phải về `unknown`.
7. Rút/cắm camera: dashboard báo mất camera, không giữ danh tính cũ.

Ghi tỷ lệ nhận đúng, nhận nhầm và độ trễ trên camera/laptop dùng cho demo. Các
test tự động dùng mốc tổng hợp chỉ kiểm tra logic; không chứng minh độ chính xác
gật/lắc/vẫy trên người thật. Chưa có bộ video gán nhãn để công bố accuracy.

## Cơ sở mô hình

- [OpenCV Zoo — YuNet và SFace](https://github.com/opencv/opencv_zoo).
- [FER+ ONNX: đầu vào 64×64, tám nhãn và softmax](https://github.com/onnx/models/tree/main/validated/vision/body_analysis/emotion_ferplus).
  Không nhân trọng số buồn/giận hay gộp nhãn thành cảm xúc khác.
- [Ultralytics pose: thứ tự 17 mốc COCO](https://docs.ultralytics.com/tasks/pose/).
  Chỉ dùng mốc thân trên; nhãn cử chỉ do quy tắc thời gian của dự án tạo ra.

- [MediaPipe Face Landmarker: landmarks, blendshapes và transformation matrix](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python).
