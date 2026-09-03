try:
    import cv2
except ImportError:
    cv2 = None
    print("⚠️ [VISION] OpenCV (cv2) not installed. Using pure mock detection.")

import time
import random
import base64
import server.mqtt_bridge as mqtt_bridge
import sys
import os
import threading
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings

# Biến toàn cục để chia sẻ giữa các luồng
shared_frame = None
shared_face_box = None
latest_person_detected = False
latest_emotion = "neutral"
lock = threading.Lock()

EMOTIONS = ["neutral", "happy", "surprised", "sad", "angry", "disgust", "fear", "contempt"]

def face_thread(callback):
    global shared_frame, shared_face_box, latest_person_detected, latest_emotion
    print("🧠 [VISION THREAD] Bắt đầu luồng xử lý AI Vision (YOLOv8)...")
    
    emotion_net = None
    yunet = None
    sface = None
    master_feature = None
    
    master_file = os.path.join(os.path.dirname(__file__), "master_face.npy")
    if os.path.exists(master_file):
        master_feature = np.load(master_file)

    try:
        base_dir = os.path.dirname(__file__)
        emotion_net = cv2.dnn.readNetFromONNX(os.path.join(base_dir, 'emotion-ferplus-8.onnx'))
        yunet = cv2.FaceDetectorYN_create(os.path.join(base_dir, 'face_detection_yunet_2023mar.onnx'), "", (320, 320), 0.5)
        sface = cv2.FaceRecognizerSF_create(os.path.join(base_dir, 'face_recognition_sface_2021dec.onnx'), "")
    except Exception as e:
        print(f"⚠️ [VISION THREAD] Lỗi tải AI models: {e}")
        
    from collections import deque, Counter
    emotion_history = deque(maxlen=5)

    while True:
        with lock:
            frame = shared_frame
            
        if frame is None:
            time.sleep(0.1)
            continue
            
        person_detected = False
        action = "neutral"
        face_box_to_share = None
        emotion = "neutral"
        identity = "Guest"
        
        if yunet and sface and emotion_net:
            try:
                # Đặt kích thước đầu vào cho YuNet (Cực kỳ quan trọng)
                yunet.setInputSize((frame.shape[1], frame.shape[0]))
                _, faces = yunet.detect(frame)
                
                if faces is not None and len(faces) > 0:
                    person_detected = True
                    # Tìm khuôn mặt bự nhất
                    best_face = max(faces, key=lambda f: f[2] * f[3])
                    x, y, w, h = int(best_face[0]), int(best_face[1]), int(best_face[2]), int(best_face[3])
                    face_box_to_share = (x, y, w, h)
                    
                    # 1. Căn chỉnh khuôn mặt bằng SFace
                    aligned_face = sface.alignCrop(frame, best_face)
                    
                    # 2. Nhận diện danh tính
                    feature = sface.feature(aligned_face)
                    if master_feature is None:
                        master_feature = feature
                        np.save(master_file, master_feature)
                        identity = "Master"
                    else:
                        score = sface.match(master_feature, feature, cv2.FaceRecognizerSF_FR_COSINE)
                        if score >= 0.363:
                            identity = "Master"
                    action = f"face_detected ({identity})"
                    
                    # 3. Nhận diện cảm xúc bằng FER+ trên khuôn mặt đã căn chỉnh hoàn hảo
                    gray_face = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2GRAY)
                    gray_face = cv2.resize(gray_face, (64, 64))
                    
                    # Xử lý ngược sáng (Backlight Compensation):
                    # Tự động đo độ sáng trung bình của khuôn mặt, nếu bị tối do ngược sáng thì nâng sáng bằng Auto-Gamma
                    face_mean_brightness = np.mean(gray_face)
                    if face_mean_brightness < 120.0 and face_mean_brightness > 10.0:
                        gamma = np.log(120.0 / 255.0) / np.log(face_mean_brightness / 255.0)
                        gamma = np.clip(gamma, 0.4, 2.0)
                        inv_gamma = 1.0 / gamma
                        lut = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
                        gray_face = cv2.LUT(gray_face, lut)
                    
                    # Cân bằng sáng thích ứng CLAHE: giữ rõ nét chi tiết chân mày (nhíu mày) và khóe môi
                    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                    gray_face = clahe.apply(gray_face)
                    
                    blob = cv2.dnn.blobFromImage(gray_face, 1.0, (64, 64), (0,), swapRB=False, crop=False)
                    emotion_net.setInput(blob)
                    preds = emotion_net.forward()
                    
                    # Chuyển đổi raw logits thành xác suất (probabilities) bằng Softmax
                    logits = preds[0]
                    e_x = np.exp(logits - np.max(logits))
                    probs = e_x / e_x.sum()
                    
                    # Trọng số cân bằng độ nhạy:
                    # - Giảm bớt ưu thế áp đảo của neutral (0.7)
                    # - Tăng mạnh độ nhạy cho sad (2.4), angry (2.4), disgust (1.8), fear (1.6)
                    # EMOTIONS = ["neutral", "happy", "surprised", "sad", "angry", "disgust", "fear", "contempt"]
                    # Index:       0          1         2            3      4        5          6       7
                    sensitivity_weights = np.array([0.7, 1.0, 1.0, 2.4, 2.4, 1.8, 1.6, 1.4])
                    weighted_probs = probs * sensitivity_weights
                    
                    raw_idx = np.argmax(weighted_probs)
                    raw_emotion = EMOTIONS[raw_idx]
                    
                    # Gom nhóm các biểu cảm vi mô liên quan để tăng độ chuẩn xác
                    if raw_emotion in ["angry", "disgust", "contempt"]:
                        mapped_emotion = "angry"
                    elif raw_emotion in ["sad", "fear"]:
                        mapped_emotion = "sad"
                    else:
                        mapped_emotion = raw_emotion
                    
                    emotion_history.append(mapped_emotion)
                    emotion = Counter(emotion_history).most_common(1)[0][0]
                else:
                    emotion_history.clear()
                    
            except Exception as e:
                print(f"⚠️ [VISION THREAD] Lỗi xử lý All-ONNX: {e}")  
            
        with lock:
            latest_person_detected = person_detected
            latest_emotion = emotion
            shared_face_box = face_box_to_share
            
        # Gửi callback
        try:
            callback(person_detected, emotion, action)
        except Exception as e:
            print(f"⚠️ [VISION THREAD] Lỗi ở callback: {e}")
            
        time.sleep(0.1) # Chạy AI 10 lần/giây để không nghẽn CPU

