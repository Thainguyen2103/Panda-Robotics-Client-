@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MOON dua xe
echo === MOON: CHE DO DUA XE (chi lai than, nhanh het muc) ===
echo Tat chay-demo.bat truoc neu dang mo.
echo.
if not exist .venv (
  echo Tao moi truong Python lan dau, mat vai phut...
  py -3.12 -m venv .venv || goto :loi
  .venv\Scripts\python.exe -m pip install --quiet -r tools\requirements.txt || goto :loi
)
.venv\Scripts\python.exe tools\dua_xe.py %*
pause
exit /b
:loi
echo LOI cai dat. Xoa thu muc .venv roi chay lai.
pause
