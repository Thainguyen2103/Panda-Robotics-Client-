@echo off
title Moon System
set "PROJECT_ROOT=%~dp0"
echo ===================================
echo     KHOI DONG DU AN MOON
echo ===================================
echo.
echo Luu y: Tat ca log se duoc gop chung vao cua so nay.
echo.

if not exist "%PROJECT_ROOT%server\venv\Scripts\python.exe" (
    echo Khong tim thay Python cua du an:
    echo %PROJECT_ROOT%server\venv\Scripts\python.exe
    echo Hay tao moi moi truong server\venv va cai server\requirements.txt.
    pause
    exit /b 1
)

echo [1/3] Khoi dong Web Dashboard...
start /B "" /D "%PROJECT_ROOT%web" node server.js

echo [2/3] Khoi dong Virtual Robot...
:: Robot vat ly khong can khoi dong tien trinh rieng.

echo [3/3] Khoi dong AI Brain...
:: Goi thang Python trong server\venv de khong phu thuoc activation/PATH.
start /B "" /D "%PROJECT_ROOT%server" "%PROJECT_ROOT%server\venv\Scripts\python.exe" brain.py

echo.
echo Dang mo trinh duyet...
timeout /t 2 /nobreak >nul
start "" http://localhost:3000

echo.
echo He thong dang chay! (Cac log dang hien thi ben duoi)
echo ---------------------------------------------------
echo DE TAT HE THONG:
echo 1. Dong cua so nay lai.
echo 2. CLICK DUP VAO FILE stop.bat de dam bao tat sach tien trinh ngam.
echo ---------------------------------------------------
echo.

cmd /k
