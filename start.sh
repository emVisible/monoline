#!/usr/bin/env bash
# Monoline — 一键启动 / one-click launcher.
#   ./start.sh          启动（首次会自动装依赖），并打开浏览器
#   MONOLINE_PORT=9000 ./start.sh   换端口
set -euo pipefail
cd "$(dirname "$0")"

export MONOLINE_PORT="${MONOLINE_PORT:-8787}"
URL="http://127.0.0.1:${MONOLINE_PORT}"

say(){ printf '\033[36m›\033[0m %s\n' "$*"; }
die(){ printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# 1) 依赖预检 ---------------------------------------------------------------
command -v uv     >/dev/null 2>&1 || die "未找到 uv。安装：curl -LsSf https://astral.sh/uv/install.sh | sh"
command -v ffmpeg >/dev/null 2>&1 || die "未找到 ffmpeg。安装：brew install ffmpeg"
command -v make   >/dev/null 2>&1 || die "未找到 make。安装 Xcode 命令行工具：xcode-select --install"

# 2) 尽量加载 nvm，让 node 22 可用（渲染 sidecar 需要，缺失只影响渲染不影响启动）
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo '')"
if [ "$NODE_MAJOR" != "22" ]; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 && nvm use 22 >/dev/null 2>&1 || true
fi

# 3) 已在运行？——判据必须是「这是 Monoline」，不是「端口有人应答」。
#    共享开发机上端口是抢占式资源：本机另一个项目（Hertz 的 uvicorn）就占过 8787，
#    而旧判据 `curl /` 对任何 HTTP 服务都退出 0（邻居回 404 也算"通"），
#    于是启动器把邻居的 404 页当成「Monoline 已在运行」打开了浏览器。
if curl -s -m 3 "${URL}/api/themes" 2>/dev/null | grep -q '"mono-ink"'; then
  say "Monoline 已在运行：${URL}（打开浏览器）"
  open "$URL" 2>/dev/null || true
  exit 0
fi
if curl -s -o /dev/null -m 2 "${URL}/" 2>/dev/null; then
  OWNER="$(lsof -nP -iTCP:"${MONOLINE_PORT}" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" pid="$2}')"
  die "端口 ${MONOLINE_PORT} 上跑的是别的程序（${OWNER:-未知}），不是 Monoline。换个端口：MONOLINE_PORT=8788 ./start.sh"
fi

# 4) 首次运行：安装依赖（Python venv + pnpm 前端/sidecar）-------------------
if [ ! -d backend/.venv ] || [ ! -d node_modules ] || [ ! -d sidecar/node_modules ]; then
  say "首次运行，安装依赖（约 1–3 分钟）…"
  make bootstrap
fi

# 5) 启动：构建前端(如缺) → 拉起渲染 sidecar → 打开浏览器 → 常驻服务 ---------
say "启动 Monoline → ${URL}   （按 Ctrl+C 停止）"
exec make start
