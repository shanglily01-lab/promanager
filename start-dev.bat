@echo off
set ROOT=%~dp0
echo 将打开两个窗口：① 后端 API :8000  ② 前端 :3008
echo 关闭对应窗口即停止该服务。
start "promanager-api" cmd /k "cd /d "%ROOT%backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --reload-delay 1 --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
start "promanager-ui" cmd /k "cd /d "%ROOT%frontend" && npm run dev"
