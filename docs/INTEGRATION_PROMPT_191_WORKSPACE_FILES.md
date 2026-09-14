# 集成提示词：#191 会话工作区只读浏览 API（后端 `feat/backend`）

> 给集成 AI。这份是**纯后端**票：没有前端改动，合并后前端行为零变化（新 API 还没有消费方）。
> 但里面有一条**安全修复**值得看完第 3 节再合并。

---

## 1. 一句话

`GET /api/sessions/{id}/workspace/...` 新增四条**只读**路由——列工作区文件、读单个文件、
`git status`、单文件 `git diff`。这是 PRD（`WORKSPACE_PANEL_PRD.md` §3.3 / §6 票 8）里
「文件/改动」面之外的后续票：「文件/改动」回答"**这次 agent 改过哪些文件**"（会话真相，
来自事件流），本票补"**工作区现在有什么、某个文件是什么**"（文件系统真相）。两者刻意分开
（不变量 #22），本模块**不参与**"哪些文件是 agent 改的"的判断。

| 端 | worktree / 分支 | commit |
| --- | --- | --- |
| 后端 | `D:\intelligence-agent-backend` / `feat/backend` | `7f00377`（+ 本文件所在 docs commit） |

**未 push、未 merge**（§14.4 等批准）。前端无对应改动 ⇒ 合并顺序上无依赖，直接
`feat/backend` → `main` 即可。

---

## 2. 四条路由（可用 curl 直接验）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sessions/{id}/workspace/files?pattern=&limit=500` | 相对 POSIX 路径、排序、只列文件；`total`/`returned`/`truncated` 如实 |
| GET | `/api/sessions/{id}/workspace/file?path=&offset=1&limit=1000` | **行切片**（`lines[]` 与 artifact 切片同名同义）+ `next_offset` 续读指针；单行超长按 2000 字符截断并逐行标注 `truncated`/`full_length` |
| GET | `/api/sessions/{id}/workspace/git/status?pathspec=` | `git status --porcelain=v1` |
| GET | `/api/sessions/{id}/workspace/git/diff?path=&staged=` | `git diff [--staged] [path]` |

错误矩阵（**不冒 500**）：会话 id 形态非法 → 422；会话不存在 / 无 workspace 映射 → 404
（后者文案写明"没有 workspace 映射"，不冒充"文件不存在"）；路径越出 workspace → 403；
文件不存在 → 404 `文件不存在：<path>`；目录当文件读 → 422 `不是文件：<path>`（POSIX；
win32 上 `open()` 对目录抛 PermissionError → 403，两平台都不冒充成功）；非 UTF-8 文本 →
415；shell 元字符 / NUL → 422；不是 git 仓库 → **200** + 非零 `exit_code` + 如实 `stderr`
（ADR-0002，与工具层同款）。

**访问控制**：① 来源闸 `require_trusted_origin`（ADR-0028 D2，与项目/目录/记忆端点**同一份**）；
② 路径边界 `Sandbox.resolve_within_workspace`（ADR-0001 唯一强制点）；③ 会话归属由**该会话的
workspace 映射**解析。响应里只有相对路径。

---

## 3. 合并前请看一眼这条安全修复（P0）

**病**：git 的操作范围是**仓库**，不是 workspace。默认布局是
`<workspace_dir>/workspaces/<session_id>`——只要 `workspace_dir` 落在某个 git 仓库内
（开发机上几乎必然），工作区就**嵌**在那个仓库里。实测修复前：

| 命令 | 后果 |
| --- | --- |
| 裸 `git status --porcelain=v1` | 列出仓库里 **workspace 之外**的改动文件 |
| 裸 `git diff` | **直接吐出 workspace 之外文件的 diff 正文** |
| `git diff -- ../../secret.txt` | 同样穿透（`_SAFE_PATHSPEC` 允许 `.` 与 `/`） |

