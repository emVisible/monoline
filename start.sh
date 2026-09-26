#!/usr/bin/env bash
# Monoline — 一键启动 / one-click launcher.
#   ./start.sh          前台常驻启动（首次自动装依赖，日志直接打在终端，Ctrl+C 停止）
#   MONOLINE_PORT=9000 ./start.sh   换端口
#   端口若被占（上一次没退干净的 Monoline，或别的项目）会先杀掉占用者再接管——
#   脚本不会再"发现已在运行就退出"，那会让你看不到日志也没法 Ctrl+C。
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

# 3) 端口必须归本脚本所有：先清掉占用者，再前台启动 ---------------------------
#    为什么仍然打印被杀进程的命令行：共享开发机上端口是抢占式资源（本机另一个项目的
#    uvicorn 就占过 8787），清端口是刻意的，但「清掉了谁」必须看得见，否则一次误杀无从追查。
free_port(){
  local pids p owner waited
  pids="$(lsof -nP -iTCP:"${MONOLINE_PORT}" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
  if [ -z "$pids" ]; then
    return 0
  fi
  for p in $pids; do
    owner="$(ps -o command= -p "$p" 2>/dev/null | cut -c1-80 || true)"
    say "端口 ${MONOLINE_PORT} 被占用，先清掉：pid=${p}  ${owner:-未知}"
    kill "$p" 2>/dev/null || true
  done
  waited=0
  while [ "$waited" -lt 20 ]; do
    if ! lsof -nP -iTCP:"${MONOLINE_PORT}" -sTCP:LISTEN -t >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
    waited=$((waited + 1))
  done
  for p in $(lsof -nP -iTCP:"${MONOLINE_PORT}" -sTCP:LISTEN -t 2>/dev/null | sort -u || true); do
    say "pid=${p} 没响应 SIGTERM，改发 SIGKILL"
    kill -9 "$p" 2>/dev/null || true
  done
  sleep 0.5
  if lsof -nP -iTCP:"${MONOLINE_PORT}" -sTCP:LISTEN -t >/dev/null 2>&1; then
    die "端口 ${MONOLINE_PORT} 清不掉，换个端口再试：MONOLINE_PORT=8788 ./start.sh"
  fi
  return 0
}
# 4) 首次运行：安装依赖（Python venv + pnpm 前端/sidecar）-------------------
if [ ! -d backend/.venv ] || [ ! -d node_modules ] || [ ! -d sidecar/node_modules ]; then
  say "首次运行，安装依赖（约 1–3 分钟）…"
  make bootstrap
fi

# 清端口要贴着 bind 做：放在依赖安装之前会留出几分钟的空档（实测过一次——空档里
# 冒出来的监听者没被清掉，两边同时监听，只是 IPv4/IPv6  scope 不同才没炸）。
free_port

# 5) 前台常驻：构建前端(如缺) → 拉起渲染 sidecar → 打开浏览器 → uvicorn 在本进程内跑
#    用 exec 是为了让终端就是服务器：日志直接打在屏幕上，Ctrl+C 直接停（不再自行退出）。
say "启动 Monoline → ${URL}   （前台常驻，日志在此显示，按 Ctrl+C 停止）"
exec make start
