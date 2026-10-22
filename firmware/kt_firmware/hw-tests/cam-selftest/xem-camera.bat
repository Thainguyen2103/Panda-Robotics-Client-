@echo off
REM Bam dup file nay de xem video camera tren laptop (nho DONG Serial Monitor truoc).
cd /d "%~dp0"
py -3.12 -c "import cv2, serial" 2>nul || py -3.12 -m pip install --user opencv-python pyserial
py -3.12 tools\viewer.py %*
pause