**修**（两件缺一不可）：① git 的 `path`/`pathspec` 先过 Sandbox 边界（越界 403——git 不会
替我们守 workspace 边界）；② 给命令一个**路径围栏**：没给 pathspec 时补 `.`，给了就以它为
准。**不能两个都加**：多个 pathspec 取并集，`-- . "a.py"` 会退化成整个子树（过滤器失效，
这个坑在实现时真踩到了）。

**证据**：`tests/web/test_workspace_files_api.py` 的 `test_git_commands_are_pinned_to_the_workspace_subtree`
与 `test_git_traversal_pathspec_is_refused` 用"工作区**真嵌进一个更大仓库**、外面真放一个
改过的文件"的布局断言；两条都做过**变异探针**（去掉围栏 → 3 条红；去掉边界校验 → 穿越用例红）。

**如实说明**：`git` 的 `stdout`/`stderr` 是原样透传的（ADR-0002 不许改写 git 输出），
所以 porcelain / diff 里的路径是**仓库相对**的，工作区嵌在仓库里时可能带上级目录名——
那是路径的**写法**，不是内容越界；内容越界已被上面两条挡住。

---

## 4. 合并后怎么验（真端点）

```bash
# 1) 建一个会话（前端或 curl），拿到 session_id
# 2) 列文件
curl -s "http://127.0.0.1:8000/api/sessions/<sid>/workspace/files" | python -m json.tool
# 3) 读文件（注意 lines[] + next_offset）
curl -s "http://127.0.0.1:8000/api/sessions/<sid>/workspace/file?path=README.md" | python -m json.tool
# 4) git
curl -s "http://127.0.0.1:8000/api/sessions/<sid>/workspace/git/status" | python -m json.tool
curl -s "http://127.0.0.1:8000/api/sessions/<sid>/workspace/git/diff" | python -m json.tool
# 5) 边界（应 403，且响应里没有 <workspace_dir> 的绝对路径）
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8000/api/sessions/<sid>/workspace/file?path=../../etc/hosts"
```

**注意**：`limit` / `offset` 有服务端上限（`le=`），给超大值会得到 **422**（FastAPI 参数
校验的形状是 list，不是一句中文 detail——这两条路由的参数校验与目录浏览那条的取舍不同，
前端消费时要按状态码判断，不要去解析 detail 的形状）。

---

## 5. 前后端边界（别误会成"面板能用了"）

本票**没有任何前端改动**，`workspace-modes` / `x-output-panel` 等 e2e 与它无关。合并后：

- 前端**看不到**任何新东西——四条路由没有消费方（浏览工作区文件的 UI 是另一张票）；
- 因此**不要**因为"面板还是只有三个面"而认为本票没落地：判据是上面第 4 节的 curl。

---

## 6. 门禁证据

| 端 | 命令 | 结果 |
| --- | --- | --- |
| 后端 | `ruff check .` | 全绿 |
| 后端 | `pytest`（全量） | **2239 passed / 10 skipped / 42 deselected / 0 failed**（356.93s） |
| 后端 | 新增用例 | `tests/web/test_workspace_files_api.py` **32 passed** |

**串行提醒**：后端全量 pytest 与前端 e2e **不要并发跑**（既有资源竞争型抖动）。

---

## 7. 如实登记的已知限制（都写在模块 docstring 里，属另一张票）

1. **读文件是全量读入再切片**（与 artifact 的 `inspect` 同一取舍）：超大文件会给服务端
   带来真实内存/时间成本。要按字节有界读，得给 Sandbox ABC 加参数（本票刻意没动 ABC 的
   行为，只把它已有的边界方法公开）。
2. **`files` 不是流式列举**：`Sandbox.list_files` 的契约是"返回全部匹配"，截断发生在
   web 层，所以一次请求会走完整棵工作区树——超大工作区上会慢。
3. **只认 UTF-8**：其它编码（GBK 等）如实 415，不猜编码。
4. **`WorkspaceRegistry.get` 会 `ensure_started()`**：对没在跑的会话，一次 GET 可能把它的
   sandbox 拉起来（docker 后端 = 起容器）。这是"后端无关地读工作区"的代价，也是 resume
   本来就要做的事；不额外发明"半启动"状态。
