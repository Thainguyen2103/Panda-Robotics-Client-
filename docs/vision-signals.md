# Vision mở rộng — 08/09/2026

## Cách dùng

Khởi động lại brain bằng `start.bat`, tải lại dashboard với Ctrl+F5. Model bàn
tay đã tải vào `server/hand_landmarker.task`. Khi chuyển sang máy khác:

```powershell
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task' -OutFile server/hand_landmarker.task
```

Không tự tải model lúc khởi động. Thiếu model nào sẽ báo lỗi riêng, các nhánh
khác tiếp tục hoạt động. Bật/tắt/tần suất trong `config/settings.py`.

## Biểu cảm

- Cười rõ (`smile >= 0.45`) được phép đổi nhãn sau 0,18 giây, kể cả FER+ nghiêng
  về trung tính. Ngạc nhiên cần cả mở miệng và mở mắt/nâng mày; chỉ há miệng
  khi nói hoặc ngáp không đủ. Đây là các quy tắc thực nghiệm trên blendshapes.
- FER+ dùng thời gian ổn định 0,30 giây; ứng viên buồn/giận được mốc mặt hỗ trợ
  cần 0,65 giây. Không còn chờ ba lần suy luận rồi lại chờ thêm nửa giây ở UI.
- Cấu hình chân mày + nheo mắt/ép môi hoặc chân mày + hạ khóe miệng đủ mạnh
  cũng có thể tạo nhãn giận/buồn độc lập FER sau 0,65 giây. Chỉ một biến đổi
  nhỏ ở chân mày không đủ. Đây vẫn là quy tắc biểu cảm, có thể nhầm tập trung
  với giận; điểm mốc mặt luôn được tách khỏi điểm FER.
- `emotion_probs`: đủ 8 điểm FER+ đã làm mượt, tổng xấp xỉ 1. Đây là xác suất
  phân lớp của mô hình, không phải xác suất cảm xúc thực tế của người.
- `expression_intensities`: mức kích hoạt hình học của cười/ngạc nhiên/buồn/giận.
  Các điểm độc lập, không cộng thành 1, không tương đương `emotion_probs`.
- `emotion_source`: `fer`, `fer+landmarks`, `landmarks`, `uncertain`.
  `emotion_confidence` là điểm từ nguồn đó, không so sánh trực tiếp giữa nguồn.
- Dashboard có mục mở rộng “Điểm FER+ liên tục”, kèm các mức kích hoạt mốc mặt.

Giới hạn: độ nhạy của buồn/giận vẫn phụ thuộc người, ánh sáng, góc quay và mô
hình. Chưa có bộ video gán nhãn để kết luận tỷ lệ chính xác. Không coi biểu cảm
là bằng chứng chắc chắn về trạng thái tâm lý.

## Bàn tay và tổ hợp cử chỉ

MediaPipe Hand Landmarker trả tối đa 2 bàn tay, mỗi tay 21 mốc x/y/z, điểm
handedness. Điểm handedness không phải độ tin cậy của từng khớp. Skeleton
ngón tay được vẽ trên camera, song song skeleton cánh tay.

Quy tắc ban đầu: `victory` (hai ngón V), `thumbs_up` (like), `open_palm`,
`pointing`, `fist`. Cần hai lần nhận cùng nhãn trên cùng tay. Đây chưa phải
mô hình học hành động tổng quát; một số hướng bàn tay hoặc ngón bị che sẽ
trả `unknown`. Giơ V là cử chỉ V, không có nghĩa chắc chắn là đang chào.

`hands[]`: `side`, `associated`, `confidence`, `gesture`, `landmarks`, `timestamp`.
Ghép bàn tay với người đang theo dõi bằng cổ tay pose hoặc vùng thân. Khi
không ghép được, vẫn xuất mốc bàn tay nhưng không đưa vào hành động của người.
Phân biệt nhiều người/che khuất/đổi tay nhanh còn có thể ghép nhầm.

`actions[]` chứa đồng thời các kênh, ví dụ:

```json
[
  {"channel":"head", "label":"head_shake"},
  {"channel":"arms", "label":"hand_raised"},
  {"channel":"left_hand", "label":"victory"},
  {"channel":"right_hand", "label":"thumbs_up"}
]
```

`action` cũ giữ tương thích dạng chuỗi nối bằng ` + `. Các dòng đầu/cánh tay/
tay trái/tay phải trên dashboard độc lập, không che mất nhau. UI giữ sự kiện
ngắn 1,8 giây để đọc; robot nên dùng `actions`, không đọc nhãn UI để quyết định.
Kết quả đến từ các lịch suy luận khác nhau, được ghép trong cửa sổ thời gian
ngắn, không khẳng định tất cả được đo đúng cùng một thời điểm.

## Hướng nhìn và trạng thái mắt

`eyes.gaze`: `toward_camera`, `away`, `unknown`. Kết hợp vị trí tâm mống mắt
trong hai mắt (cả ngang/dọc), góc đầu và trạng thái mở mắt. Đây là ước lượng
nhìn về camera, không chứng minh chú ý/eye contact với robot nếu camera đặt
khác vị trí mắt robot. Chưa có hiệu chuẩn hướng nhìn theo từng người.

