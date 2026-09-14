"""领域异常 → HTTP 的翻译层（ARCH-5，#144）。

`SessionService` 正确地不知道 HTTP（不变量：领域层不依赖传输层）。但 web 层此前把
「领域异常 → status + detail」这段映射在 **11 个 handler** 里各重述一遍（app.py 10 +
lineage.py 1，共 **37 个 except 臂**）——同一个异常在不同 handler 给出不同状态码不会被
任何检查发现，新增一个领域异常要改每一处。本模块是这段翻译的**唯一 home**。

## 审计结论（逐 handler，ARCH-5 施工前核对，状态码与改动前逐字一致）

| 端点 | 翻译的领域异常 |
| --- | --- |
| `GET /api/sessions/{id}/events` | InvalidSessionId, SessionNotFound |
| `POST /api/sessions` | WorkspaceNameInvalid（含子类 WorkspacePathInvalid）, InvalidDecision |
| `GET /api/sessions/{id}/stream` | InvalidSessionId, SessionNotFound |
| `POST /api/sessions/{id}/resume` | InvalidSessionId, SessionNotFound, ActiveRunConflict, RecoveryConflict, SeqConflict |
| `POST /api/sessions/{id}/cancel` | InvalidSessionId, SessionNotFound |
| `POST /api/sessions/{id}/approve` | InvalidSessionId, SessionNotFound, ApprovalQueueMissing, ApprovalRequestMissing, InvalidDecision, ApprovalAlreadyResolved |
| `POST /api/sessions/{id}/recover` | InvalidSessionId, SessionNotFound, RecoveryConflict, SeqConflict |
| `POST /api/sessions/{id}/model` | InvalidSessionId, SessionNotFound, UnknownModel, SeqConflict |
| `POST /api/sessions/{id}/messages` | InvalidSessionId, SessionNotFound, ActiveRunConflict, RecoveryConflict, QueueItemNotFound, SteerTargetNotFound, SeqConflict |
| `POST /api/sessions/{id}/queue/{qid}/cancel` | InvalidSessionId, SessionNotFound, QueueItemNotFound, SeqConflict |
| `POST /api/sessions/{id}/forks`（lineage.py） | InvalidSessionId, SessionNotFound, ActiveRunConflict, InvalidForkBoundary |
| `GET /api/sessions`（WS-3 / #153 追加） | WorkspaceNotFound |
| `DELETE /api/sessions/{id}`（会话硬删 / #172 追加） | InvalidSessionId, SessionNotFound, ActiveRunConflict, SessionHasChildren |
| `POST /api/sessions/{id}/archive`（会话归档 / #171 追加） | InvalidSessionId, SessionNotFound, ActiveRunConflict |
| `DELETE /api/sessions/{id}/archive`（取消归档 / #171 追加） | InvalidSessionId, SessionNotFound |

审计发现：**每个异常在所有 handler 里状态码一致**（这正是可单源化的前提）。
两个特例写进契约、不得「顺手统一」：

- `approve` 的 **404 有三个不可区分来源**（SessionNotFound / ApprovalQueueMissing /
  ApprovalRequestMissing 都是 404）——OBS-015 的结论，客户端无法从状态码区分，属有意为之；
- `ApprovalAlreadyResolved` 是 **409（幂等已决）而非 404**——与上面三个 404 分开，
  因此「审批已决」是可区分的。

**WS-3 追加（#153）**：`GET /api/sessions` 开始翻译 `WorkspaceNotFound`——
`?workspace_id=<未注册 id>` 返回 **404**，而不是空列表（空列表会把"项目不存在"
伪装成"项目没有会话"）。上表已补该端点行，`_DOMAIN_ERROR_STATUS` 的 404 组同步
新增 `WorkspaceNotFound`。

**WS-4 追加（#154）**：新增 `/api/projects` 系列端点（`web/projects.py`），共 9 条：
`POST /api/projects`（注册已存在目录，幂等）、`GET /api/projects`（注册表序）、
`POST /api/projects/resolve`（按路径解析，不注册）、`GET|PATCH|DELETE
/api/projects/{id}`（软删除）、`POST /api/projects/{id}/sessions`（attach）、
`DELETE /api/projects/{id}/sessions/{sid}`（detach，幂等）、
`POST /api/projects/{id}/sessions/{sid}/order`（账本内重排）。
这些端点同时翻译**两张表**：会话层词汇走 `http_error`（`WorkspaceNotFound` 404 /
`WorkspaceMoveInvalid` 409 / `InvalidSessionId` 422 / `SessionNotFound` 404），
`workspace` 包与 OS 词汇走下面的 `workspace_http_error`。

**BUG-011 追加**：`SeqConflict` → **409**（seq 冲突：并发写者抢先落盘，或日志已损坏）。
旧行为是 `service.resume_and_launch` 把 `ValueError` 一刀切翻成 `SessionNotFound`（404），
使真机会话 `dd983104` 的日志损坏被显示成 `续聊失败：Send failed: 404`。上表中 5 个
「会构造/追加 Session 聚合」的端点各自声明了它；上方的 37 个 except 臂是 ARCH-5 当时的
历史审计记录，不在本次补记范围内。

**WS-6 追加（#169）**：新增 `WorkspacePathInvalid: 422`——`POST /api/sessions` 的 `cwd`
形态/存在性非法（非绝对 / 不存在 / 不是目录）。它**继承** `WorkspaceNameInvalid`，所以
handler 的 `except` 元组一行不用改；但本表是**精确类型**索引（`http_error` 直接查表、
不回退到父类），子类必须在这里自己登记，否则命中时 KeyError。

**会话硬删追加（#172 / ADR-0029）**：新增 `SessionHasChildren: 409`——会话是别的会话的
fork 父时不删（不级联、不静默 orphan），detail 带子会话数量。它既不是 422（请求形态没
错）也不是 404（父明明存在），所以只有 409 诚实。上表已补该端点行；该端点的 `404`
与 `409 ActiveRunConflict` 都是既有条目，复用不新增。

## 设计取舍（为什么不再往前一步）

- **不用 FastAPI 全局 `exception_handler`**：那会把整张表应用到每个端点，使一个本来
  只会 500 的意外异常突然变成 404/422。issue 边界明确禁止「引入该端点本来不产生的
  状态码」——每个端点仍用**自己的 except 元组**声明「本端点翻译哪些」，子集语义不变。
- **不用装饰器**：app.py 与 lineage.py 都启用了 `from __future__ import annotations`，
  注解是字符串；包装函数定义在别的模块会改变 `__globals__`，FastAPI 的
  `get_type_hints` 解析 `ForkRequest` / `ResumeRequest` 这类本模块名会 NameError。
  而定义在本模块又无法同时服务两个模块（app → lineage 有导入顺序约束）。收益不抵风险。
"""

