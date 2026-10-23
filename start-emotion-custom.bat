@echo off
setlocal
cd /d "%~dp0"
set "MOON_EMOTION_MODEL=%~dp0models\vision\ferplus-custom-v1\hard-seed42.onnx"
if not exist "%MOON_EMOTION_MODEL%" (
    echo Missing custom model: %MOON_EMOTION_MODEL%
    echo Copy the verified hard-seed42.onnx export into models\vision\ferplus-custom-v1 first.
    pause
    exit /b 1
)
echo Using custom FER+ model: %MOON_EMOTION_MODEL%
call "%~dp0start.bat"
endlocal
