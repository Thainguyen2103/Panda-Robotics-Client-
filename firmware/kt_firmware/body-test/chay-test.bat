@echo off
REM Lai thu phan than: giu L / R. Lan dau tu tao moi truong Python + cai pyserial.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Lan dau: tao moi truong Python...
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\python.exe -m pip install --quiet pyserial
)
.venv\Scripts\python.exe tools\lai_xe.py %*
pause
