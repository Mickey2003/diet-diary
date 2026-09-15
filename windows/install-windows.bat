@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM  今天吃得怎么样 · Windows 一次性安装脚本
REM  作用：在 backend\ 下创建虚拟环境、安装依赖、生成 .env
REM  要求：已安装 Python 3.10+ 并加入 PATH（宝塔 Python 项目管理器安装的版本
REM        通常在 C:\BtSoft\python\3.11\python.exe，可用 PY 变量指定）
REM ============================================================
set "ROOT=%~dp0.."
set "BACKEND=%ROOT%\backend"
if "%PY%"=="" set "PY=python"

echo [1/4] 检查 Python ...
"%PY%" --version || (echo 未找到 Python，请安装 3.10+ 或设置 PY=完整路径 & pause & exit /b 1)

echo [2/4] 创建虚拟环境 %BACKEND%\.venv ...
if not exist "%BACKEND%\.venv\Scripts\python.exe" "%PY%" -m venv "%BACKEND%\.venv"

echo [3/4] 安装依赖（如网络慢可先执行: pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple）...
"%BACKEND%\.venv\Scripts\python.exe" -m pip install --upgrade pip >nul
"%BACKEND%\.venv\Scripts\python.exe" -m pip install -r "%BACKEND%\requirements.txt" || (echo 依赖安装失败 & pause & exit /b 1)

echo [4/4] 生成 .env ...
if not exist "%BACKEND%\.env" (
  copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
  echo 已生成 backend\.env（默认离线 mock 模式；模型请在网页「模型设置」配置）
)
if not exist "%BACKEND%\data" mkdir "%BACKEND%\data"
if not exist "%BACKEND%\uploads" mkdir "%BACKEND%\uploads"

echo.
echo 安装完成。测试运行：windows\start-windows.bat
echo 长期运行：用宝塔「Python 项目管理器」或 windows\nssm-install-service.bat 注册为服务
pause
