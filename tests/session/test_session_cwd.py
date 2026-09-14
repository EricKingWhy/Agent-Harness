"""WS-1 / issue #151：会话侧 cwd 锚（`session/started` 的 `cwd`）。

覆盖 AC1–AC7。三处**语义**断言值得单独指出，因为它们是本票的设计核心而非实现细节：

1. **规范化同源（AC5）**：把同一目录的**不同写法**分别喂给两个写入点
   （注册表映射 / 会话事件），落盘后必须是**逐字符相等**的两个字符串。
2. **加法式（AC3）**：老日志没有该字段 → 读出 `None`，且不抛异常；形状非法
   （空串 / 非字符串）同样按"没有"处理，绝不猜测回填。
3. **不可变（AC2）**：resume / 模型切换 / 追加消息之后，`session/started` 那一行
   必须**逐字节未变**（不只是值相等）。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from agent_harness.agent.factory import AgentFactory
from agent_harness.multiagent.provider import InProcessSubagentProvider
from agent_harness.multiagent.tools import DelegateTool
from agent_harness.sandbox import WorkspaceRegistry, canonical_workspace_path
from agent_harness.session import Session, cwd_event_data, session_cwd
from agent_harness.session.event import SESSION_STARTED, USER_MESSAGE
from agent_harness.session.store import JsonlSessionStore
from agent_harness.tooling import ToolExecutor, ToolRegistry, ToolResult
from tests.scripted_model import ScriptedModel


def _store(tmp_path: Path) -> JsonlSessionStore:
    return JsonlSessionStore(root=tmp_path / "sessions")


def _events_path(tmp_path: Path, session_id: str) -> Path:
    return tmp_path / "sessions" / session_id / "events.jsonl"


def _started_data(store: JsonlSessionStore, session_id: str) -> dict:
    events = store.read_events(session_id)
    started = [e for e in events if e.type == SESSION_STARTED]
    assert len(started) == 1, "一个会话只应有一条 session/started"
    return started[0].data


#: "删掉该键"的哨兵——与"把值写成字面 null"必须能区分开。
_POP: object = object()


def _canon(path: Path) -> str:
    """期望值的规范化形式。

    断言不写死 `str(tmp_path / ...)`：`tmp_path` 自身在某些平台上带链接
    （macOS 的 `/var` → `/private/var`），落盘值是解析后的形式，写死未解析的
    字符串会在那些平台上假红。期望值也过同一个函数。
    """
    return canonical_workspace_path(path)


def _make_directory_link(link: Path, target: Path) -> bool:
    """在 link 处建一个指向 target 的目录链接；本机做不到返回 False。

    先试符号链接；Windows 未开 Developer Mode / 非管理员时没有该特权，退化为
    **目录联接**（junction）——两者都是 reparse point，`realpath` 都把 link 解析到
    目标目录，正是 AC7 要的"符号链接指向同一目录"等价类。链接与其目标都建在
    `tmp_path` 内，清理时不会波及测试目录之外。
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    # 输出丢弃：mklink 的提示文本是本地代码页（非 UTF-8），读它只会在
    # subprocess 的 reader 线程里炸出 UnicodeDecodeError，返回码已经够了。
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return completed.returncode == 0


