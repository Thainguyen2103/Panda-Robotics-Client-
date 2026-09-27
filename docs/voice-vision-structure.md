# Cấu trúc module Voice và Vision

Hai subsystem được chia theo miền chức năng. File mới nên được đặt vào
nhóm sở hữu dữ liệu/trạng thái đó, không đặt thêm logic vào facade
`__init__.py`, `core.py`, `features.py` hay `signals.py`.

## Voice

| Nhóm | Trách nhiệm |
|---|---|
| `audio/` | Xử lý PCM, RMS/phổ, VAD và chia đoạn câu nói |
| `speech/` | Gọi STT, lọc transcript, confidence và sửa ASR an toàn |
| `wake/` | Khớp tên Moon và Porcupine on-device |
| `runtime/` | Mic local, trạng thái phiên browser và WebSocket transport |
| `paths.py` | Vị trí model Voice local |
| `core.py` | Facade tương thích; không thêm logic mới |

Luồng browser: `runtime/web.py` → `runtime/session.py` → `audio/`, `speech/`,
`wake/`. Luồng mic local được điều phối tại `runtime/local.py`.

## Vision

| Nhóm | Trách nhiệm |
|---|---|
| `face/` | Landmark mặt, biểu cảm, mắt, ước lượng khoảng cách và cử chỉ đầu |
| `body/` | Khớp thân trên, góc khuỷu tay và cử chỉ cánh tay |
| `hands/` | Landmark bàn tay và cử chỉ ngón |
| `pipeline/` | Nạp model, lập lịch inference và tổng hợp kết quả mỗi frame |
| `runtime/` | Camera, mailbox frame, render JPEG và publish MQTT |
| `fusion.py` | Ghép các kênh hành động/đồ vật mà không ghi đè nhau |
| `stability.py` | Ổn định nhãn theo thời gian |
| `paths.py` | Vị trí model và dữ liệu sinh trắc local |

`features.py` và `signals.py` chỉ giữ import tương thích. Luồng chính là
`runtime/camera.py` → `pipeline/engine.py` → các module `face/body/hands`.
