"""会话工作区的**只读**浏览面（#191 / `WORKSPACE_PANEL_PRD.md` §3.3 + §6 票 8）。

PRD 的「文件/改动」面（#189）回答的是"**这次 agent 改过哪些文件**"——那份数据来自事件流
（工具结果的 `before`/`after` + `changed_files`），是**会话真相**。本模块补的是另一个问题：
"**这个工作区里现在有什么、某个文件的内容是什么**"——那是**文件系统真相**。

两者刻意分开，不是重复（不变量 #22：UI 不得维护第二套不可对账的业务真相）：
本模块**不**参与"哪些文件是 agent 改的"的判断，它只如实反映工作区当前的样子。
前端若要标"这是本会话改过的文件"，那份标记只能来自事件投影，不能拿这里的内容反推。

四条路由（全部只读、全部挂在会话下）
------------------------------------

| 方法 | 路径 | 做什么 |
| --- | --- | --- |
| GET | `/api/sessions/{id}/workspace/files` | 列工作区文件（glob 过滤 + 上限 + 如实截断） |
| GET | `/api/sessions/{id}/workspace/file` | 读一个文件的**行切片**（可从第 N 行续读） |
| GET | `/api/sessions/{id}/workspace/git/status` | `git status --porcelain=v1` |
| GET | `/api/sessions/{id}/workspace/git/diff` | `git diff [--staged] [path]` |

## 访问控制（本票的主要风险面，AGENTS.md §4.3）

三道闸，一道都不新造：

1. **来源闸**：`require_trusted_origin`（ADR-0028 D2）——与项目 / 目录列举 / 记忆端点
   **同一份实现**。宿主侧读写能力只接受本机来源（配了 JWT 则由认证层接管）。
2. **路径边界**：一律经 **Sandbox**（`Sandbox.resolve_within_workspace`，ADR-0001 的
   唯一强制点）。`read_text` / `list_files` 自己就会拒绝越界；两条 **git** 路由的
   `path` / `pathspec` 由本模块显式过一遍同一函数（见下），再把命令**围在 workspace
   子树内**。本模块**不写第二套路径校验**：两份校验就是两个漂移面，而实现里只要有一处
   忘了调，边界就没了。越界表现为 `PermissionError` → 403（与目录浏览同一句策展文案）。
3. **会话归属**：路由挂在 `/api/sessions/{session_id}/workspace/...` 下，workspace 由
   **该会话的映射**解析（`WorkspaceRegistry.get`），不接客户端给的任意根目录。

### git 路由为什么要额外做两件事（#191 code-review 的 P0）

git 的操作范围是**仓库**，不是 workspace——而仓库可能比 workspace 大：默认布局是
`<workspace_dir>/workspaces/<session_id>`，只要 `workspace_dir` 落在某个仓库内（开发机上
几乎必然如此），工作区就"嵌"在那个仓库里。实测（修复前）：

| 命令 | 后果 |
| --- | --- |
| `git status --porcelain=v1`（无 pathspec） | 列出仓库里 **workspace 之外**的改动文件 |
| `git diff`（无 path） | 直接吐出 workspace **之外**文件的 diff 正文 |
| `git diff -- ../../secret.txt` | 同上——`_SAFE_PATHSPEC` 允许 `.` 与 `/`，挡不住穿越 |

所以两条 git 路由做两件事，缺一不可：

1. **pathspec 先过 Sandbox 边界**（`resolve_within_workspace`）：越界 → 403，而不是交给
   git 去解释（git 的范围是仓库，它不会替我们守 workspace 边界）；
2. **给命令一个路径围栏**（`_scope_for`）：**没给** pathspec 时补 `.`（cwd 就是 workspace，
   于是"不带 pathspec"的调用也读不到外面）；**给了** pathspec 就以它为准——它已经过第 1 步
   的边界校验，本身就是围栏。

两条都不可省：只做第 2 条挡不住穿越（见上表第三行）；而第 2 条里"围栏与过滤各给一个
pathspec"也不行——多个 pathspec 取**并集**，`-- . "a.py"` 会退化成整个子树（过滤器失效）。

**响应不含宿主绝对路径**：`files` / `lines` 里只有相对 POSIX 路径；越界拒绝的文案只用
调用方给的那个相对路径（`os_error_detail(path=...)` 优先用它，而不是异常自带的绝对路径）。
**例外如实说明**：git 的 `stdout` / `stderr` 是**原样透传**的——`git diff` 的 `a/`、`b/`
前缀是**仓库相对**路径，工作区嵌在仓库里时可能带上级目录名（如 `workspaces/<sid>/x`），
`git status` 的 porcelain 路径同样相对仓库根。那是 git 自己的输出契约，改写它就是伪造
（ADR-0002 要求如实带回）。**内容**不会越界（第 1、2 条挡着），越界的只是路径的**写法**。

## 为什么经 Sandbox 而不是直接读宿主文件系统

`Sandbox.workspace_root` 对 `docker` 后端是**容器内**路径（`/workspace`），宿主上根本
不存在；只有 `read_text` / `list_files` / `exec` 这层抽象在两个后端上都是对的
（host 目录 / 容器内各自实现）。所以本模块不碰 `os`，只调 Sandbox——顺带白拿了
local 的 `newline=""` 字节透传（CRLF 不被折叠）与 docker 的容器内读取。

代价如实说明：`WorkspaceRegistry.get` 对没在跑的会话会**重建并 `ensure_started()`**
（docker 后端 = 起容器），所以一次 GET 可能把会话的 sandbox 拉起来。这是"后端无关地读
工作区"的代价，也是 resume 本来就要做的事（07 §9 的恢复顺序）；不额外发明"半启动"状态。

## 已知不做（如实划界）

- **不写**：没有写文件 / 删文件 / 暂存的入口（票面只要求只读）。git 只跑 `status`/`diff`
  两种读查询，命令由 `tools/git.py` 的 `git_status_command` / `git_diff_command` 构造
  ——白名单（挡 shell 元字符）也只有那一份。
- **不做内容搜索**：没有 grep/glob 检索面（工作区全量枚举由 `files` 的 `pattern` 过滤覆盖）。
- **不做大文件的分块续传**：`file` 是行切片 + 续读指针；超大文件会被完整读进内存再切片
  （与 artifact 的 `inspect` 同一取舍——那条路径也是 `load()` 全量后再切）。要按字节
  有界读，得给 Sandbox ABC 加参数，属另一张票的范围。
- **列表开销与工作区大小成正比**：`Sandbox.list_files` 的契约是"返回**全部**匹配"，
  截断发生在本模块（`MAX_FILE_ENTRIES`）。所以 `files` 不是流式列举，一次请求会走完整棵
  工作区树——超大工作区上这一次调用会慢，这是 `list_files` 的既有形状，不在这里改。
- **只认 UTF-8**：`Sandbox.read_text` 是 UTF-8 契约（二进制 → 415）。GBK 等其它编码的文件
  会被如实拒绝，而不是猜一个编码出来。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import anyio
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel

from agent_harness.session.errors import InvalidSessionId, SessionNotFound
from agent_harness.session.service import SessionService
from agent_harness.storage.artifact import slice_lines
from agent_harness.tools.git import (
    git_diff_command,
    git_status_command,
    run_git_command,
)
from agent_harness.web.artifacts import MAX_CHARS_PER_LINE_CAP, MAX_LINES_CAP
from agent_harness.web.domain_errors import http_error, workspace_http_error
from agent_harness.web.projects import require_trusted_origin

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agent_harness.sandbox import Sandbox
    from agent_harness.web.app import AppState

#: 列文件的条目上限。与 `host_dirs.MAX_ENTRIES` 同量级，但**各自独立**：那条路径列的是
#: 宿主目录（一次点击换一层列举），这条列的是一个工作区里匹配 pattern 的全部文件——
#: 两个资源、两种浏览语义，共用一个常量只会让"改一个动两个"。
MAX_FILE_ENTRIES = 500

#: 读文件的行预算与单行上限：**刻意引用既有那两份常量**，而不是各写一个字面量（两句注释说
#: "同口径"是保证不了多久的）。两处承诺的是同一件事——"一次读回来的文本量既有用又撑不爆
#: 响应体"——所以上限也该是同一个来源（`web/artifacts.py` 的读数端上限）。
#: `MAX_FILE_ENTRIES` 不在此列：它管的是**目录条目数**（另一个资源、另一种浏览语义）。
MAX_FILE_LINES = MAX_LINES_CAP
MAX_CHARS_PER_LINE = MAX_CHARS_PER_LINE_CAP


class WorkspaceFileList(BaseModel):
    """工作区文件清单（路径全部是相对 workspace 的 POSIX 形式）。"""

    files: list[str]
    #: 匹配总数（**不受** `limit` 影响）：客户端据此知道"还有多少没看到"。
    total: int
    returned: int
    truncated: bool


class WorkspaceFileSlice(BaseModel):
    """一个文件的行切片（字段与 `ArtifactSlice` 同名同义，便于前端复用同一套渲染）。

    与 `ArtifactSlice` 的两处差别，都是**刻意**的：
    - 身份字段是 `path` 而不是 `artifact_id`（这里读的是工作区文件，不是外置产物）；
    - 多一个 `next_offset`：截断时给出**可执行的续读指针**。artifact 那边靠 `line_number`
      自行推算，文件阅读器不该让调用方自己算。
    """

    path: str
    lines: list[dict[str, int | str | bool]]
    total_lines: int
    returned_lines: int
    truncated: bool
    #: 续读指针（`None` = 已读完）。截断时等于"下一个尚未返回的行号"。
    next_offset: int | None
    #: 服务端实际生效的查询参数（客户端给的值会被夹进上限，回显让调用方可复现）。
    query: dict[str, int | None]


class GitCommandResult(BaseModel):
    """一条只读 git 命令的原样结果（ADR-0002：exit_code 非零**不是** HTTP 错误）。"""

    exit_code: int
    stdout: str
    stderr: str


async def _session_sandbox(
    state: AppState, session_id: str, validate_session_id: Callable[[str], str]
) -> Sandbox:
    """会话 → 它的 workspace sandbox（三件事：会话形态合法、会话存在、映射存在）。

    `validate_session_id` 由调用方传入（app 侧那一份）：形态校验只有一处实现，这里
    只负责把它的 `InvalidSessionId` 翻成 422——漏了这一步就会以 500 冒出去（与既有
    artifact 路由同一写法）。

    `WorkspaceRegistry.get` 是同步且可能落盘的（读映射 JSON + `ensure_started`），
    所以卸载到 worker 线程；`KeyError`（没有映射）在事件循环侧翻成 404。
    """
    try:
        validate_session_id(session_id)
    except InvalidSessionId as error:
        raise http_error(error) from error
    if not await SessionService(state).has_session(session_id):
        raise http_error(SessionNotFound(f"session '{session_id}' not found"))
    try:
        return await anyio.to_thread.run_sync(state.workspace_registry.get, session_id)
    except KeyError as error:
        # 会话在、映射不在（映射被清 / 会话由别的机制建、或本部署没建过 workspace）。
        # 如实说"没有 workspace 映射"，不冒充"文件不存在"——两件事的修法完全不同。
        raise HTTPException(
            status_code=404,
            detail=(
                f"会话 '{session_id}' 没有 workspace 映射：无法浏览工作区"
                "（映射尚未创建或已被删除）。"
            ),
        ) from error


def _list_files(sandbox: Sandbox, pattern: str, limit: int) -> WorkspaceFileList:
    """同步列举 + 截断（由 handler 卸载到 worker 线程）。

    `total` 是匹配总数、`truncated` 是"有没被 limit 截掉"——两者都来自同一份匹配结果，
    不存在"报 500 条其实有 300 条"的可能。
    """
    matched = sandbox.list_files(pattern)
    return WorkspaceFileList(
        files=matched[:limit],
        total=len(matched),
        returned=min(len(matched), limit),
        truncated=len(matched) > limit,
    )


def _read_slice(sandbox: Sandbox, path: str, offset: int, limit: int) -> WorkspaceFileSlice:
    """同步读 + 切片（由 handler 卸载到 worker 线程）。

    编码只认 UTF-8（`Sandbox.read_text` 的契约）：解不开就是**调用方该知道的事实**，
    由 handler 翻成 415，不在这里兜底成乱码。
    """
    content = sandbox.read_text(path)
    all_lines = content.splitlines()
    lines, truncated = slice_lines(
        all_lines,
        start_line=offset,
        end_line=None,
        keyword=None,
        max_lines=limit,
        max_chars_per_line=MAX_CHARS_PER_LINE,
    )
    # 续读指针 = "下一个**尚未返回**的行号"：按最后一条返回行的下一行算，且**必须**还有
    # 未返回的行（`last < len(all_lines)`）。只在字符上限截断末行时也置 truncated，那时
    # 行号已经用完——指针要 null，否则调用方会去读一个不存在的行（`offset=total+1`）。
    last_line = int(lines[-1]["line_number"]) if lines else None
    next_offset = (
        last_line + 1
        if truncated and last_line is not None and last_line < len(all_lines)
        else None
    )
    return WorkspaceFileSlice(
        path=path,
        lines=lines,
        total_lines=len(all_lines),
        returned_lines=len(lines),
        truncated=truncated,
        next_offset=next_offset,
        query={"offset": offset, "limit": limit},
    )


def _scope_for(checked_pathspec: str) -> str:
    """git 命令的路径围栏：**没有** pathspec 时用 `.`，有就以调用方那个为准。

    不能"两个都加"：git 的多个 pathspec 是**并集**，`-- . "a.py"` 等于整个子树
    （实测：过滤器失效，`b.txt` 会一起冒出来）。所以围栏与过滤这两个角色由**同一个**
    pathspec 承担——给的 pathspec 已经过边界校验、必在 workspace 内，它自己就是围栏。
    """
    return "" if checked_pathspec else "."


def _boundary_checked(sandbox: Sandbox, value: str) -> str:
    """给 git 命令用的路径：**过一遍 Sandbox 边界**后原样返回（空串直接放行）。

    只校验不读（`resolve_within_workspace` 的返回值这里不要）：git 的命令范围是**仓库**，
    它不会替我们守 workspace 边界，所以穿越型 pathspec（`..`、指向外面的绝对路径）必须先
    在这里被挡掉——否则它会与围栏 pathspec 取**并集**，把外面重新拉进输出。
    越界 → `PermissionError` → 403；含 NUL → `ValueError`（`Path.resolve()` 抛）→ 422。
    """
    if not value:
        return ""
    sandbox.resolve_within_workspace(value)
    return value


def register_workspace_file_routes(
    app: FastAPI, *, validate_session_id: Callable[[str], str]
) -> None:
    """把工作区只读路由挂到既有 app（`create_app` 里一行调用的接入面）。

    `validate_session_id` 从 app 侧传入（与 `register_lineage_routes` 同款）：会话 id 的
    形态校验只有 app 侧那一份，本模块不复制。
    """

    async def _sandbox_for(session_id: str) -> Sandbox:
        """本模块四条路由统一的会话解析入口（形态 / 存在性 / 映射三件事只写一遍）。"""
        return await _session_sandbox(app.state.agent, session_id, validate_session_id)

    @app.get("/api/sessions/{session_id}/workspace/files")
    async def list_workspace_files(
        session_id: str,
        pattern: str = Query(
            default="",
            description="glob 过滤（对相对路径整体或文件名匹配，`**` 递归；空 = 全部）",
        ),
        limit: int = Query(default=MAX_FILE_ENTRIES, ge=1, le=MAX_FILE_ENTRIES),
        _: None = Depends(require_trusted_origin),
    ) -> WorkspaceFileList:
        """列工作区文件（只读；目录不列，只列文件）。

        错误矩阵：会话 id 形态非法 → 422 / 会话不存在或没有 workspace 映射 → 404。
        列举本身不因越界而失败——`pattern` 只是过滤器，走不出 workspace（`list_files`
        从 workspace_root 往下走）。
        """
        sandbox = await _sandbox_for(session_id)
        return await anyio.to_thread.run_sync(_list_files, sandbox, pattern, limit)

    @app.get("/api/sessions/{session_id}/workspace/file")
    async def read_workspace_file(
        session_id: str,
        path: str = Query(description="workspace 内的文件路径（相对或绝对，必须落在 workspace 内）"),
        offset: int = Query(default=1, ge=1, description="起始行号（1-based）"),
        limit: int = Query(default=MAX_FILE_LINES, ge=1, le=MAX_FILE_LINES),
        _: None = Depends(require_trusted_origin),
    ) -> WorkspaceFileSlice:
        """读一个文件的行切片（只读；可从 `next_offset` 续读）。

        错误矩阵（与目录浏览同一套策展文案，不冒 500）：越出 workspace → 403
        `无权限访问：<path>` / 不存在 → 404 `文件不存在：<path>` / 是目录 → 422
        `不是文件：<path>`（POSIX；win32 的 `open()` 对目录抛 PermissionError → 403，
        两个平台都不冒充成功）/ 非 UTF-8 文本 → 415。
        """
        sandbox = await _sandbox_for(session_id)
        try:
            return await anyio.to_thread.run_sync(_read_slice, sandbox, path, offset, limit)
        except UnicodeDecodeError as error:
            # 二进制文件：如实说"不是文本"，不猜编码、不吐乱码。415（不支持的媒体类型）
            # 比 422（请求参数错）更准——路径没问题，是这份内容的形态本接口不支持。
            raise HTTPException(
                status_code=415,
                detail=(
                    f"不是 UTF-8 文本文件，本接口只读文本：{path}"
                    "（二进制内容请用产物读取接口或下载）"
                ),
            ) from error
        except OSError as error:
            # `noun="文件"`：同一个 errno 在目录浏览里说"目录不存在"，在这里必须说"文件"
            # ——同一份策展实现，只换名词（见 `os_error_detail`）。
            raise workspace_http_error(error, path=path, noun="文件") from error
        except ValueError as error:
            # 含 NUL 的路径：`Path.resolve()` 抛 ValueError（**不是** OSError），会穿透成 500。
            # `host_dirs` 对同一形态有同样的守卫（那边注释写着"POSIX 的 realpath 遇 NUL 抛
            # ValueError → 会穿透成 500"），这里沿用同款 422 + 同款文案。
            # 注意顺序：`UnicodeDecodeError` 是 `ValueError` 的子类，必须先被上面那条捕获
            # （415 才是它该有的答案），所以这一条放在最后。
            raise HTTPException(
                status_code=422, detail=f"路径含非法字符：{path!r}"
            ) from error

    @app.get("/api/sessions/{session_id}/workspace/git/status")
    async def workspace_git_status(
        session_id: str,
        pathspec: str = Query(default="", description="可选路径过滤（纯路径，不支持通配符）"),
        _: None = Depends(require_trusted_origin),
    ) -> GitCommandResult:
        """`git status --porcelain=v1`（只读）。

        不是 git 仓库 → **200** + 非零 `exit_code` + 如实 `stderr`（ADR-0002 的语义，
        与 `git_status` 工具逐字同一套：命令跑过了，git 说不）。

        边界：`pathspec` 先过 Sandbox（越界 → 403，不只是"git 报错"），命令再带 `"."`
        围栏——没有这两步，工作区嵌在更大仓库里时会列出仓库内、workspace **之外**的文件。
        """
        sandbox = await _sandbox_for(session_id)
        try:
            checked = await anyio.to_thread.run_sync(_boundary_checked, sandbox, pathspec)
            command = git_status_command(checked, scope=_scope_for(checked))
        except PermissionError as error:
            raise workspace_http_error(error, path=pathspec) from error
        except ValueError as error:
            # 白名单拒绝（shell 元字符等）：策略与文案都来自工具层那一份。
            raise HTTPException(status_code=422, detail=str(error)) from error
        result = await run_git_command(sandbox, command)
        return GitCommandResult(
            exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr
        )

    @app.get("/api/sessions/{session_id}/workspace/git/diff")
    async def workspace_git_diff(
        session_id: str,
        path: str = Query(default="", description="可选路径过滤（纯路径，不支持通配符）"),
        staged: bool = Query(default=False, description="True 时看暂存区差异（git diff --staged）"),
        _: None = Depends(require_trusted_origin),
    ) -> GitCommandResult:
        """`git diff [--staged] [path]`（只读；单文件 diff 就是传 `path`）。

        边界同 `git/status`：`path` 先过 Sandbox 边界，命令再带 `"."` 围栏。
        **这条是 P0 修复的主战场**：修复前不带 `path` 的 `git diff` 会把 workspace 之外
        的文件 diff 正文直接吐出来（工作区嵌在仓库内时）。
        """
        sandbox = await _sandbox_for(session_id)
        try:
            checked = await anyio.to_thread.run_sync(_boundary_checked, sandbox, path)
            command = git_diff_command(staged=staged, path=checked, scope=_scope_for(checked))
        except PermissionError as error:
            raise workspace_http_error(error, path=path) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        result = await run_git_command(sandbox, command)
        return GitCommandResult(
            exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr
        )


__all__ = [
    "MAX_CHARS_PER_LINE",
    "MAX_FILE_ENTRIES",
    "MAX_FILE_LINES",
    "GitCommandResult",
    "WorkspaceFileList",
    "WorkspaceFileSlice",
    "register_workspace_file_routes",
]
