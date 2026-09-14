"""领域异常 → HTTP 映射的单一 source of truth（ARCH-5，#144）。

此前这段映射在 11 个 handler（app.py 10 + lineage.py 1）里各自重述，共 37 个
except 臂。本测试把「审计结论」钉成契约：状态码只允许在
`web/domain_errors.py::_DOMAIN_ERROR_STATUS` 一处改动。
"""

from __future__ import annotations

import pytest

from agent_harness.memory.errors import MemoryDomainError, MemoryNotFound
from agent_harness.session.errors import SessionNotFound, SessionServiceError
from agent_harness.web.domain_errors import (
    _DOMAIN_ERROR_STATUS,
    _MEMORY_ERROR_STATUS,
    _WORKSPACE_ERROR_STATUS,
    http_error,
    memory_http_error,
    workspace_http_error,
)
from agent_harness.workspace import (
    UnknownLedgerEntry,
    WorkspaceError,
)


def _all_subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def test_status_map_covers_every_domain_exception():
    """新增领域异常必须显式登记状态码。

    这是本设计的**正确性前提**：`http_error` 用直接索引查表（不猜、不回退），
    所以漏登记的类型一旦被端点捕获就会 KeyError。宁可在这里先红。
    """
    missing = _all_subclasses(SessionServiceError) - set(_DOMAIN_ERROR_STATUS)
    assert not missing, (
        "以下领域异常未登记 HTTP 状态码："
        f"{sorted(c.__name__ for c in missing)}"
    )


def test_status_map_is_the_audited_contract():
    """ARCH-5 逐 handler 审计结论（11 handler / 37 except 臂）——状态码不得漂移。

    审计要点：同一个领域异常在所有 handler 里状态码**一致**（这是「可单源化」的
    前提）；`approve` 的三个 404（SessionNotFound / ApprovalQueueMissing /
    ApprovalRequestMissing）**有意不可区分**（OBS-015）；`ApprovalAlreadyResolved`
    是 409 幂等已决而非 404。
    """
    assert {c.__name__: s for c, s in _DOMAIN_ERROR_STATUS.items()} == {
        "InvalidSessionId": 422,
        "SessionNotFound": 404,
        "WorkspaceNameInvalid": 422,
        # WS-6 / #169：`cwd` 形态/存在性非法（非绝对 / 不存在 / 不是目录）——与
        # workspace 名字非法同一个 422 语义（detail 文案区分）。它是
        # WorkspaceNameInvalid 的**子类**，但本表是**精确类型**索引，必须自己登记。
        "WorkspacePathInvalid": 422,
        "InvalidDecision": 422,
        "UnknownModel": 422,
        "InvalidForkBoundary": 422,
        "ActiveRunConflict": 409,
        "RecoveryConflict": 409,
        "ApprovalAlreadyResolved": 409,
        "SteerTargetNotFound": 409,
        "ApprovalQueueMissing": 404,
        "ApprovalRequestMissing": 404,
        "QueueItemNotFound": 404,
        # WS-3 / #153：按项目列会话时未注册的 workspace_id——与「项目存在但没有会话」
        # 必须可区分，所以是 404 而不是「空列表」（不变量 #21 同族：缺席不造假）。
        "WorkspaceNotFound": 404,
        # WS-4 / #154：会话↔项目的移动在当前状态下不成立（无 cwd 锚 / cwd 不属于该项目 /
        # 重排目标不在该项目账本里）——状态冲突而非入参非法，与 422 分开。
        "WorkspaceMoveInvalid": 409,
        # BUG-011：seq 冲突（并发写者抢先落盘 / 日志已损坏）——冲突不是「不存在」，
        # 必须与 SessionNotFound 的 404 区分开（旧行为把它翻成 404 掩蔽了日志损坏）。
        "SeqConflict": 409,
        # #172 / ADR-0029：会话是别的会话的 fork 父——不级联（删掉用户没选中的子会话）、
        # 不 orphan（留悬空来源链接），所以只有 409 诚实：请求形态没错、父也确实存在。
        "SessionHasChildren": 409,
    }


def test_http_error_reads_status_from_the_single_map():
    """detail 原样透传（各端点契约的 detail 文案不变），status 来自映射表。"""
    http = http_error(SessionNotFound("session 'x' not found"))
    assert http.status_code == 404
    assert http.detail == "session 'x' not found"


# ── WS-4 / #154：第二张表（workspace 包 / OS 词汇）──


def test_workspace_map_covers_every_workspace_exception():
    """`workspace` 包的每个领域异常都必须显式登记（`workspace_http_error` 直接索引）。"""
    missing = _all_subclasses(WorkspaceError) - set(_WORKSPACE_ERROR_STATUS)
    assert not missing, (
        "以下 workspace 领域异常未登记 HTTP 状态码："
        f"{sorted(c.__name__ for c in missing)}"
    )


def test_workspace_map_is_the_audited_contract():
    """WS-4 的项目端点审计结论——状态码不得漂移。

    关键区分：**未知目标**（无该项目 / 路径不存在）= 404；**路径存在但不是目录** =
    422（入参非法）；**账本序请求与账本现状冲突**（会话/锚点不在该项目账本里）= 409；
    **OS 拒绝该路径**（非法字符 EINVAL / 超长 ENAMETOOLONG，裸 `OSError`）= 422；
    **无权访问** = 403；**路径是目录但调用方要文件**（#191 读工作区文件，POSIX 的
    `IsADirectoryError`）= 422。
    `WorkspaceRegistryCorrupt` **刻意不登记**：索引损坏是服务端完整性故障，500 才诚实。
    """
    assert {c.__name__: s for c, s in _WORKSPACE_ERROR_STATUS.items()} == {
        "UnknownWorkspace": 404,
        "FileNotFoundError": 404,
        "UnknownLedgerEntry": 409,
        "NotADirectoryError": 422,
        "IsADirectoryError": 422,
        "OSError": 422,
        "PermissionError": 403,
    }