from __future__ import annotations

from fastapi import HTTPException

from agent_harness.memory.errors import MemoryNotFound
from agent_harness.session.errors import (
    ActiveRunConflict,
    ApprovalAlreadyResolved,
    ApprovalQueueMissing,
    ApprovalRequestMissing,
    InvalidDecision,
    InvalidForkBoundary,
    InvalidSessionId,
    QueueItemNotFound,
    RecoveryConflict,
    SeqConflict,
    SessionHasChildren,
    SessionNotFound,
    SessionServiceError,
    SteerTargetNotFound,
    UnknownModel,
    WorkspaceMoveInvalid,
    WorkspaceNameInvalid,
    WorkspaceNotFound,
    WorkspacePathInvalid,
)
from agent_harness.workspace import UnknownLedgerEntry, UnknownWorkspace

#: 领域异常 → HTTP status 的**唯一**映射源（ARCH-5）。新增领域异常只改这里；
#: 需要用它的端点再在自己的 except 元组里声明。状态码口径见模块 docstring 的审计表。
#: 覆盖全部 `SessionServiceError` 子类——由
#: `tests/web/test_domain_error_mapping.py` 双向钉住（漏登记先红、值漂移先红）。
_DOMAIN_ERROR_STATUS: dict[type[SessionServiceError], int] = {
    # 422：入参/引用非法（客户端 bug，不是冲突）
    InvalidSessionId: 422,
    WorkspaceNameInvalid: 422,
    WorkspacePathInvalid: 422,
    InvalidDecision: 422,
    UnknownModel: 422,
    InvalidForkBoundary: 422,
    # 404：目标不存在（approve 的三个来源有意不可区分，见模块 docstring）
    SessionNotFound: 404,
    ApprovalQueueMissing: 404,
    ApprovalRequestMissing: 404,
    QueueItemNotFound: 404,
    WorkspaceNotFound: 404,
    # 409：状态冲突（含幂等已决、需人工裁决的崩溃遗留、seq 冲突）
    ActiveRunConflict: 409,
    RecoveryConflict: 409,
    ApprovalAlreadyResolved: 409,
    SteerTargetNotFound: 409,
    # #172 / ADR-0029：会话是 fork 父——删它会连带处置用户没选中的子会话（级联），
    # 或留一个悬空来源链接（orphan），两者都不接受，所以是"状态不允许"而非入参非法。
    SessionHasChildren: 409,
    # WS-4 / #154：会话↔项目的移动在当前状态下不成立（无 cwd 锚 / cwd 不属于该项目 /
    # 重排目标不在该项目账本里）。是"请求合法但状态不允许"，与 422 的名字形态非法分开。
    WorkspaceMoveInvalid: 409,
    # BUG-011：seq 冲突是「资源当前状态与请求冲突」，**不是**「资源不存在」——
    # 旧行为把它翻成 404（`send_message` 的 `Send failed: 404`），掩盖了日志损坏。
    SeqConflict: 409,
}

