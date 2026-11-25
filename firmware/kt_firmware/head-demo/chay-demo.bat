x`@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === PANDA head-demo: camera + man hinh + loa ===
echo (Nho dong Serial Monitor truoc)
echo.
if not exist .venv (
  echo Tao moi truong Python lan dau, mat vai phut...
  py -3.12 -m venv .venv || goto :loi
  .venv\Scripts\python.exe -m pip install --quiet -r tools\requirements.txt || goto :loi
)
if not exist models\face_detection_yunet_2023mar.onnx curl -L -o models\face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
if not exist models\emotion-ferplus-8.onnx curl -L -o models\emotion-ferplus-8.onnx https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx
if not exist models\face_landmarker.task curl -L -o models\face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
if not exist gemini-key.txt (
  echo.
  echo CHUA CO GEMINI KEY: phan giong noi se tat, camera + man hinh van chay.
  echo Lay key mien phi o https://aistudio.google.com/apikey roi dan vao file gemini-key.txt
  echo.
)
.venv\Scripts\python.exe tools\head_demo.py %*
pause
exit /b
:loi
echo LOI cai dat. Xoa thu muc .venv roi chay lai.
pause
