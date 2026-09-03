import os

filepath = 'server/vision.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Thay doi khung hinh va chat luong de DOM do bi giat
content = content.replace("frame_time = 1.0 / 24.0", "frame_time = 1.0 / 15.0")
content = content.replace("small_frame = cv2.resize(frame, (480, 360))", "small_frame = cv2.resize(frame, (400, 300))")
content = content.replace("_, buffer = cv2.imencode('.jpg', small_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])", "_, buffer = cv2.imencode('.jpg', small_frame, [cv2.IMWRITE_JPEG_QUALITY, 40])")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Optimized!")