#: workspace 包 / 文件系统异常 → HTTP status 的第二张表（WS-4 / #154）。
#:
#: 为什么单独一张：`_DOMAIN_ERROR_STATUS` 的键必须是 `SessionServiceError` 子类，而
#: `UnknownWorkspace` / `UnknownLedgerEntry` 是 `workspace` 包的词汇（该包不依赖
#: session 层，不能反向继承）。这张表兜住**直接**从索引冒出来的那些异常 +
#: `create()` 有意原样透传的 OS 错误。
#:
#: **刻意不登记**：`WorkspaceRegistryCorrupt`（RuntimeError）——索引损坏是服务端完整性
#: 故障，500 才是诚实状态码，不是客户端的错。
#:
#: `UnknownWorkspace` 的**当下可达性**：本表要求每个 `WorkspaceError` 子类都有状态码
#: （覆盖测试双向钉住），但当前 HTTP 路径不会触达它——索引的读方法返回 `None`
#: （`ProjectService` 翻成 `WorkspaceNotFound`），写方法抛 `UnknownLedgerEntry`。它的
#: 价值是**注册表完备性**：将来某个索引调用点直接冒出该异常时是 404，不是 500。
_WORKSPACE_ERROR_STATUS: dict[type[Exception], int] = {
    # 404：目标不存在
    UnknownWorkspace: 404,
    FileNotFoundError: 404,
    # 409：账本序请求与账本当前状态冲突（会话/锚点不在该项目账本里）
    UnknownLedgerEntry: 409,
    # 422：路径存在但不是目录（`require_existing_directory` 的原样透传）——入参非法
    NotADirectoryError: 422,
    # 422：**路径是目录，但调用方要的是文件**（#191 读工作区文件：`open(dir)` 在 POSIX
    # 抛这个）。与上一条互为镜像；不登记它的后果是 `workspace_http_error` 精确查表
    # KeyError → 客户端可控的路径换来 500，而 win32 上同一动作抛 PermissionError（403）
    # ——同一件事两个平台两种答案，至少两边都不是 500。
    IsADirectoryError: 422,
    # 422：**裸 `OSError`**——非法字符 / 超长路径等（`os.stat` 抛 EINVAL / ENAMETOOLONG，
    # 实测 `C:\bad<name>` 与 `"\t"` 都是这一类）。客户端可控的路径换来 500 不诚实；
    # 这类 errno 就是"你给的路径不合法"。注意 `workspace_http_error` 按 `type(exc)` 精确
    # 查表，所以这条不会吞掉上面 FileNotFoundError / NotADirectoryError 的专有项。
    OSError: 422,
    # 403：路径存在但服务端无权访问（文件系统权限，不是"参数写错"）。
    # 目录浏览场景下这条**不降级成空列表**——"看不见"与"这里没有子目录"必须可区分。
    PermissionError: 403,
}


def os_error_detail(
    exc: Exception, *, path: str | None = None, noun: str = "目录"
) -> str:
    """文件系统异常 → **策展中文** detail（与 `GET /api/host/dirs` 同一套文案）。

    为什么不再 `str(exc)`：同一个路径在"注册项目"与"目录浏览"两处会被用户看到——
    `str(OSError)` 是 `[Errno 20] 不是目录: 'D:\\x\\readme.txt'`（带 errno、反斜杠双重
    转义），而目录浏览器给的是 `不是目录：D:\\x\\readme.txt`。同一事实两种说法，
    用户会以为遇到了两种问题（API-01，2026-09-13 真机验收）。

    路径取舍：调用方给的 `path`（已规范化的 canonical）优先，否则取
    `OSError.filename`——`os.stat` / `realpath` 抛出的 OSError 都带它，
    `pydantic` / 手写的异常则可能没有；都没有时**退回 `str(exc)`**，
    宁可文案粗糙也不丢信息。

    `noun` 只影响 `FileNotFoundError` 那一句（默认"目录"，因为绝大多数调用方在找目录）：
    #191 读工作区**文件**时,"目录不存在：README.md"是错的，所以调用方传 `noun="文件"`。
    参数化而不是另写一句文案——同一张表、同一个函数，"一个 errno 一种说法"这条不破。

    **只策展 `OSError`**：`workspace_http_error` 也接 `WorkspaceError`（`UnknownWorkspace`
    / `UnknownLedgerEntry`），那些异常自带完整中文消息且**未必与路径有关**——给它们套
    "路径不可用：" 模板会把"账本里没这条"说成"路径不可用"，是更糟的谎。非 OS 异常原样透传。
    """
    if not isinstance(exc, OSError):
        return str(exc)
    target = path or getattr(exc, "filename", None) or ""
    if isinstance(exc, FileNotFoundError):
        return f"{noun}不存在：{target}" if target else str(exc)
    if isinstance(exc, PermissionError):
        return f"无权限访问：{target}" if target else str(exc)
    if isinstance(exc, NotADirectoryError):
        return f"不是目录：{target}" if target else str(exc)
    if isinstance(exc, IsADirectoryError):
        return f"不是文件：{target}" if target else str(exc)
    return f"路径不可用：{target}" if target else str(exc)


