@echo off
chcp 65001 >nul
setlocal
REM 手动启动后端（前端由后端托管）。仅监听本机 8000，由 Nginx 反向代理对外提供 HTTPS。
set "ROOT=%~dp0.."
set "BACKEND=%ROOT%\backend"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%BACKEND%"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
echo 启动：http://127.0.0.1:8000  （API 文档 /docs，Ctrl+C 停止）
if exist "data\initial_password.txt" (
  echo ================ 登录信息 ================
  type data\initial_password.txt
  echo ==========================================
)
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
pause
