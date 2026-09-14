"""MCP 连接生命周期（T2）：连接/断开标记/重连不重执行/stdio 启动环境白名单。"""

import asyncio
from contextlib import asynccontextmanager

import pytest
from anyio import ClosedResourceError

from agent_harness.mcp import MCPServerConfig
from agent_harness.mcp.client import (
    MCPCallError,
    MCPServerConnection,
    MCPServerDownError,
    build_stdio_launch_env,
)


def _config(**overrides) -> MCPServerConfig:
    base = {"name": "fake", "transport": "stdio", "command": "npx", "args": ["x"]}
    base.update(overrides)
    return MCPServerConfig.model_validate(base)


class _ScriptedSession:
    """可脚本化的假 ClientSession：call 行为按队列弹出。"""

    def __init__(self, behaviors: list):
        self._behaviors = list(behaviors)

    async def initialize(self) -> None:
        return None

    async def list_tools(self):
        from mcp import types
        return types.ListToolsResult(tools=[])

    async def call_tool(self, name, arguments):
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior


def _factory(sessions: list[_ScriptedSession]):
    """session_factory 替身：按序 yield 脚本化会话，记录调用次数。"""
    state = {"count": 0}

    @asynccontextmanager
    async def factory():
        state["count"] += 1
        yield sessions[min(state["count"] - 1, len(sessions) - 1)]

    factory.state = state
    return factory


@pytest.mark.asyncio
async def test_connect_via_session_factory_and_list_tools():

    session = _ScriptedSession([])
    factory = _factory([session])
    conn = MCPServerConnection(_config(), session_factory=factory)
    await conn.connect()
    assert conn.connected is True

    session.list_tools = _fake_list_tools
    tools = await conn.list_tools()
    assert tools == []
    await conn.aclose()
    assert conn.connected is False


async def _fake_list_tools(self=None):
    from mcp import types
    return types.ListToolsResult(tools=[])


@pytest.mark.asyncio
async def test_connect_failure_raises_down_error_and_cleans_up():
    @asynccontextmanager
    async def broken_factory():
        raise RuntimeError("process failed to start")
        yield None

    conn = MCPServerConnection(_config(), session_factory=broken_factory)
    with pytest.raises(MCPServerDownError, match="fake"):
        await conn.connect()
    assert conn.connected is False


@pytest.mark.asyncio
async def test_connect_timeout_is_bounded_by_server_config():
    import asyncio

    @asynccontextmanager
    async def hanging_factory():
        await asyncio.Event().wait()  # 永不就绪
        yield None

    conn = MCPServerConnection(_config(timeout_seconds=0.1), session_factory=hanging_factory)
    with pytest.raises(MCPServerDownError):
        await conn.connect()


@pytest.mark.asyncio
async def test_transport_death_marks_disconnected_then_error():
    """transport 死亡 → 本次调用 MCPServerDownError + 连接标记断开。"""
    dead_session = _ScriptedSession([ClosedResourceError("pipe closed")])
    factory = _factory([dead_session])
    conn = MCPServerConnection(_config(), session_factory=factory)
    await conn.connect()

    with pytest.raises(MCPServerDownError, match="transport failure"):
        await conn.call_tool("echo", {"text": "hi"})
    assert conn.connected is False
    # 死掉的调用没有被执行第二次（dead session 的 behavior 只被消费一次）
    assert len(dead_session._behaviors) == 0


@pytest.mark.asyncio
async def test_reconnect_restores_connection_without_reexecuting():
    """重连恢复连接；新调用在新连接上执行——失败的旧调用不被重放（Gate 2）。"""
    dead_session = _ScriptedSession([ClosedResourceError("pipe closed")])
    from mcp import types
    live_session = _ScriptedSession([
        types.CallToolResult(content=[types.TextContent(type="text", text="ok")], is_error=False),
    ])
    factory = _factory([dead_session, live_session])
    conn = MCPServerConnection(_config(), session_factory=factory)
    await conn.connect()

    with pytest.raises(MCPServerDownError):
        await conn.call_tool("echo", {"text": "hi"})

    # 下一次模型主动调用：先重连（factory 第 2 次被调用），再执行
    result = await conn.call_tool("echo", {"text": "hi"})
    assert result.is_error is False
    assert factory.state["count"] == 2
    # 旧会话只剩一个已消费的失败行为——旧调用没有被重放
    assert len(dead_session._behaviors) == 0


