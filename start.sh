#!/usr/bin/env bash
# 一键启动（WSL / Linux）：后端 8000 + 前端 5173
# 用法：bash start.sh            开发模式（前后端分开热更新）
#       bash start.sh --seed     启动前先生成演示数据
#       bash start.sh --prod     仅启动后端并托管已构建的前端（需先 npm run build）
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"

if [ ! -d .venv ]; then
  echo "[1/4] 创建 Python 虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "[2/4] 安装后端依赖 ..."
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已根据 .env.example 生成 backend/.env（默认离线 mock 模式，可在设置页配置模型）"
fi

if [[ "$*" == *"--seed"* ]]; then
  echo "[3/4] 生成演示数据 ..."
  python -m app.seed --reset
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT

show_login_info() {
  # 首次启动会自动创建管理员账号；密码在 data/initial_password.txt
  sleep 4
  if [ -f "$ROOT/backend/data/initial_password.txt" ]; then
    echo "================ 登录信息 ================"
    cat "$ROOT/backend/data/initial_password.txt"
    echo "=========================================="
  fi
}

if [[ "$*" == *"--prod"* ]]; then
  echo "[4/4] 生产模式：后端托管前端，访问 http://localhost:8000"
  show_login_info &
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi

echo "[4/4] 启动后端 http://localhost:8000 （API 文档 /docs）"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
show_login_info &

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  echo "安装前端依赖 ..."
  npm install
fi
echo "启动前端 http://localhost:5173"
npm run dev -- --host 0.0.0.0 &
wait
