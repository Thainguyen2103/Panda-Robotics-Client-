@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === TEST RIENG MIC: ghi am qua USB, nghe bang loa laptop ===
echo (Nho tat Serial Monitor truoc, neu khong se khong mo duoc cong USB)
echo.
py -3.12 -c "import serial" 2>nul || (
  echo Cai thu vien pyserial lan dau...
  py -3.12 -m pip install --quiet pyserial
)
py -3.12 tools\ghi_am_mic.py
echo.
pause
