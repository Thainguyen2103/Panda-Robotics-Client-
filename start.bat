@echo off
title Panda System
echo ===================================
echo     KHOI DONG DU AN PANDA
echo ===================================
echo.
echo Luu y: Tat ca log se duoc gop chung vao cua so nay.
echo.

echo [1/3] Khoi dong Web Dashboard...
start /B "" cmd /c "cd web && node server.js"

echo [2/3] Khoi dong Virtual Robot...
start /B "" cmd /c "cd server && .\venv\Scripts\activate.bat && python virtual_robot.py"

echo [3/3] Khoi dong AI Brain...
:: Doi 2 giay de robot len mang truoc khi AI ket noi
timeout /t 2 /nobreak >nul
start /B "" cmd /c "cd server && .\venv\Scripts\activate.bat && python brain.py"

echo.
echo Dang mo trinh duyet...
timeout /t 2 /nobreak >nul
start http://localhost:3000

echo.
echo He thong dang chay! (Cac log dang hien thi ben duoi)
echo ---------------------------------------------------
echo DE TAT HE THONG: 
echo 1. Dong cua so nay lai.
echo 2. CLICK DUP VAO FILE stop.bat de dam bao tat sach tien trinh ngam.
echo ---------------------------------------------------
echo.

:: Giữ cửa sổ mở
cmd /k
