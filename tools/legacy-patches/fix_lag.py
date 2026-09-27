import os

filepath = 'server/vision.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''        if frame is not None:
            # Stream camera to web dashboard
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            b64_str = base64.b64encode(buffer).decode('utf-8')
            mqtt_bridge.publish(settings.TOPIC_CAMERA, b64_str)

        if frame_count % 3 == 0:'''

new_code = '''        if frame is not None:
            # Stream camera to web dashboard (giảm độ phân giải để đỡ lag)
            small_frame = cv2.resize(frame, (320, 240))
            _, buffer = cv2.imencode('.jpg', small_frame, [cv2.IMWRITE_JPEG_QUALITY, 30])
            b64_str = base64.b64encode(buffer).decode('utf-8')
            mqtt_bridge.publish(settings.TOPIC_CAMERA, b64_str)

        # Chạy YOLO mỗi 10 frame thay vì 3 để giảm tải CPU
        if frame_count % 10 == 0:'''

content = content.replace(old_code, new_code)
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print('Lag fixed!')
