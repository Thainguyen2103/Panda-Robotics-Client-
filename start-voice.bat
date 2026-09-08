@echo off
cd /d "%~dp0"
echo Moon Dashboard: http://localhost:3000
echo Voice only - no Brain or LLM
node web\server.js
pause