@pytest.mark.asyncio
async def test_protocol_error_keeps_connection_alive():
    """McpError（server 拒绝：未知工具等）连接仍存活——只包装不上报断开。"""
    from mcp.shared.exceptions import MCPError

    session = _ScriptedSession([MCPError(0, "unknown tool")])
    factory = _factory([session])
    conn = MCPServerConnection(_config(), session_factory=factory)
    await conn.connect()

    with pytest.raises(MCPCallError, match="拒绝调用"):
        await conn.call_tool("ghost", {})
    assert conn.connected is True, "协议错误不应标记连接死亡"


def test_stdio_launch_env_allowlisted(monkeypatch):
    """C2 同款防线：stdio server 启动 env = 白名单 + 配置项，不继承全量。"""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("MY_API_KEY", "secret")
    config = _config(env={"GITHUB_TOKEN": "gh-tok"})  # 展开由 parse 层完成

    launch_env = build_stdio_launch_env(config)

    assert launch_env["PATH"] == "/usr/bin"
    assert launch_env["GITHUB_TOKEN"] == "gh-tok"  # 配置显式传入
    assert "MY_API_KEY" not in launch_env, "部署机密钥不得泄漏给第三方 server"


# ── T3：Streamable HTTP transport（本地真实回路）──


@pytest.mark.asyncio
async def test_http_transport_round_trip(tmp_path):
    """http transport 走真实 Streamable HTTP（SDK streamable_http_app + uvicorn）：
    连接 → discovery → 调用 → 断开全链路。"""
    import asyncio as _asyncio

    import uvicorn

    from tests.mcp_client.fake_server import FakeMCPServer, make_fake_tool

    fake = FakeMCPServer(tools=[make_fake_tool("http_echo")])
    app = fake._server.streamable_http_app()
    # lifespan 必须开：streamable_http_app 的 SessionManager 在 lifespan 中初始化
    uv_config = uvicorn.Config(app, host="127.0.0.1", port=0,
                               log_level="error", lifespan="on")
    uv_server = uvicorn.Server(uv_config)
    serve_task = _asyncio.create_task(uv_server.serve())
    try:
        for _ in range(100):
            if uv_server.started:
                break
            await _asyncio.sleep(0.05)
        assert uv_server.started, "uvicorn 未能在预期时间内启动"
        port = uv_server.servers[0].sockets[0].getsockname()[1]

        config = MCPServerConfig(name="remote", transport="http",
                                 url=f"http://127.0.0.1:{port}/mcp")
        conn = MCPServerConnection(config)
        await conn.connect()
        tools = await conn.list_tools()
        assert [t.name for t in tools] == ["http_echo"]
        result = await conn.call_tool("http_echo", {"text": "x"})
        assert result.is_error is False
        await conn.aclose()
        assert conn.connected is False
    finally:
        uv_server.should_exit = True
        serve_task.cancel()
        try:
            await serve_task
        except _asyncio.CancelledError:
            pass


# ── 真实 server 验收抓到的 anyio 跨任务 bug 回归钉（owner-task 模式）──


@pytest.mark.asyncio
async def test_aclose_from_different_task_does_not_crash(tmp_path):
    """transport CM（内部持有 anyio cancel scope）在 owner 任务内进入；
    aclose 从另一个任务调用不得触发 'exit cancel scope in a different task'
    ——真实 Context7 server 验收时在旧实现上必现。"""
    import anyio

    @asynccontextmanager
    async def scoped_factory():
        # 模拟 stdio_client：CM 内部使用 anyio cancel scope
        with anyio.CancelScope():
            yield _ScriptedSession([])

    conn = MCPServerConnection(_config(), session_factory=scoped_factory)
    await conn.connect()
    assert conn.connected is True

    closer = asyncio.create_task(conn.aclose())  # 另一个任务关闭
    await asyncio.wait_for(closer, timeout=10)  # 不得抛 RuntimeError
    assert conn.connected is False


