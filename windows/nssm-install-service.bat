@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM  用 NSSM 把后端注册为 Windows 服务（开机自启、崩溃自动重启）
REM  1. 从 https://nssm.cc/download 下载 nssm，把 win64\nssm.exe 放到本目录
REM  2. 以管理员身份运行本脚本
REM  卸载：nssm remove DietDiary confirm
REM ============================================================
set "ROOT=%~dp0.."
set "BACKEND=%ROOT%\backend"
set "NSSM=%~dp0nssm.exe"
if not exist "%NSSM%" (echo 未找到 %NSSM%，请先下载 nssm.exe 放到 windows\ 目录 & pause & exit /b 1)
if not exist "%BACKEND%\.venv\Scripts\python.exe" (echo 请先运行 install-windows.bat & pause & exit /b 1)
if not exist "%~dp0logs" mkdir "%~dp0logs"

"%NSSM%" install DietDiary "%BACKEND%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
"%NSSM%" set DietDiary AppDirectory "%BACKEND%"
"%NSSM%" set DietDiary AppEnvironmentExtra PYTHONIOENCODING=utf-8 PYTHONUTF8=1
"%NSSM%" set DietDiary AppStdout "%~dp0logs\service.out.log"
"%NSSM%" set DietDiary AppStderr "%~dp0logs\service.err.log"
"%NSSM%" set DietDiary AppRotateFiles 1
"%NSSM%" set DietDiary AppRotateBytes 10485760
"%NSSM%" set DietDiary Start SERVICE_AUTO_START
"%NSSM%" set DietDiary AppExit Default Restart
"%NSSM%" set DietDiary Description "今天吃得怎么样 · AI 饮食观察日记 后端"
"%NSSM%" start DietDiary
echo 服务 DietDiary 已安装并启动。日志：windows\logs\
pause
