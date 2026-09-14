"""会话级模型切换领域逻辑（T7 #137；从 service.py 抽出，候选 2 纯结构重构）。

纯领域函数集合，无功状态、不依赖 ``SessionService`` 实例：

- ``current_model_selection`` —— 从事件流派生「当前模型」（append-only 确定性）。
- ``resolve_model_target`` —— (provider, model_id) → ``ModelTarget``。
- ``append_model_change`` —— ``MODEL_CHANGED`` 的唯一写入口。
- ``inherit_parent_model`` —— fork child 继承父会话当前模型。
- ``assert_model_resolvable`` —— 校验目标真能装配（provider 已知 + key 可用）。

``service.py`` 重新导出全部公开符号，既有导入路径与 CLI/Web 调用点不变。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from agent_harness.config import Settings
from agent_harness.session.amend import AmendOptions
from agent_harness.session.event import (
    MODEL_CHANGED,
    SESSION_STARTED,
    SessionEvent,
)
from agent_harness.session.session import Session

logger = logging.getLogger("agent_harness.session.model_switch")


def current_model_selection(events: list[SessionEvent]) -> tuple[str | None, str | None]:
    """从事件流派生会话当前模型 (provider, model_id)。

    优先级：最后一条 ``model/changed`` 的 to_* > ``session/started`` 的初始值
    > (None, None)（= 默认链）。append-only 语义下"最后一次切换"即当前模型，
    replay 确定性（不变量 #3）。
    """
    for event in reversed(events):
        if event.type == MODEL_CHANGED:
            return event.data.get("to_provider"), event.data.get("to_model_id")
    for event in reversed(events):
        if event.type == SESSION_STARTED:
            return event.data.get("provider"), event.data.get("model_id")
    return None, None


def amend_with_session_model(
    amend: AmendOptions | None, events: list[SessionEvent], settings: Settings
) -> AmendOptions | None:
    """未显式指定 model 时，用 session 派生的当前模型补齐。

    显式 amend.model 永远优先（一次性覆盖）；session 也没记录模型则原样返回
    （走默认链，行为不变）。session 记录的模型若已不在 catalog（配置变更），
    回落默认链并记 warning——历史选择不该让续聊 500。AGENT_MODELS 本身畸形
    仍是配置错误，`parse_model_catalog` 照旧响亮失败（不静默降级）。
    """
    if amend is not None and amend.model is not None:
        return amend
    provider, model_id = current_model_selection(events)
    if model_id is None:
        return amend

    from agent_harness.model.config import find_catalog_entry

    if find_catalog_entry(settings, provider or "", model_id) is None:
        logger.warning(
            "会话当前模型 %s/%s 已不在 catalog，本轮回落默认链", provider, model_id
        )
        return amend
    return replace(amend or AmendOptions(), model=model_id)


def default_model_id(settings: Settings) -> str:
    """默认链在 ``GET /api/models`` 里的 picker id（= 默认模型名）。"""
    from agent_harness.model.config import ModelConfig

    return ModelConfig.from_settings(settings).model_name


def is_default_selection(settings: Settings, provider: str, model_id: str) -> bool:
    """判断目标是否是 ``GET /api/models`` 的默认条目（is_default=true）。

    默认条目不是一个 catalog 条目，但前端 picker 会展示它——选中它 = 清除会话级
    覆盖、回到默认链（事件写 ``to_model_id=None``）。
    """
    from agent_harness.model.config import ConfigError

    if provider != settings.model_provider:
        return False
    try:
        resolved_default = default_model_id(settings)
    except ConfigError:
        return False
    return model_id in {resolved_default, "default"}


@dataclass(frozen=True)
class ModelTarget:
    """一次模型切换的解析结果（T7 #137）。

    ``model_id=None`` = 切回默认链（``GET /api/models`` 的 is_default 条目）；
    ``effective_model_id`` 是 picker 应显示的 id——catalog 条目名，或默认链的默认
    模型名（HTTP 响应回传它，避免 handler 自己推导领域值）。
    """

    provider: str
    model_id: str | None
    effective_model_id: str


def resolve_model_target(
    settings: Settings, provider: str, model_id: str
) -> ModelTarget | None:
    """解析 (provider, model_id) → ModelTarget；未命中返回 None。

    默认条目优先于同名 catalog 条目：picker 的默认选项 id 就是默认模型名，
    catalog 恰有同名条目时必须按「默认条目 = 清覆盖」语义处理，否则前端选默认
    反而锁死在该 catalog 条目的 base_url / temperature 上。
    """
    from agent_harness.model.config import find_catalog_entry

    if is_default_selection(settings, provider, model_id):
        return ModelTarget(
            provider=provider, model_id=None,
            effective_model_id=default_model_id(settings),
        )
    entry = find_catalog_entry(settings, provider, model_id)
    if entry is None:
        return None
    return ModelTarget(
        provider=entry.provider, model_id=entry.name, effective_model_id=entry.name,
    )


@dataclass(frozen=True)
class ModelChange:
    """一次模型切换的结果。

    ``from_*`` 可能为 None = 此前走默认链；``to_model_id`` 为 None = 切回默认链
    （选中 ``GET /api/models`` 的 ``is_default`` 条目），后续 run 不再带 catalog 覆盖。
    ``effective_model_id`` = 前端 picker 应对齐的 id（见 ``ModelTarget``）。
    """

    from_provider: str | None
    from_model_id: str | None
    to_provider: str
    to_model_id: str | None
    effective_model_id: str


def append_model_change(session: Session, target: ModelTarget) -> ModelChange:
    """追加 ``model/changed``——MODEL_CHANGED 的唯一写入口（T7 #137）。

    走 ``Session.append``（无 resume 副作用，不变量 #7）；``from_*`` 从事件流派生。
    service 与 CLI demo 共用，避免两处各自拼事件 data。
    """
    from_provider, from_model_id = current_model_selection(session.events)
    session.append(MODEL_CHANGED, {
        "from_provider": from_provider,
        "from_model_id": from_model_id,
        "to_provider": target.provider,
        "to_model_id": target.model_id,
    })
    return ModelChange(
        from_provider=from_provider,
        from_model_id=from_model_id,
        to_provider=target.provider,
        to_model_id=target.model_id,
        effective_model_id=target.effective_model_id,
    )


def inherit_parent_model(child: Session, parent_events: list[SessionEvent]) -> None:
    """child 继承父会话的当前模型（fork seed 不含父 ``session/started``，T7 #137）。

    父走默认链时什么都不做；父有会话级模型时补一条 ``model/changed``——否则父创建
    时选的 catalog 模型会在 child 静默回落默认链（切换过的父反而会继承，语义不一致）。
    """
    provider, model_id = current_model_selection(parent_events)
    if provider is None or model_id is None:
        return
    append_model_change(
        child,
        ModelTarget(
            provider=provider, model_id=model_id, effective_model_id=model_id,
        ),
    )


def assert_model_resolvable(settings: Settings, target: ModelTarget) -> None:
    """校验目标模型真能装配（provider 已知 + 有可用 key），否则 UnknownModel。

    AC「校验 provider 可用性」：catalog 成员资格之外，还确认 ``ModelConfig`` 能
    构造出来——与创建路径（``create_and_launch`` 的 ``from_catalog``）同一判据，
    避免 POST /model 接受一个 POST /sessions 会拒绝的目标。CLI 与 Web 共用。
    """
    from agent_harness.model.config import ConfigError, ModelConfig
    from agent_harness.session.errors import UnknownModel

    try:
        if target.model_id is None:
            ModelConfig.from_settings(settings)
        else:
            ModelConfig.from_catalog(settings, target.model_id)
    except (ConfigError, KeyError) as error:
        raise UnknownModel(str(error)) from error
