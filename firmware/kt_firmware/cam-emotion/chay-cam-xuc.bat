@echo off
REM Bam dup de mo camera + AI cam xuc tren laptop (nho DONG Serial Monitor truoc).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Lan dau: dang cai moi truong Python ^(vai phut^)...
  py -3.12 -m venv .venv
  .venv\Scripts\python.exe -m pip install -r tools\requirements.txt
)
REM 3 mo hinh Thai dung (khong dua len git vi nang ~39MB) — tai tu nguon goc neu chua co
if not exist models mkdir models
if not exist models\face_detection_yunet_2023mar.onnx curl -L -o models\face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
if not exist models\emotion-ferplus-8.onnx curl -L -o models\emotion-ferplus-8.onnx https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx
if not exist models\face_landmarker.task curl -L -o models\face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
.venv\Scripts\python.exe tools\emotion_viewer.py %*
pause