def test_workspace_map_covers_the_os_errors_create_can_raise():
    """`create()` 会原样透传的 OS 错误必须都有状态码——否则客户端可控路径换来 500。

    上一例只能枚举 `WorkspaceError` 子类，**发现不了"代码会抛的 OS 异常没登记"**，
    所以这条显式钉住：`os.stat` 的 EINVAL/ENAMETOOLONG 是裸 `OSError`、权限问题是
    `PermissionError`、目标不存在是 `FileNotFoundError`、不是目录是 `NotADirectoryError`。
    """
    for exc in (
        OSError(22, "Invalid argument"),
        PermissionError(13, "denied"),
        FileNotFoundError(2, "missing"),
        NotADirectoryError(20, "not a dir"),
    ):
        http = workspace_http_error(exc)
        assert 400 <= http.status_code < 500, f"{type(exc).__name__} → {http.status_code}"


def test_workspace_http_error_curates_the_os_detail():
    """detail 是**策展中文**（API-01，2026-09-13 真机验收）。

    此前 `str(exc)` 原样透传，于是同一个路径在"注册项目"里显示
    `[Errno 20] 不是目录: 'D:\\x\\readme.txt'`、在"目录浏览"里显示
    `不是目录：D:\\x\\readme.txt`——同一事实两种说法。现在两处共用本函数。
    """
    cases = [
        (NotADirectoryError(20, "不是目录", "D:/x"), 422, "不是目录：D:/x"),
        (FileNotFoundError(2, "missing", "D:/y"), 404, "目录不存在：D:/y"),
        (PermissionError(13, "denied", "D:/z"), 403, "无权限访问：D:/z"),
        (OSError(22, "Invalid argument", "C:/bad<name>"), 422, "路径不可用：C:/bad<name>"),
    ]
    for exc, status, detail in cases:
        http = workspace_http_error(exc)
        assert http.status_code == status, f"{type(exc).__name__} → {http.status_code}"
        assert http.detail == detail, f"{type(exc).__name__} → {http.detail!r}"


def test_workspace_http_error_prefers_the_callers_canonical_path():
    """调用方给的 canonical 优先于 `OSError.filename`（host/dirs 用这条保证路径已规范化）。"""
    http = workspace_http_error(NotADirectoryError(20, "不是目录", "D:/raw"), path="D:/canonical")
    assert http.detail == "不是目录：D:/canonical"


def test_workspace_http_error_keeps_str_when_the_path_is_unknown():
    """两个路径来源都拿不到时**退回 `str(exc)`**：宁可文案粗糙，也不丢信息。

    `OSError.filename` 并非总有（手写异常、某些包装层）；这条钉住"退路不丢信息"。
    """
    bare = OSError(22, "Invalid argument")
    assert workspace_http_error(bare).detail == str(bare)


def test_workspace_http_error_does_not_dress_domain_errors_as_path_errors():
    """`WorkspaceError`（非 OS 异常）**原样透传**，不被套上"路径不可用："模板。

    同一个入口也接 `UnknownWorkspace` / `UnknownLedgerEntry`——它们的消息自带语义
    （"账本里没这条"），套路径模板会把事实说错。
    """
    ledger = UnknownLedgerEntry("会话不在该项目账本里：s-1")

    http = workspace_http_error(ledger)

    assert http.status_code == 409
    assert http.detail == str(ledger)


# ── MEM-4 / #159：第三张表（memory 领域 / 归属词汇）──


def test_memory_map_covers_every_domain_exception():
    """`memory` 包的每个领域异常都必须显式登记（`memory_http_error` 直接索引）。

    与另外两张表同款的**正确性前提**：漏登记的类型一旦被端点捕获就是 KeyError，所以在这里
    先红，而不是等到线上把一个 404 变成 500。
    """
    missing = _all_subclasses(MemoryDomainError) - set(_MEMORY_ERROR_STATUS)
    assert not missing, (
        "以下 memory 领域异常未登记 HTTP 状态码："
        f"{sorted(c.__name__ for c in missing)}"
    )


def test_memory_map_is_the_audited_contract():
    """记忆端点的错误语义——状态码不得漂移。

    关键区分：**未知记忆 id** = 404（用户对着一个具体 id 点删除，"这条不在了"要报出来，
    不是静默成功）；**存在但属于别人** = 403（领域层的归属校验如实上报，不伪装成 404）。
    `ValueError`（"要了 SESSION scope 却没有可信绑定"）**刻意不登记**：按 id 操作到会话记忆
    已由 `row_namespace_matches` 归入"不是你的记忆"，真冒出它说明是我们自己的上下文处理
    写错了，500 才诚实。
    """
    assert {c.__name__: s for c, s in _MEMORY_ERROR_STATUS.items()} == {
        "MemoryNotFound": 404,
        "PermissionError": 403,
    }


def test_memory_http_error_preserves_detail_and_rejects_unregistered_types():
    error = MemoryNotFound("mem-1")
    http = memory_http_error(error)
    assert http.status_code == 404
    assert "mem-1" in http.detail

    assert memory_http_error(PermissionError("不属于当前用户")).status_code == 403

    # 未登记类型是编码错误：直接索引 → KeyError（由覆盖测试先红挡住），不静默 500。
    with pytest.raises(KeyError):
        memory_http_error(ValueError("session binding missing"))