class TestWriteSide:
    def test_cwd_is_written_and_canonicalized(self, tmp_path: Path) -> None:
        """AC1：规范化绝对路径落盘（尾部斜杠被解析掉）。"""
        store = _store(tmp_path)
        project = tmp_path / "proj"
        session = Session.start(store, session_id="s1", cwd=f"{project}{os.sep}")
        stored = session.events[0].data["cwd"]
        assert stored == _canon(project)
        # 输入带尾分隔符、落盘值不带：证明"规范化"真的吃掉了尾部斜杠，而不是原样透传。
        # 不写 `== str(project)`——`tmp_path` 自身在带链接的平台上（macOS `/var`）未解析
        # 写法与解析后写法并不相等，那样写会在那些平台上假红（见 `_canon`）。
        assert not stored.endswith(os.sep)

    def test_cwd_is_persisted_before_start_returns(self, tmp_path: Path) -> None:
        """AC6 前置半：返回时事件已**落盘**（此后任何 attach 都能读到 cwd）。

        attach 那一半属 WS-2（本票无 attach）；本票保证的是"会话先落盘"这一序。
        """
        store = _store(tmp_path)
        session = Session.start(store, session_id="s2", cwd=tmp_path / "proj")
        assert _started_data(store, session.session_id)["cwd"] == _canon(tmp_path / "proj")

    def test_cwd_absent_when_not_given(self, tmp_path: Path) -> None:
        """AC3：不给 cwd 就不写字段（而不是写一个 None）。"""
        store = _store(tmp_path)
        session = Session.start(store, session_id="s3")
        assert "cwd" not in session.events[0].data
        assert session_cwd(session.events) is None

    def test_cwd_coexists_with_existing_started_data(self, tmp_path: Path) -> None:
        """AC3 加法式：既有字段（provider / model_id）零改动。"""
        store = _store(tmp_path)
        session = Session.start(
            store, session_id="s4",
            started_data={"provider": "openai", "model_id": "gpt-x"},
            cwd=tmp_path / "proj",
        )
        data = session.events[0].data
        assert data["provider"] == "openai" and data["model_id"] == "gpt-x"
        assert data["cwd"] == _canon(tmp_path / "proj")

    def test_cwd_event_data_is_empty_for_none(self) -> None:
        assert cwd_event_data(None) == {}
        # 空串同样必须挡掉：`realpath("")` 返回**进程当前工作目录**，会把会话
        # 静默锚到服务器碰巧启动的目录（读取侧本就把空串当"无 cwd"）。
        assert cwd_event_data("") == {}
        assert cwd_event_data(".") == {"cwd": canonical_workspace_path(".")}

    def test_cwd_smuggled_in_started_data_is_dropped(self, tmp_path: Path) -> None:
        """写侧只认 `cwd` 参数：started_data 里夹带的同名键会绕过唯一一套规范化（AC5）。"""
        store = _store(tmp_path)
        session = Session.start(
            store, session_id="smuggle",
            started_data={"provider": "p", "cwd": "relative/../raw//path"},
        )
        assert "cwd" not in session.events[0].data
        assert session.events[0].data["provider"] == "p"  # 其余键照旧

    def test_explicit_cwd_param_beats_started_data(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        session = Session.start(
            store, session_id="both",
            started_data={"cwd": "relative/../raw//path"},
            cwd=tmp_path / "proj",
        )
        assert session.events[0].data["cwd"] == _canon(tmp_path / "proj")


class TestReadSideIsAdditive:
    def _strip_cwd(self, tmp_path: Path, session_id: str, value: object = _POP) -> None:
        """把已落盘日志的第一行改成"旧日志"形状（无 cwd，或塞一个非法 cwd）。"""
        path = _events_path(tmp_path, session_id)
        lines = path.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        if value is _POP:
            first["data"].pop("cwd", None)
        else:
            first["data"]["cwd"] = value
        lines[0] = json.dumps(first, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_legacy_session_without_cwd_reads_none(self, tmp_path: Path) -> None:
        """AC3：历史遗留会话读出 None，且读取不报错。"""
        store = _store(tmp_path)
        Session.start(store, session_id="legacy", cwd=tmp_path / "proj")
        self._strip_cwd(tmp_path, "legacy")
        events = store.read_events("legacy")
        assert events, "读取本身不得失败"
        assert session_cwd(events) is None

    @pytest.mark.parametrize("bad", ["", 123, None, {"nested": True}])
    def test_malformed_cwd_reads_none_without_raising(self, tmp_path: Path, bad: object) -> None:
        """`None` 这一档写的是**字面 null**（不是"删掉该键"，那是另一档）。"""
        store = _store(tmp_path)
        sid = f"bad-{type(bad).__name__}"
        Session.start(store, session_id=sid, cwd=tmp_path / "proj")
        self._strip_cwd(tmp_path, sid, bad)
        raw_first = json.loads(_events_path(tmp_path, sid).read_text(encoding="utf-8").splitlines()[0])
        assert "cwd" in raw_first["data"], "本档要测的是「有键但值非法」，不是键缺失"
        assert session_cwd(store.read_events(sid)) is None

    def test_first_started_event_wins(self, tmp_path: Path) -> None:
        """AC2 的派生语义：权威值是**第一条** started——后追加的不改写归属。"""
        store = _store(tmp_path)
        session = Session.start(store, session_id="dup", cwd=tmp_path / "proj")
        session.append(SESSION_STARTED, {"cwd": _canon(tmp_path / "elsewhere")})
        assert session_cwd(store.read_events("dup")) == _canon(tmp_path / "proj")


class TestImmutability:
    def test_resume_and_model_change_leave_started_line_byte_identical(self, tmp_path: Path) -> None:
        """AC2：resume / 模型切换 / 续聊之后 started 行逐字节未变。"""
        store = _store(tmp_path)
        session = Session.start(store, session_id="imm", cwd=tmp_path / "proj")
        path = _events_path(tmp_path, session.session_id)
        first_line_before = path.read_bytes().split(b"\n", 1)[0]

        resumed = Session.resume(store, session.session_id)
        resumed.append(USER_MESSAGE, {"content": "续聊"})
        from agent_harness.session.model_switch import (
            ModelTarget,
            append_model_change,
        )
        append_model_change(
            resumed, ModelTarget(provider="p", model_id="m", effective_model_id="m")
        )

        path = _events_path(tmp_path, session.session_id)
        assert path.read_bytes().split(b"\n", 1)[0] == first_line_before
        assert session_cwd(store.read_events(session.session_id)) == _canon(tmp_path / "proj")
        assert len([e for e in store.read_events(session.session_id)
                    if e.type == SESSION_STARTED]) == 1

    def test_replay_reads_do_not_modify_the_log(self, tmp_path: Path) -> None:
        """replay 路径只读：连读两次，文件与 cwd 都不变。"""
        store = _store(tmp_path)
        session = Session.start(store, session_id="ro", cwd=tmp_path / "proj")
        path = _events_path(tmp_path, session.session_id)
        before = path.read_bytes()
        for _ in range(2):
            assert session_cwd(store.read_events(session.session_id)) == _canon(tmp_path / "proj")
        assert path.read_bytes() == before


class TestCanonicalEquivalence:
    def test_equivalent_spellings_are_one_path(self, tmp_path: Path) -> None:
        """AC7：`D:\\a\\b\\`、`D:\\a\\..\\a\\b`、符号链接 → 同一路径。"""
        root = tmp_path / "a"
        target = root / "b"
        target.mkdir(parents=True)
        link = tmp_path / "link-to-b"

        forms = [f"{target}{os.sep}", root / ".." / "a" / "b"]
        if _make_directory_link(link, target):
            forms.append(link)

        canonical = {canonical_workspace_path(form) for form in forms}
        assert len(canonical) == 1, canonical
        assert canonical.pop() == _canon(target)

    def test_symlinked_directory_is_resolved(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "alias"
        if not _make_directory_link(link, real):
            pytest.skip("当前环境既不能建符号链接也不能建目录联接")
        assert canonical_workspace_path(link) == canonical_workspace_path(real)


class TestSameSourceAsWorkspaceRegistry:
    """AC5：映射文件里的 workspace_root 与会话事件里的 cwd 是**同一个字符串**。"""

    def test_two_write_points_agree_across_spellings(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        registry = WorkspaceRegistry(root=tmp_path)
        project = tmp_path / "workspaces" / "myproj"

        # 两个写入点各喂一种**等价但不同**的写法：注册表用 `..` 绕一圈，
        # 会话侧带尾部斜杠 + `.`。落盘后必须完全相等。
        registry.create(
            "k", workspace_root=tmp_path / "workspaces" / ".." / "workspaces" / "myproj"
        )
        session = Session.start(
            store, session_id="k", workspace_registry=registry,
            cwd=f"{project}{os.sep}.",
        )

        mapping = json.loads((tmp_path / "workspaces" / "k.json").read_text(encoding="utf-8"))
        assert mapping["workspace_root"] == session_cwd(session.events)
        assert mapping["workspace_root"] == canonical_workspace_path(project)

    def test_two_write_points_agree_through_a_link(self, tmp_path: Path) -> None:
        """AC5 的判别式：会话侧喂**链接写法**、注册表喂真实路径 → 落盘仍逐字符相等。

        `..` / 尾部斜杠 / `.` 这些写法连 `os.path.abspath` 都能吃掉，只有"经链接
        指向同一目录"能把 `realpath` 与 `abspath` 分开。把会话侧的规范化退化成
        `abspath`，本用例即变红（映射里是解析后的路径，事件里留着链接路径）——
        那正是 AC5 禁止的"同一路径两套规范化"。
        """
        store = _store(tmp_path)
        registry = WorkspaceRegistry(root=tmp_path)
        project = tmp_path / "real-project"
        project.mkdir()
        link = tmp_path / "alias-project"
        if not _make_directory_link(link, project):
            pytest.skip("当前环境既不能建符号链接也不能建目录联接")

        sandbox = registry.create("lk", workspace_root=project)
        session = Session.start(store, session_id="lk", cwd=link)

        raw = json.loads((tmp_path / "workspaces" / "lk.json").read_text(encoding="utf-8"))
        assert raw["workspace_root"] == _canon(project)
        assert session_cwd(session.events) == raw["workspace_root"]
        assert _canon(sandbox.workspace_root) == raw["workspace_root"]

    def test_registry_mapping_is_canonical(self, tmp_path: Path) -> None:
        registry = WorkspaceRegistry(root=tmp_path)
        registry.create("m", workspace_root=tmp_path / "ws" / ".." / "ws2")
        mapping = json.loads((tmp_path / "workspaces" / "m.json").read_text(encoding="utf-8"))
        assert mapping["workspace_root"] == canonical_workspace_path(tmp_path / "ws2")

    def test_default_workspace_is_canonical(self, tmp_path: Path) -> None:
        """默认 workspace 位置本身是链接时，映射里必须写**解析后**的路径。

        把 `<root>/workspaces/<session_id>` 预先做成链接，`create()` 的规范化才有
        可观测效果：去掉它，映射里留下的是链接路径而不是目标路径（单行变异即可
        让本用例变红）。用普通目录做不到——那时 raw 字符串本来就等于规范化结果
        （`WorkspaceRegistry.__init__` 已 resolve 过根目录）。
        """
        root = tmp_path / "root"
        (root / "workspaces").mkdir(parents=True)
        target = tmp_path / "real-workspace"
        target.mkdir()
        if not _make_directory_link(root / "workspaces" / "d", target):
            pytest.skip("当前环境既不能建符号链接也不能建目录联接")

        registry = WorkspaceRegistry(root=root)
        sandbox = registry.create("d")

        mapping = json.loads((root / "workspaces" / "d.json").read_text(encoding="utf-8"))
        assert mapping["workspace_root"] == _canon(target)
        assert mapping["workspace_root"] == _canon(sandbox.workspace_root)


class TestForkInheritance:
    """AC4：child 的 cwd 显式继承自 parent（不靠"反正目录是复制来的"隐式成立）。

    注意语义边界：记录的是**项目归属**（父的 cwd），不是 child 自己那份
    copy-on-fork 目录（ADR-0017 决策 5 的物理隔离是另一件事）。若按后者取，
    每次 fork 都会凭空多出一个"项目"，与"项目 → 多会话"的目标相反。
    """

    async def _fork(self, tmp_path: Path, store: JsonlSessionStore, parent_id: str) -> str:
        from agent_harness.cli import fork_command

        parent_events = store.read_events(parent_id)
        boundary = parent_events[-1].seq
        return await fork_command(
            parent_id, from_message=boundary, no_summary=True,
            workspace_dir=str(tmp_path), write=lambda _line: None,
        )

    @pytest.mark.asyncio
    async def test_child_inherits_parent_cwd(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        parent = Session.start(store, session_id="p1", cwd=tmp_path / "proj")
        parent.append(USER_MESSAGE, {"content": "分叉点"})

        child_id = await self._fork(tmp_path, store, "p1")

        assert session_cwd(store.read_events(child_id)) == _canon(tmp_path / "proj")

    @pytest.mark.asyncio
    async def test_child_of_legacy_parent_has_no_cwd(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        parent = Session.start(store, session_id="p2")  # 历史遗留：无 cwd
        parent.append(USER_MESSAGE, {"content": "分叉点"})

        child_id = await self._fork(tmp_path, store, "p2")

        # 先证明 fork 这条路径**真的跑过**（否则本用例无法区分"显式继承到 None"
        # 与"继承代码根本没执行"——那就是空转）。
        child_types = [e.type for e in store.read_events(child_id)]
        assert "session/forked" in child_types
        assert session_cwd(store.read_events(child_id)) is None
        assert "cwd" not in _started_data(store, child_id)


class _EchoArgs(BaseModel):
    text: str = "x"


class _Echo:
    """最小工具替身（registry 只看 name/description/args_schema/execute）。"""

    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return "read"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EchoArgs

    async def execute(self, args: _EchoArgs) -> ToolResult:
        return ToolResult.success(message=args.text)


def _spawn_setup(
    tmp_path: Path, *, parent_id: str, parent_cwd: Path | None, child_answers: int = 1,
    monkeypatch=None,
) -> tuple[DelegateTool, InProcessSubagentProvider, JsonlSessionStore]:
    """装配一个可真实 spawn 子会话的 provider（父会话可选带 cwd）。"""
    store = _store(tmp_path)
    workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
    workspace_registry.create(parent_id, workspace_root=tmp_path / "project")
    Session.start(store, session_id=parent_id, cwd=parent_cwd)

    if monkeypatch is not None:
        reads: list[str] = []
        original = store.read_events

        def counting(session_id: str, _reads=reads, _original=original):
            _reads.append(session_id)
            return _original(session_id)

        monkeypatch.setattr(store, "read_events", counting)
        store.parent_reads = reads  # type: ignore[attr-defined]

    provider_impl = InProcessSubagentProvider()
    tool = DelegateTool(provider_impl)
    source_registry = ToolRegistry()
    source_registry.register(_Echo())
    provider_impl.activate(
        factory=AgentFactory(
            model=ScriptedModel([AIMessage(content=f"child {i}") for i in range(child_answers)]),
            primary_model_name="main-model",
            executor_factory=ToolExecutor,
        ),
        source_registry=source_registry,
        session_store=store,
        workspace_registry=workspace_registry,
        parent_session_id=parent_id,
    )
    return tool, provider_impl, store


def _delegate_args() -> object:
    return type("_Args", (), {"target": "coding", "task": "x", "constraints": []})()


class TestSubagentChildInheritance:
    """同一继承规则的另一条子会话路径：SubAgent child（不写就会作为"未分组"冒出来）。"""

    @pytest.mark.asyncio
    async def test_subagent_child_inherits_parent_cwd(self, tmp_path: Path) -> None:
        tool, provider_impl, _ = _spawn_setup(
            tmp_path, parent_id="parent-cwd", parent_cwd=tmp_path / "project"
        )

        assert (await tool.execute(_delegate_args())).ok

        child = provider_impl.last_child_sessions[-1]
        assert session_cwd(child.events) == _canon(tmp_path / "project")

    @pytest.mark.asyncio
    async def test_subagent_child_of_legacy_parent_has_no_cwd(self, tmp_path: Path) -> None:
        """父无 cwd（老会话）→ 子也无：父子未分组状态保持一致。"""
        tool, provider_impl, _ = _spawn_setup(
            tmp_path, parent_id="parent-legacy", parent_cwd=None
        )

        assert (await tool.execute(_delegate_args())).ok
        child = provider_impl.last_child_sessions[-1]
        # 先证明子会话真的被创建（否则无法区分"继承到 None"与"根本没有子会话"）。
        assert child.events[0].type == SESSION_STARTED
        assert session_cwd(child.events) is None

    @pytest.mark.asyncio
    async def test_parent_cwd_is_read_once_across_spawns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """父 cwd 写后不可变 → 整个 provider 生命周期只读一次父 JSONL。"""
        tool, provider_impl, store = _spawn_setup(
            tmp_path, parent_id="parent-once", parent_cwd=tmp_path / "project",
            child_answers=2, monkeypatch=monkeypatch,
        )
        reads = store.parent_reads  # type: ignore[attr-defined]

        assert (await tool.execute(_delegate_args())).ok
        assert (await tool.execute(_delegate_args())).ok

        assert len(provider_impl.last_child_sessions) == 2
        assert reads == ["parent-once"], f"父 JSONL 被读了 {len(reads)} 次（应只读一次）"

    @pytest.mark.asyncio
    async def test_spawn_does_not_touch_the_parent_log(self, tmp_path: Path) -> None:
        """读父 cwd 是**只读**：不得 `Session.resume`（那会往父日志追 session/resumed）。

        只数 `read_events` 调用次数区分不了"读一次"与"读并 resume 一次"，
        所以这里直接比父 JSONL 的字节。
        """
        tool, provider_impl, _ = _spawn_setup(
            tmp_path, parent_id="parent-ro", parent_cwd=tmp_path / "project"
        )
        path = _events_path(tmp_path, "parent-ro")
        before = path.read_bytes()

        assert (await tool.execute(_delegate_args())).ok
        assert provider_impl.last_child_sessions, "子会话没建出来——本用例失去意义"
        assert path.read_bytes() == before, "父会话日志被写动了"

    @pytest.mark.asyncio
    async def test_reactivation_does_not_reuse_previous_parent_cwd(
        self, tmp_path: Path
    ) -> None:
        """`activate()` 承诺"覆盖"：换父会话后缓存必须作废。

        否则第二次激活后的子会话会继承**上一个**父的 cwd——比不继承更糟，
        它会把子会话挂到错误的项目组里。
        """
        store = _store(tmp_path)
        workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
        workspace_registry.create("parent-a", workspace_root=tmp_path / "proj-a")
        workspace_registry.create("parent-b", workspace_root=tmp_path / "proj-b")
        Session.start(store, session_id="parent-a", cwd=tmp_path / "proj-a")
        Session.start(store, session_id="parent-b", cwd=tmp_path / "proj-b")

        provider_impl = InProcessSubagentProvider()
        tool = DelegateTool(provider_impl)
        source_registry = ToolRegistry()
        source_registry.register(_Echo())

        def activate_for(parent_id: str) -> None:
            provider_impl.activate(
                factory=AgentFactory(
                    model=ScriptedModel([AIMessage(content="child ok")]),
                    primary_model_name="main-model",
                    executor_factory=ToolExecutor,
                ),
                source_registry=source_registry,
                session_store=store,
                workspace_registry=workspace_registry,
                parent_session_id=parent_id,
            )

        activate_for("parent-a")
        assert (await tool.execute(_delegate_args())).ok
        assert session_cwd(provider_impl.last_child_sessions[-1].events) == _canon(
            tmp_path / "proj-a"
        )

        activate_for("parent-b")
        assert (await tool.execute(_delegate_args())).ok
        assert session_cwd(provider_impl.last_child_sessions[-1].events) == _canon(
            tmp_path / "proj-b"
        ), "重复激活后仍继承上一个父会话的 cwd"

    @pytest.mark.asyncio
    async def test_read_failure_is_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """瞬时 I/O 故障不该把子会话永久钉成"未分组"：失败不写缓存，下次 spawn 重试。"""
        tool, provider_impl, store = _spawn_setup(
            tmp_path, parent_id="parent-flaky", parent_cwd=tmp_path / "project",
            child_answers=2,
        )
        original = store.read_events
        calls: list[str] = []

        def flaky(session_id: str):
            calls.append(session_id)
            raise OSError("transient")

        monkeypatch.setattr(store, "read_events", flaky)

        assert (await tool.execute(_delegate_args())).ok
        assert calls, "父会话 cwd 根本没被读取——本测试失去意义"
        assert session_cwd(provider_impl.last_child_sessions[-1].events) is None

        monkeypatch.setattr(store, "read_events", original)
        assert (await tool.execute(_delegate_args())).ok
        assert session_cwd(provider_impl.last_child_sessions[-1].events) == _canon(
            tmp_path / "project"
        ), "一次读失败被缓存成了 None（应下次重试）"
