@echo off
setlocal
cd /d "%~dp0"

echo 将打开两个窗口: 后端 8000 + 前端 3008
start "promanager-backend" cmd /k call "%~dp0start-backend.cmd"
timeout /t 2 /nobreak >nul
start "promanager-frontend" cmd /k call "%~dp0start-frontend.cmd"
exit /b 0