@pytest.mark.asyncio
async def test_owner_setup_failure_does_not_leak_task():
    """建立失败的 owner task 必须被回收，不留悬挂任务。"""
    before = {t.get_name() for t in asyncio.all_tasks()}

    @asynccontextmanager
    async def broken_factory():
        raise RuntimeError("spawn failed")
        yield None

    conn = MCPServerConnection(_config(), session_factory=broken_factory)
    with pytest.raises(MCPServerDownError):
        await conn.connect()
    after = {t.get_name() for t in asyncio.all_tasks() if not t.done()}
    assert not any("mcp-owner-fake" in n for n in after - before), "owner task 泄漏"


# ── Round 9 审计修复回归钉：lifecycle 串行化 + 取消路径收尾 ──


@pytest.mark.asyncio
async def test_wedge_state_recovers_via_reconnect():
    """楔死态（connected=True 但 _session=None，并发 lifecycle 交叉的产物）
    必须自愈：下次调用重连成功，而不是永远 MCPServerDownError。"""
    live_session = _ScriptedSession([])
    factory = _factory([live_session])
    conn = MCPServerConnection(_config(), session_factory=factory)
    await conn.connect()
    # 模拟并发 connect/aclose 交叉后的楔死态：标记存活但会话已丢
    conn.connected = True
    conn._session = None
    # 重连拿到的"新"会话（factory 按序复用最后一个）要能成功执行本次调用
    from mcp import types
    live_session._behaviors.append(types.CallToolResult(
        content=[types.TextContent(type="text", text="ok")], is_error=False))

    result = await conn.call_tool("echo", {"text": "hi"})
    assert result.is_error is False
    assert factory.state["count"] == 2, "楔死态必须触发重连（新会话）"


@pytest.mark.asyncio
async def test_concurrent_reconnect_serialized():
    """并发 reconnect（READ_ONLY gather + transport 死亡的自然场景）串行完成：
    各自恰好一次 停止→重建，终态可用，不出楔死。"""
    from mcp import types

    dead_session = _ScriptedSession([ClosedResourceError("pipe closed")])
    sessions = [
        _ScriptedSession([types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")], is_error=False)])
        for _ in range(3)
    ]
    factory = _factory([dead_session, *sessions])
    conn = MCPServerConnection(_config(), session_factory=factory)
    await conn.connect()

    await asyncio.gather(conn.reconnect(), conn.reconnect())
    assert conn.connected is True and conn._session is not None
    assert factory.state["count"] == 3, "每个 reconnect 恰好一次重建"
    result = await conn.call_tool("echo", {"text": "hi"})
    assert result.is_error is False


@pytest.mark.asyncio
async def test_connect_cancellation_reaps_owner():
    """connect 等待中调用方被取消：owner task 必须被回收（挂死的传输 CM
    回卷）——只 _stop.set() 够不到还停在建立阶段的 owner，会泄漏子进程。"""
    exited: list[bool] = []

    @asynccontextmanager
    async def hanging_factory():
        try:
            await asyncio.Event().wait()  # 挂在建立阶段（慢 npx spawn 的替身）
            yield None
        finally:
            exited.append(True)

    conn = MCPServerConnection(_config(), session_factory=hanging_factory)
    task = asyncio.create_task(conn.connect())
    await asyncio.sleep(0.05)  # 让 owner 进入挂死的建立阶段
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    assert conn._owner_task is None, "取消路径必须回收 owner task"
    assert exited, "挂死的传输 CM 必须被回卷（否则 stdio 子进程泄漏到进程退出）"


@pytest.mark.asyncio
async def test_aclose_cancellation_is_not_swallowed():
    """reap 吞不得调用方取消：取消中的 aclose 必须以 CancelledError 结束，
    否则取消里的 handler 会继续跑下一轮 connect（取消延迟一整个重连周期）。"""
    exit_gate = asyncio.Event()

    @asynccontextmanager
    async def slow_exit_factory():
        yield _ScriptedSession([])
        await exit_gate.wait()  # 模拟 server 子进程退出挂死

    conn = MCPServerConnection(_config(), session_factory=slow_exit_factory)
    await conn.connect()
    closer = asyncio.create_task(conn.aclose())
    await asyncio.sleep(0.1)  # closer 进入 reap 的优雅等待
    closer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(closer, timeout=6)