def start_vision(callback):
    global shared_frame
    print("👁️ [VISION] Khởi động module thị giác...")
            
    # Bật luồng AI
    ai_thread = threading.Thread(target=face_thread, args=(callback,), daemon=True)
    ai_thread.start()
    
    cap = None
    if cv2:
        cap = cv2.VideoCapture(settings.WEBCAM_INDEX)
        if not cap.isOpened():
            print("❌ [VISION] Không thể mở webcam!")
            cap = None

    print("👁️ [VISION] Đang chạy vòng lặp truyền hình ảnh...")
    
    frame_time = 1.0 / 15.0 # Stream ở 15 FPS cho mượt
    
    while True:
        start_t = time.time()
        
        frame = None
        if cap:
            ret, cap_frame = cap.read()
            if not ret:
                break
            # Dùng frame đọc từ camera
            frame = cap_frame
            
        if frame is not None:
            # Cập nhật frame cho luồng AI
            with lock:
                shared_frame = frame.copy()
                box = shared_face_box
                
            display_frame = frame.copy()
            
            # Vẽ Box bao quanh khuôn mặt nếu có
            if box is not None:
                x, y, w, h = box
                cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(display_frame, "Face", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                
            # Stream thẳng lên Web
            small_frame = cv2.resize(display_frame, (400, 300))
            _, buffer = cv2.imencode('.jpg', small_frame, [cv2.IMWRITE_JPEG_QUALITY, 40])
            b64_str = base64.b64encode(buffer).decode('utf-8')
            mqtt_bridge.publish(settings.TOPIC_CAMERA, b64_str)

        elapsed = time.time() - start_t
        if elapsed < frame_time:
            time.sleep(frame_time - elapsed)

if __name__ == "__main__":
    def test_callback(detected, emotion, action):
        pass
    start_vision(test_callback)
