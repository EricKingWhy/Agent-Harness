#!/usr/bin/env bash
# dev.sh — intelligence-agent 一键启动脚本（Git Bash / POSIX 友好）
#
# 用法：
#   ./dev.sh              起 Web（后端 :8000 + 前端 :5173），Ctrl+C 一起停
#   ./dev.sh web          同上（显式）
#   ./dev.sh cli          起交互式 CLI REPL（demo/live_agent.py）
#   ./dev.sh backend      只起后端
#   ./dev.sh frontend     只起前端
#   ./dev.sh help         显示用法
#
# 前置：
#   - .env 在仓库根（含 MODEL_API_KEY / MODEL_NAME；Langfuse 可选）
#   - uv 已装（后端依赖管理）
#   - pnpm 已装（前端依赖管理；首次需 cd web && pnpm install）

set -euo pipefail
cd "$(dirname "$0")"

# ── 颜色（终端不支持时自动失效） ──
if [[ -t 1 ]]; then
  C_RESET='\033[0m'; C_BLUE='\033[34m'; C_GREEN='\033[32m'
  C_YELLOW='\033[33m'; C_RED='\033[31m'; C_BOLD='\033[1m'
else
  C_RESET=''; C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_BOLD=''
fi

log()    { printf "${C_BLUE}▶${C_RESET} %s\n" "$*"; }
ok()     { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn()   { printf "${C_YELLOW}!${C_RESET} %s\n" "$*"; }
err()    { printf "${C_RED}✗${C_RESET} %s\n" "$*" >&2; }
header() { printf "\n${C_BOLD}${C_BLUE}═══ %s ═══${C_RESET}\n" "$*"; }

# ── 前置检查 ──
check_prereqs() {
  command -v uv >/dev/null 2>&1 || { err "未找到 uv。安装：pip install uv 或 https://docs.astral.sh/uv/"; exit 1; }
  [[ -f .env ]] || warn ".env 不在仓库根——后端可能因缺 MODEL_API_KEY 启动失败"
}

# ── 后端：FastAPI via uvicorn（:8000，热重载） ──
start_backend() {
  log "启动后端 FastAPI (uvicorn :8000, reload)..."
  exec uv run uvicorn agent_harness.web.app:create_prod_app \
    --factory \
    --reload \
    --host 127.0.0.1 \
    --port 8000
}

# ── 前端：Vite dev server（:5173，反代 /api → :8000） ──
start_frontend() {
  log "启动前端 Vite (:5173)..."
  if [[ ! -d web/node_modules ]]; then
    warn "前端依赖未装——先跑 pnpm install"
    (cd web && pnpm install)
  fi
  cd web && exec pnpm dev
}

# ── 交互式 CLI REPL ──
start_cli() {
  log "启动交互式 CLI (demo/live_agent.py)..."
  exec uv run python demo/live_agent.py
}

# ── Web：后端 + 前端并行，Ctrl+C 一起停 ──
start_web() {
  header "启动 Web（后端 + 前端）"

  if [[ ! -d web/node_modules ]]; then
    warn "前端依赖未装——先跑 pnpm install"
    (cd web && pnpm install)
  fi

  BACKEND_PID=""
  FRONTEND_PID=""

  cleanup() {
    header "关闭中（kill 后端 + 前端）"
    [[ -n "$BACKEND_PID" ]]  && kill "$BACKEND_PID"  2>/dev/null && ok "后端已停 (pid $BACKEND_PID)"
    [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null && ok "前端已停 (pid $FRONTEND_PID)"
    wait 2>/dev/null
    ok "完成"
  }
  trap cleanup EXIT INT TERM

  # 后端
  log "后端 → http://127.0.0.1:8000 (uvicorn reload)"
  uv run uvicorn agent_harness.web.app:create_prod_app \
    --factory --reload --host 127.0.0.1 --port 8000 &
  BACKEND_PID=$!

  # 给后端一点时间起来再起前端（避免前端代理首请求扑空）
  sleep 2

  # 前端
  log "前端 → http://127.0.0.1:5173 (vite, /api → :8000)"
  (cd web && pnpm dev) &
  FRONTEND_PID=$!

  ok "两个服务已起。打开 http://127.0.0.1:5173 用 Web；Ctrl+C 一起停。"
  printf "\n"
  wait
}

# ── 用法 ──
show_help() {
  cat <<'EOF'
dev.sh — intelligence-agent 开发启动脚本

用法：
  ./dev.sh              起 Web（后端 :8000 + 前端 :5173），Ctrl+C 一起停
  ./dev.sh web          同上（显式）
  ./dev.sh cli          起交互式 CLI REPL（demo/live_agent.py，输一行一个任务）
  ./dev.sh backend      只起后端 FastAPI (:8000)
  ./dev.sh frontend     只起前端 Vite (:5173)
  ./dev.sh help         显示本帮助

端口：
  后端  http://127.0.0.1:8000    FastAPI (uvicorn --reload)
  前端  http://127.0.0.1:5173    Vite dev (/api 反代到后端)

其它常用命令（不在本脚本内）：
  uv run agent-harness "你的任务"           一次性 CLI（chat）
  uv run agent-harness sessions             列 session
  uv run agent-harness fork <session_id>    fork 一个 session
  uv run agent-harness replay <session_id>  重放一个 session
  uv run agent-harness ingest <file>        知识库摄取
  uv run pytest -q                          全量测试
  uv run pytest tests/integration/test_phase16_gate.py -m integration -v   Phase 16 Gate
EOF
}

# ── 派发 ──
check_prereqs

case "${1:-web}" in
  web)        start_web ;;
  cli)        start_cli ;;
  backend)    start_backend ;;
  frontend)   start_frontend ;;
  help|-h|--help) show_help ;;
  *)          err "未知参数: $1"; show_help; exit 1 ;;
esac