EAR được tính từ 6 mốc mỗi mắt, có hysteresis mở/đóng và blendshape eyeBlink
để hỗ trợ. `state`: `open`, `closed`, `prolonged_closure`, `unknown`.
Nhắm mắt liên tục 1,5 giây đặt `possible_drowsiness=true`; chỉ là dấu hiệu có
thể buồn ngủ, không phải chẩn đoán. Không suy ra nervous/lo lắng từ blink rate.

`blink_count_60s`, `blink_rate_per_min`, `closed_fraction`, `sample_fps`,
`observed_seconds`, `quality` được xuất. Đợi ít nhất 20 giây dữ liệu liên tục
mới có rate/fraction. Mất mặt hoặc khoảng lấy mẫu >0,4 giây xóa cửa sổ để
không tính khoảng thiếu dữ liệu thành nhắm mắt. Tần suất dưới 15 Hz báo
`limited_sampling`; nhiều chớp mắt nhanh có thể bị bỏ sót. Không dùng tính
năng này như hệ thống cảnh báo an toàn khi lái xe.

## Khoảng cách

`distance.cm` ước lượng theo kích thước mặt. Mặc định dùng HFOV giả định 60°
và chiều rộng mặt 14 cm, hiển thị `~… cm *` / nguồn `assumed_fov`. Hai giả định
có thể sai, đặc biệt với trẻ em. Mặt quá nhỏ hoặc quay >20° trả unavailable.

Để hiệu chuẩn, đặt cùng người ở khoảng cách đã đo, lấy `face_box[2]` và chiều
rộng khung hình đang xử lý (mặc định 640), rồi chạy:

```powershell
.\server\venv\Scripts\python.exe tools\calibrate_distance.py --distance-cm 60 --face-width-px 160 --frame-width-px 640
```

Ví dụ trên trả `VISION_DISTANCE_SCALE_CM = 15`. Điền vào settings hoặc đặt
`$env:PANDA_DISTANCE_SCALE_CM = '15'` trước khởi động. Công thức là
`distance_cm = scale * frame_width / face_width`. Làm lại khi đổi zoom/camera
hoặc người. Số ví dụ không phải kết quả đo camera của bạn.

## Đồ vật

YOLOv8n dùng `server/yolov8n.pt`, xuất `objects[]` gồm nhãn, điểm, box chuẩn hóa,
timestamp và `near_hands`. Ly/chai/sách/điện thoại được dịch trên dashboard.
“Gần tay” chỉ dựa vào lân cận hình học 2D, không khẳng định đang cầm/nắm.
Không thấy đồ vật không có nghĩa đồ vật không tồn tại.

## Tần suất và dữ liệu cũ

Mốc mặt/đầu/mắt ưu tiên theo từng frame. Mỗi frame chỉ chạy tối đa một nhánh
nặng phụ (danh tính, FER, pose, hands hoặc objects), chọn theo mức trễ so với
tần suất cấu hình. `secondary_stage` cho biết nhánh được chạy; các FPS là trần,
không phải tốc độ bảo đảm. Không tính rate chớp mắt theo FPS cấu hình.

Pose quá 0,75 giây, hands quá 0,6 giây, objects quá 1,5 giây sẽ bị xóa. Kết quả
mất camera/AI quá hạn xóa toàn bộ dữ liệu; UI mất bản tin >4 giây cũng xóa.
Timestamp là đồng hồ đơn điệu của tiến trình sản xuất; không so trực tiếp
với đồng hồ hệ thống trên máy khác.

## Kiểm tra

```powershell
.\server\venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_vision_ui.cjs
.\server\venv\Scripts\python.exe tools/check_vision.py --camera --frames 100
```

Test tự động kiểm tra công thức, dữ liệu thiếu, nhận tổ hợp, giữ/xóa UI và quy
tắc cử chỉ trên mốc tổng hợp. Cần test thực tế từng trường hợp: cười tự nhiên,
nói/há miệng không ngạc nhiên, V/like mỗi tay, vừa lắc đầu vừa giơ tay, nhìn
lệch bằng mắt, nhắm mắt 2 giây, bỏ đồ vật vào/ra khung hình và rút camera.

Kết quả kiểm tra ngày 08/09/2026: 29 test Python và các test UI đều qua. Bảy
mô hình tải và suy luận không lỗi trong diagnostic camera. Lượt đầu có mặt
24/40 khung hình; lượt sau đổi lịch có 50 khung hình nhưng không có mặt nên
không dùng lượt đó để khẳng định tốc độ xử lý đầy đủ mặt/tay. Dashboard được
kiểm tra bằng dữ liệu mô phỏng bốn kênh cử chỉ cùng lúc và điểm số liên tục;
đó không phải kết quả đánh giá độ chính xác nhận diện cử chỉ từ camera.

Nguồn mô hình/API: [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python),
[Hand Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python),
[Ultralytics predict](https://docs.ultralytics.com/modes/predict/).
