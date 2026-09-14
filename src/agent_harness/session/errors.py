"""SessionService 领域异常层级（从 service.py 抽出，候选 2 纯结构重构）。

调用方（Web handler / CLI）负责把领域异常翻译为 HTTP status / CLI 错误消息。
所有异常都继承 ``SessionServiceError``，便于调用方统一 catch。

抛出点不限于 ``SessionService``：``session/session.py``（聚合加载校验）与
``session/store.py``（落盘守卫）也抛 ``SeqConflict``——它描述的是「会话事件流的
seq 纪律」，属会话领域、与传输层无关；基类名沿用历史命名，不再另立层级。

本模块无行为变化——异常类逐字搬移，``service.py`` 重新导出以保持所有既有
导入路径（``from agent_harness.session.service import SessionNotFound``）不变。
"""

from __future__ import annotations


class SessionServiceError(Exception):
    """SessionService 所有领域异常的基类。"""


class SessionNotFound(SessionServiceError):
    """session_id 不存在（store 中无事件）。"""


class InvalidSessionId(SessionServiceError):
    """session_id 格式不合法（安全校验失败）。"""


class ActiveRunConflict(SessionServiceError):
    """session 已有在途 run，不允许并发。"""


class SessionHasChildren(SessionServiceError):
    """会话是别的会话的 fork 父，不能删（ADR-0029 D4）。

    刻意**不级联**：静默删掉用户没选中的子会话不可接受；也刻意**不静默 orphan**：
    子会话会带着一个悬空来源链接（lineage 显示 "(parent missing)"）。所以拒绝，
    并把子会话数量写进 detail，由用户先处理子会话。"""


class ApprovalQueueMissing(SessionServiceError):
    """session 没有交互式审批队列（permission_mode 非交互，或 run 已结束）。"""


class ApprovalRequestMissing(SessionServiceError):
    """approval_id 在 session 事件中找不到对应的 approval-requested。"""


class ApprovalAlreadyResolved(SessionServiceError):
    """approval_id 已被决策（防重复）。"""


class InvalidDecision(SessionServiceError):
    """决策值不合法或不在 allowed_decisions 内。"""


class RecoveryConflict(SessionServiceError):
    """恢复需要人工裁决（UNKNOWN 工具状态）。"""


class SeqConflict(SessionServiceError):
    """事件 seq 与已落盘日志冲突（重复 / 回退），或日志本身已不满足单调性。

    两种触发面（消息里区分，状态码同为 409——都是「资源当前状态与请求冲突」，
    而不是「资源不存在」）：

    - **写时冲突**：并发写者各自基于同一份快照取号，后一个的 seq 已被占用。
      调用方可重新读取快照后重试（``service.change_model`` 即如此）。
    - **读时冲突**：日志里已存在重复 / 回退 seq（历史损坏，如真机会话
      ``dd983104`` 的两条 seq=5）——不可自愈，需人工处置。

    BUG-011 前这两种情况要么被静默写坏（重复 seq 落盘），要么被
    ``service.resume_and_launch`` 的 ``except ValueError`` 一刀切翻译成
    ``SessionNotFound``（HTTP 404，把数据完整性问题谎报成「会话不存在」）。
    """


class WorkspaceNameInvalid(SessionServiceError):
    """workspace 名字不合法（路径逃逸风险）。"""


class WorkspacePathInvalid(WorkspaceNameInvalid):
    """`cwd` 路径不合法（ADR-0027 / #169 AC1）：非绝对路径 / 不存在 / 不是目录。

    继承 `WorkspaceNameInvalid`：HTTP 层同一 422 语义（detail 文案区分），handler 的
    `except WorkspaceNameInvalid` 天然覆盖。**不能**只靠父类——领域错误表是精确类型
    索引，子类必须自己登记（`web/domain_errors.py`）。
    """


class WorkspaceNotFound(SessionServiceError):
    """workspace_id 不存在（项目未注册 / 装配里没有 workspace 索引）。

    WS-3 / #153：按项目列会话时，未注册的项目**不能**伪装成"空列表"——那是在谎报
    "这个项目没有会话"（不变量 #21 同族：缺席不造假）。由
    `SessionService.list_sessions` 把 workspace 层的 `UnknownWorkspace` 翻成本异常
    （同一套"下层异常翻译成本层词汇"的既有做法，见 `ForkBoundaryError` →
    `InvalidForkBoundary`）。
    """


class WorkspaceMoveInvalid(SessionServiceError):
    """请求的会话↔项目移动在当前状态下不成立（WS-4 / #154，AC7 的对应物）。

    三种来源，都是**状态冲突**而不是"参数写错"，所以是 409 而非 422：

    1. 会话 header 没有 cwd 锚（历史遗留）——无法判定它属于哪个目录，写进账本会留下
       "账本有 id 但会话无 cwd"的中间态；
    2. 会话的 cwd 指向的项目 ≠ 请求里的项目——项目归属由**目录**决定（ADR-0025 D1），
       不能凭调用方指定；
    3. 重排的会话或锚点不在该项目的可见成员里——账本序只在项目内定义。

    与 `WorkspaceNameInvalid`（名字形态非法 → 422）刻意分开：那条是"请求本身不合法"，
    这条是"请求合法但当前状态不允许"。
    """


class QueueItemNotFound(SessionServiceError):
    """排队消息不存在 / 已消费 / 已取消。"""


class SteerTargetNotFound(SessionServiceError):
    """steer 目标 run 不存在（无在途 run）。"""


class UnknownModel(SessionServiceError):
    """模型切换目标不在 catalog 中（provider + model_id 未命中）。"""


class InvalidForkBoundary(SessionServiceError):
    """fork 锚点非法（不是用户消息 seq / 前缀含未终态 run）。"""
