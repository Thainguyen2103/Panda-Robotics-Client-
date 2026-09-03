@echo off
title Panda Stopper
echo ===================================
echo     TAT TAT CA DICH VU PANDA
echo ===================================
echo.

echo Dang tat Web Dashboard...
taskkill /F /FI "WINDOWTITLE eq Administrator:  Panda Web Dashboard*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Panda Web Dashboard*" /T >nul 2>&1

echo Dang tat Virtual Robot...
taskkill /F /FI "WINDOWTITLE eq Administrator:  Panda Virtual Robot*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Panda Virtual Robot*" /T >nul 2>&1

echo Dang tat AI Brain...
taskkill /F /FI "WINDOWTITLE eq Administrator:  Panda AI Brain*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Panda AI Brain*" /T >nul 2>&1

echo.
echo Da tat toan bo he thong!
echo.
pause
