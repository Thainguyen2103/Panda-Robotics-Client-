@echo off
cd /d "%~dp0"
echo Moon Voice Lab: http://localhost:8765
if exist server\venv\Scripts\python.exe (
    server\venv\Scripts\python.exe -m server.voice_lab
) else (
    python -m server.voice_lab
)
pause
