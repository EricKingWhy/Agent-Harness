#!/usr/bin/env bash
# intelligence-agent —— 单端口启动脚本（云沙箱 / 任意 Linux 主机通用）
#
# 后端 FastAPI 同时提供 API 与前端静态资源（web/dist），只需一个端口。
# 端口取 $PORT（云沙箱注入），缺省 8000。
set -euo pipefail
cd "$(dirname "$0")"

# 选解释器：优先 $PYTHON_BIN，否则 python3 / python
PY="${PYTHON_BIN:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ]; then echo "未找到 python 解释器" >&2; exit 1; fi

# 源码在 src/ 下，直接加进模块搜索路径（无需 pip install 本包）
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

echo "[start] python=$PY port=${PORT:-8000} cwd=$(pwd)"
exec "$PY" -m uvicorn agent_harness.web.app:create_prod_app \
  --factory --host 0.0.0.0 --port "${PORT:-8000}"
