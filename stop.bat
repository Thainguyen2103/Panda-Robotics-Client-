@echo off
title Moon Stopper
echo ===================================
echo     TAT TAT CA DICH VU MOON
echo ===================================
echo.

echo Dang tat Web Dashboard...
taskkill /F /FI "WINDOWTITLE eq Administrator:  Moon Web Dashboard*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Moon Web Dashboard*" /T >nul 2>&1

echo Dang tat Virtual Robot...
taskkill /F /FI "WINDOWTITLE eq Administrator:  Moon Virtual Robot*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Moon Virtual Robot*" /T >nul 2>&1

echo Dang tat AI Brain...
taskkill /F /FI "WINDOWTITLE eq Administrator:  Moon AI Brain*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Moon AI Brain*" /T >nul 2>&1

echo.
echo Da tat toan bo he thong!
echo.
pause
