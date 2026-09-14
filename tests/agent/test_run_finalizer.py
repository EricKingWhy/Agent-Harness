"""_RunFinalizer 单元测试：终态簿记 owner（批次 B / 候选 2）。

"一个 run 至多一条终态事件"的不变量此前由散布在 _drive 两条臂里的布尔旗
执行——本类收拢后可脱离 ScriptedModel 全链单测。
"""

import pytest

from agent_harness.agent.runtime import _RunFinalizer
from agent_harness.session import MODEL_FAILED, RUN_FAILED, RUN_STARTED, Session
from tests.conftest import make_session


@pytest.fixture
def session(tmp_path) -> Session:
    session = make_session(tmp_path)
    session.append(RUN_STARTED, {})
    return session


def test_cancelled_terminal_writes_reason_and_usage_once(session):
    usage: dict[str, int] = {"prompt_tokens": 100}
    finalizer = _RunFinalizer(session, usage)
    finalizer.begin_run("run-1")

    event = finalizer.cancelled_terminal(steps=2)
    assert event is not None and event.type == RUN_FAILED
    assert event.data["reason"] == "cancelled"
    assert event.data["usage_total"] == {"prompt_tokens": 100}
    # 单终态：第二次调用必须 no-op（双终结 = 历史不可对账）
    assert finalizer.cancelled_terminal(steps=2) is None


def test_terminal_marked_by_success_path_blocks_cancel_terminal(session):
    """成功路径已写 run/completed 后，取消臂不得再补 run/failed（取消可能
    恰好落在终结事件 yield / 收尾 checkpoint 的窗口里）。"""
    finalizer = _RunFinalizer(session, {})
    finalizer.begin_run("run-1")
    finalizer.mark_terminal_written()

    assert finalizer.cancelled_terminal(steps=1) is None
    assert finalizer.failure_terminal(steps=1) is None


def test_run_never_begun_writes_nothing(session):
    """begin_run 之前被取消/失败：没有 run 可终结，已写事件保持原样。"""
    finalizer = _RunFinalizer(session, {})
    assert finalizer.cancelled_terminal(steps=0) is None
    assert finalizer.failure_terminal(steps=0) is None
    assert session.events[-1].type == RUN_STARTED, "不得新增任何事件"


def test_model_failed_cancelled_message(session):
    finalizer = _RunFinalizer(session, {})
    finalizer.begin_run("run-1")
    finalizer.model_call_open = True

    event = finalizer.append_model_failed(step=0, cancelled=True)
    assert event.type == MODEL_FAILED
    assert event.data["message"] == "model call cancelled"
    assert event.step_id == 1


def test_model_failed_redacts_exception_message(session):
    """异常消息可能含 Provider 回显的敏感文本——事件只带类型名（脱敏不变量）。"""
    finalizer = _RunFinalizer(session, {})
    finalizer.begin_run("run-1")

    event = finalizer.append_model_failed(step=0, cancelled=False,
                                          error_type="TimeoutError")
    assert event.data["message"] == "model call failed: TimeoutError"
    assert "sk-secret" not in event.data["message"]


def test_failure_terminal_snapshots_usage(session):
    usage: dict[str, int] = {"prompt_tokens": 7, "completion_tokens": 3}
    finalizer = _RunFinalizer(session, usage)
    finalizer.begin_run("run-1")

    event = finalizer.failure_terminal(steps=1)
    assert event is not None and event.type == RUN_FAILED
    assert event.data["usage_total"] == {"prompt_tokens": 7, "completion_tokens": 3}
    # failure_terminal 同样受单终态约束
    assert finalizer.failure_terminal(steps=1) is None


def test_model_failed_readable_message_override(session):
    """readable_message 覆盖默认类型名消息——已分类故障（如内容审查拒绝）用
    固定可读文案，消费者（UI 事件检查器）无需翻服务端日志。"""
    readable = "provider 内容审查拒绝输入（可能因检索到的网页文本）"
    finalizer = _RunFinalizer(session, {})
    finalizer.begin_run("run-1")

    event = finalizer.append_model_failed(
        step=0,
        cancelled=False,
        error_type="BadRequestError",
        readable_message=readable,
    )
    assert event.data["message"] == readable
    # 覆盖不传时保持原行为
    event = finalizer.append_model_failed(
        step=0,
        cancelled=False,
        error_type="TimeoutError",
    )
    assert event.data["message"] == "model call failed: TimeoutError"


def test_failure_terminal_writes_reason_and_message(session):
    """reason（机器分类）+ message（可读文案）成对落 run/failed data——
    与上下文超限路径的 RUN_FAILED 形状一致；两者缺省时都不落键。"""
    readable = "provider 内容审查拒绝输入（可能因检索到的网页文本）"
    usage: dict[str, int] = {"prompt_tokens": 7}
    finalizer = _RunFinalizer(session, usage)
    finalizer.begin_run("run-1")

    event = finalizer.failure_terminal(
        steps=1,
        reason="provider_content_moderation",
        message=readable,
    )
    assert event.data["reason"] == "provider_content_moderation"
    assert event.data["message"] == readable
    assert event.data["usage_total"] == {"prompt_tokens": 7}
