#!/usr/bin/env bash
# 一键部署到 Linux 服务器（Ubuntu/Debian，已在腾讯云 Ubuntu 22.04 上验证思路）：
#   1) 构建前端  2) 创建后端 venv 并安装依赖  3) 写 systemd 服务（后端仅监听 127.0.0.1:8000）
#   4) 安装 Caddy 并生成 Caddyfile，自动为公网 IP 申请 Let's Encrypt 证书并自动续期
# 用法：
#   sudo bash deploy/install.sh                 # 自动检测公网 IP
#   sudo bash deploy/install.sh --ip 1.2.3.4    # 指定 IP
#   sudo bash deploy/install.sh --self-signed   # 无法放行 80 端口时改用自签名证书
#   sudo bash deploy/install.sh --skip-caddy    # 只装后端服务，不装 Caddy
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"
PUBLIC_IP=""
SELF_SIGNED=0
SKIP_CADDY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip) PUBLIC_IP="$2"; shift 2;;
    --self-signed) SELF_SIGNED=1; shift;;
    --skip-caddy) SKIP_CADDY=1; shift;;
    *) echo "未知参数 $1"; exit 1;;
  esac
done

log() { echo -e "\033[1;32m[deploy]\033[0m $*"; }

# ---------- 1. 前端构建 ----------
if ! command -v node >/dev/null; then
  log "安装 Node.js 20 ..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
log "构建前端 ..."
sudo -u "$RUN_USER" bash -c "cd '$ROOT/frontend' && npm install && npm run build"

# ---------- 2. 后端环境 ----------
apt-get install -y python3-venv python3-pip >/dev/null
log "安装后端依赖 ..."
sudo -u "$RUN_USER" bash -c "cd '$ROOT/backend' && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
if [ ! -f "$ROOT/backend/.env" ]; then
  sudo -u "$RUN_USER" cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  log "已生成 backend/.env，请稍后在网页设置中配置模型，或直接编辑该文件"
fi

# ---------- 3. systemd ----------
log "写入 systemd 服务 diet-diary ..."
sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$RUN_USER#g" "$ROOT/deploy/diet-diary.service" > /etc/systemd/system/diet-diary.service
systemctl daemon-reload
systemctl enable --now diet-diary
sleep 2
systemctl --no-pager status diet-diary | head -5 || true

if [ -f "$ROOT/backend/data/initial_password.txt" ]; then
  echo "================ 初始登录信息 ================"
  cat "$ROOT/backend/data/initial_password.txt"
  echo "=============================================="
fi

if [ "$SKIP_CADDY" = "1" ]; then
  log "已跳过 Caddy。后端监听 127.0.0.1:8000，请自行配置反向代理。"
  exit 0
fi

# ---------- 4. Caddy ----------
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP="$(curl -4 -s --max-time 5 https://ifconfig.me || curl -4 -s --max-time 5 https://api.ipify.org || true)"
fi
if [ -z "$PUBLIC_IP" ]; then
  echo "无法自动获取公网 IP，请用 --ip 指定"; exit 1
fi
log "公网 IP：$PUBLIC_IP"

if ! command -v caddy >/dev/null; then
  log "安装 Caddy（官方 apt 源）..."
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi
CADDY_VER="$(caddy version | awk '{print $1}' | sed 's/^v//')"
log "Caddy 版本 $CADDY_VER（IP 证书需要 ≥ 2.10.2；过低请执行 caddy upgrade 或从 GitHub 下载最新二进制）"

TEMPLATE="$ROOT/deploy/Caddyfile.template"
[ "$SELF_SIGNED" = "1" ] && TEMPLATE="$ROOT/deploy/Caddyfile.selfsigned.template"
sed "s#__PUBLIC_IP__#$PUBLIC_IP#g" "$TEMPLATE" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

log "完成！访问 https://$PUBLIC_IP"
log "证书申请日志：journalctl -u caddy -n 50 --no-pager | grep -i -E 'certificate|obtain|error'"
log "安全组请只放行 80、443；关闭 8000 / 5173 的公网访问。"