def workspace_http_error(
    exc: Exception, *, path: str | None = None, noun: str = "目录"
) -> HTTPException:
    """workspace 包 / OS 异常 → `HTTPException`；状态码取自 `_WORKSPACE_ERROR_STATUS`。

    与 `http_error` 同款：直接索引（不 `.get` 回退），未登记类型是编码错误，由
    `tests/web/test_domain_error_mapping.py` 的覆盖测试先红挡住。

    detail 走 `os_error_detail`（策展中文，**唯一一份**文案）；`host_dirs._os_error`
    也复用本函数，所以"注册项目 / 目录浏览 / 会话 cwd / 工作区文件"几处对同一个 errno
    说同一句话。`path` 是给调用方传 canonical 路径的（`OSError.filename` 在少数构造
    方式下为空）；`noun` 仅供读文件那条路径把"目录不存在"改成"文件不存在"。
    """
    return HTTPException(
        status_code=_WORKSPACE_ERROR_STATUS[type(exc)],
        detail=os_error_detail(exc, path=path, noun=noun),
    )


#: memory 领域 / 归属异常 → HTTP status 的第三张表（MEM-4 / #159）。
#:
#: 为什么又是单独一张：`_DOMAIN_ERROR_STATUS` 的键必须是 `SessionServiceError` 子类
#: （记忆不是会话服务），`_WORKSPACE_ERROR_STATUS` 的键是 workspace 包词汇。记忆有自己的
#: 领域异常（`memory/errors.py`），一个包一张表，键域各自自洽。
#:
#: **刻意不登记 `ValueError`**：它从 `MemoryNamespace.of` 冒出来只有一种情形——"要了
#: SESSION scope 却没有可信 session 绑定"。本票的用户 API **只暴露 USER scope**，而按 id
#: 操作到会话记忆的情形已由领域层的 `row_namespace_matches` 归入"不是你的记忆"
#: （→ `PermissionError` → 403），所以真冒出 ValueError 说明是**我们自己**的上下文处理
#: 写错了，500 才是诚实状态码，不该拿 422 盖住（同 `WorkspaceRegistryCorrupt` 的取舍）。
_MEMORY_ERROR_STATUS: dict[type[Exception], int] = {
    # 404：目标不存在（`forget` 返回 False 在入口层的显式化——对着一个具体 id 说"删了"，
    # 结果显示"这条不存在"，比静默成功更诚实）。
    MemoryNotFound: 404,
    # 403：存在但不能由当前身份/入口操作（归属不符，或 SESSION 行在本上下文解析不出绑定）。
    # **不是 404**——静默当成"不存在"会让越权探测变成没有反馈的猜谜，而领域层的归属校验
    # 本来就拒绝了，如实报 403。
    PermissionError: 403,
}


def memory_http_error(exc: Exception) -> HTTPException:
    """memory 领域 / 归属异常 → `HTTPException`；状态码取自 `_MEMORY_ERROR_STATUS`。

    与另外两张表同款：直接索引，未登记类型由覆盖测试先红挡住。
    """
    return HTTPException(
        status_code=_MEMORY_ERROR_STATUS[type(exc)], detail=str(exc)
    )


def http_error(exc: SessionServiceError) -> HTTPException:
    """领域异常 → `HTTPException`；状态码取自 `_DOMAIN_ERROR_STATUS` 单一映射源。

    `detail` 仍是 `str(exc)`——各端点的错误文案契约不变。调用方保持
    `raise http_error(e) from e` 以保留异常链。

    直接索引（不 `.get` 回退）：未登记类型是**编码错误**，且已被
    `test_status_map_covers_every_domain_exception` 挡住；此处再兜一层只会掩盖它。
    """
    return HTTPException(
        status_code=_DOMAIN_ERROR_STATUS[type(exc)], detail=str(exc)
    )
