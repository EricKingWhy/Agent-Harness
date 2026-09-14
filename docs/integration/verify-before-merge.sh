#!/usr/bin/env bash
# 集成前校验脚本 —— feat/frontend → main
#
# 用法（在有 git 凭证的终端）：
#   bash docs/integration/verify-before-merge.sh
#
# 只做**只读检查**：不 merge、不 push、不改任何 ref。
# 哈希会随时间过期，故本脚本**每次都重新实测**，不信任任何文档里的常量。

set -uo pipefail

REMOTE_URL="https://github.com/EricKingWhy/intelligence-agent.git"
BRANCH="feat/frontend"
MAIN="main"

pass=0
fail=0
ok()   { echo "  [OK]   $*"; pass=$((pass+1)); }
bad()  { echo "  [FAIL] $*"; fail=$((fail+1)); }
info() { echo "  [info] $*"; }
hdr()  { echo; echo "── $* ──"; }

hdr "0. 环境"
if ! command -v git >/dev/null 2>&1; then
  bad "未找到 git"
  exit 1
fi
info "git $(git --version)"
info "工作目录 $(pwd)"
if [ ! -e .git ]; then
  bad "当前目录不是 git 工作树（请在 D:\\intelligence-agent-frontend 下运行）"
  exit 1
fi

hdr "1. 远端实测（不信任文档里的哈希）"
ls_out=$(git ls-remote "$REMOTE_URL" "refs/heads/$BRANCH" "refs/heads/$MAIN" 2>/dev/null)
if [ -z "$ls_out" ]; then
  bad "git ls-remote 失败（网络/凭证问题）"
  exit 1
fi
REMOTE_BRANCH_SHA=$(echo "$ls_out" | awk -v b="refs/heads/$BRANCH" '$2==b {print $1}')
REMOTE_MAIN_SHA=$(echo "$ls_out" | awk -v b="refs/heads/$MAIN" '$2==b {print $1}')
info "$BRANCH = $REMOTE_BRANCH_SHA"
info "$MAIN     = $REMOTE_MAIN_SHA"
[ -n "$REMOTE_BRANCH_SHA" ] && ok "取到 $BRANCH" || bad "取不到 $BRANCH"
[ -n "$REMOTE_MAIN_SHA" ]   && ok "取到 $MAIN"     || bad "取不到 $MAIN"

hdr "2. 本地工作树干净度"
dirty=$(git status --porcelain --untracked-files=no)
if [ -z "$dirty" ]; then
  ok "无已跟踪文件的未提交改动"
else
  bad "有未提交改动 —— 请先处理："
  echo "$dirty" | sed 's/^/         /'
fi
info "未跟踪文件（不影响 merge，仅供参考）："
git status --porcelain --untracked-files=all | grep '^??' | sed 's/^/         /' || info "（无）"

hdr "3. 本地 HEAD 与远端是否对齐"
LOCAL_HEAD=$(git rev-parse HEAD 2>/dev/null)
info "本地 HEAD = ${LOCAL_HEAD:-<读取失败>}"
if [ "${LOCAL_HEAD:-}" = "$REMOTE_BRANCH_SHA" ]; then
  ok "本地 HEAD 与 origin/$BRANCH 一致"
else
  bad "本地 HEAD 与 origin/$BRANCH **不一致** —— 先把远端拉下来核对再集成"
  info "（这可能是因为 main 前进后本地未 fetch，或本地有未推送 commit）"
fi

hdr "4. 拓扑与冲突预判（对真实 sha 实测）"
if git cat-file -e "$REMOTE_MAIN_SHA^{commit}" 2>/dev/null; then
  AHEAD=$(git rev-list --count "$REMOTE_MAIN_SHA".."$REMOTE_BRANCH_SHA" 2>/dev/null)
  BEHIND=$(git rev-list --count "$REMOTE_BRANCH_SHA".."$REMOTE_MAIN_SHA" 2>/dev/null)
  info "ahead = $AHEAD ; behind = $BEHIND"

  if [ "$BEHIND" = "0" ]; then
    ok "fast-forward 可能"
  else
    info "非 fast-forward（behind=$BEHIND）—— 正常，继续看 merge-tree"
  fi

  MT=$(git merge-tree --write-tree --name-only "$REMOTE_BRANCH_SHA" "$REMOTE_MAIN_SHA" 2>&1)
  echo "$MT" | head -20 | sed 's/^/         /'
  if echo "$MT" | grep -qi 'conflict'; then
    bad "merge-tree 报告**冲突** —— 不要直接 merge，需按 AGENTS.md §14.7 语义化解决"
  else
    ok "merge-tree 无冲突段（只有 tree 哈希）"
  fi

  hdr "5. 双侧改动文件重叠检查"
  MB=$(git merge-base "$REMOTE_BRANCH_SHA" "$REMOTE_MAIN_SHA" 2>/dev/null)
  info "merge-base = $MB"
  ours=$(git diff --name-only "$MB" "$REMOTE_BRANCH_SHA" 2>/dev/null | sort)
  theirs=$(git diff --name-only "$MB" "$REMOTE_MAIN_SHA" 2>/dev/null | sort)
  overlap=$(comm -12 <(echo "$ours") <(echo "$theirs"))
  if [ -z "$overlap" ]; then
    ok "双侧改动**零重叠**"
  else
    bad "双侧有重叠文件（未必冲突，但需人工确认）："
    echo "$overlap" | sed 's/^/         /'
  fi
else
  bad "本地缺 $MAIN 的对象（$REMOTE_MAIN_SHA）—— 先 fetch"
  info "在 D:\\intelligence-agent-frontend 执行：git fetch origin $MAIN"
fi

hdr "6. 门禁复跑提示（本脚本不代跑，避免误判）"
cat <<'EOF'
         集成前请在 web/ 下复跑（先清产物，避免沙箱 safe-delete 拦截）：
           cd web && rm -rf test-results dist
           npx tsc --noEmit
           npx vitest run                      # 期望 416/416
           npx oxlint                          # 期望 0 error / 35 warning
           npx vitest run -c vitest.perf.config.ts   # 期望 12/12
           npx playwright test                 # 期望 58 passed
           npx vite build
EOF

hdr "结论"
echo "  通过 $pass 项，失败 $fail 项"
if [ "$fail" -eq 0 ]; then
  echo "  ✅ 预检通过 —— 可进入 merge 流程（merge / push 仍需用户批准）"
  exit 0
else
  echo "  ❌ 有 $fail 项未通过 —— 请先处理，不要盲目 merge"
  exit 1
fi
