"""MCP server 连接生命周期（T2/T3，ADR-0012 决策 7；owner-task 模式）。

- 连接时机 = wiring 时（per-server 超时；仅约束连接建立，不约束工具调用——
  工具调用超时由 adapter 映射 Tool.timeout_seconds、Executor 统一执行，
  避免同一路径两层计时器）。
- 重连只恢复连接、不隐式重执行（Gate 2）：调用中 transport 死亡 → 本次调用
  失败；下次模型主动发起的调用先重连再执行（新调用 ≠ 重放旧调用）。
- 失败语义（Q10）：连接失败向 wiring 抛 MCPServerDownError（降级缺席）；
  协议层错误（MCPError）连接仍然存活，原样上抛。
- stdio 启动环境 = OS 必需项白名单 + 配置 env（第三方 server 不可信，
  不继承全量进程 env——C2 同款泄漏防线）。
- **owner-task 模式**（真实 server 验收抓到的修复）：stdio_client 等传输 CM
  内部持有 anyio cancel scope，在哪个任务进入就必须在哪个任务退出——
  wiring 任务 connect、shutdown 任务 aclose 的自然用法会触发 "Attempted to
  exit cancel scope in a different task"。因此 transport 生命周期归属一个
  专职 owner task：connect 启动它，aclose 只发停止信号；跨任务关闭变成
  事件通知，cancel scope 全部在 owner 任务内 LIFO 退出。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

import httpx2
from mcp import ClientSession, StdioServerParameters, types
from mcp.shared.exceptions import MCPError

try:  # HTTP transport（SDK 2.x）
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # pragma: no cover — SDK 老版本降级路径
    streamable_http_client = None  # type: ignore[assignment]

try:
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover
    stdio_client = None  # type: ignore[assignment]

from agent_harness.mcp.config import MCPServerConfig

logger = logging.getLogger(__name__)

#: stdio server 启动环境的 OS 必需项（与 LocalSubprocessSandbox 白名单同一原则；
#: MCP server 是第三方代码，继承全量 env 等于把部署机密钥喂给不可信进程）。
#: 如实声明：SDK stdio_client 自身会 union get_default_environment()（OS 基础项
#: 含 PROCESSOR_ARCHITECTURE 等）——有效 env = SDK 基础项 ∪ 本白名单 ∪ 配置项，
#: 三者都无凭据语义；本白名单的职责是挡住部署机配置的自定义变量。
MCP_STDIO_ENV_ALLOWLIST = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES",
    "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "USERNAME", "OS",
    "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM", "USER", "LOGNAME", "SHELL",
    "PYTHONIOENCODING", "PYTHONUTF8",
)


class MCPServerDownError(RuntimeError):
    """连接不可用（连接失败 / transport 死亡）——adapter 映射为失败结果。"""


class MCPCallError(RuntimeError):
    """协议层错误（server 拒绝：未知工具 / 非法参数等）——连接仍然存活。"""


def build_stdio_launch_env(config: MCPServerConfig) -> dict[str, str]:
    """stdio server 启动环境：白名单 + 配置 env（已展开），不继承全量 env。"""
    launch_env = {k: os.environ[k] for k in MCP_STDIO_ENV_ALLOWLIST if k in os.environ}
    launch_env.update(config.env)
    return launch_env


def build_http_client(config: MCPServerConfig) -> httpx2.AsyncClient:
    """为 http transport 构造带认证 headers 的 HTTP 客户端（SDK 2.x 把
    headers/auth 收敛到预配置的 httpx2 客户端；值已经过 parse 层 ${VAR} 展开）。

    read/write 不设上限：远端工具调用时长由 Tool.timeout_seconds（Executor
    统一执行）约束，双层超时只会产生更难归因的取消；连接与池化给保守上限。
    """
    return httpx2.AsyncClient(
        headers=dict(config.headers) if config.headers else None,
        timeout=httpx2.Timeout(timeout=None, connect=10.0, pool=30.0),
    )


class MCPServerConnection:
    """一个 MCP server 的连接生命周期（owner-task 模式，见模块 docstring）。"""

    def __init__(
        self,
        config: MCPServerConfig,
        *,
        session_factory: (Callable[[], Any] | None) = None,
    ) -> None:
        """session_factory：测试注入点——返回 async CM，yield 已初始化的
        ClientSession（绕过真实 transport）。生产路径按 transport 走 stdio/http。"""
        self._config = config
        self._session_factory = session_factory
        self._session: ClientSession | None = None
        self._owner_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._setup_error: BaseException | None = None
        self.connected = False
        # lifecycle 串行锁：connect / reconnect / aclose 的 停止→重建 序列必须
        # 原子——并发交叉（READ_ONLY gather 下 transport 死亡是自然场景）会产出
        # connected=True 但 _session=None 的楔死态（见 call_tool 前置检查）。
        self._lifecycle = asyncio.Lock()

    async def connect(self) -> None:
        """建立并初始化会话（wiring 时调用；幂等）。失败抛 MCPServerDownError。

        per-server 超时覆盖**整个建立阶段**（等待 owner 完成传输启动 +
        initialize）——挂死的 server 进程/端点在 connect 这一步就会被掐断。
        工具调用超时不在这里（Executor 经 Tool.timeout_seconds 统一执行）。
        """
        async with self._lifecycle:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        if self.connected:
            return
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._setup_error = None
        self._owner_task = asyncio.create_task(
            self._run_owner(), name=f"mcp-owner-{self._config.name}"
        )
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                await self._ready.wait()
        except asyncio.CancelledError:
            # 调用方取消（如请求断连打断首次懒连接）：owner 多半还停在建立
            # 阶段（慢 npx spawn），_stop 只在建立完成后才被观察——不回收就
            # 泄漏 owner task 与 stdio 子进程。尽力收尾后继续向上传播取消。
            self._stop.set()
            try:
                await asyncio.shield(self._reap_owner())
            except BaseException:  # 收尾尽力而为，取消必须继续传播
                logger.debug("connect 取消路径的 owner 收尾未完成（忽略）", exc_info=True)
            raise
        except TimeoutError:
            self._stop.set()
            await self._reap_owner()
            raise MCPServerDownError(
                f"server '{self._config.name}' 连接失败: TimeoutError "
                f"（建立阶段超过 {self._config.timeout_seconds}s）"
            )
        if self._setup_error is not None:
            await self._reap_owner()
            raise MCPServerDownError(
                f"server '{self._config.name}' 连接失败: {self._setup_error}"
            ) from self._setup_error
        self.connected = True

    async def _run_owner(self) -> None:
        """owner task：进入传输 CM → initialize → 待命；stop 置位后统一退出。

        全部 CM 的进入与退出都发生在本任务内（anyio cancel scope 合规）。
        """
        self._setup_error = None
        try:
            async with AsyncExitStack() as stack:
                if self._session_factory is not None:
                    session = await stack.enter_async_context(self._session_factory())
                elif self._config.transport == "stdio":
                    assert self._config.command is not None
                    params = StdioServerParameters(
                        command=self._config.command,
                        args=list(self._config.args),
                        env=build_stdio_launch_env(self._config),
                        cwd=self._config.cwd,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))  # type: ignore[misc]
                    session = await stack.enter_async_context(ClientSession(read, write))
                else:
                    assert self._config.url is not None
                    if streamable_http_client is None:  # pragma: no cover
                        raise MCPServerDownError("SDK 缺少 streamable HTTP transport")
                    http_client = build_http_client(self._config)
                    stack.push_async_callback(http_client.aclose)
                    read, write = await stack.enter_async_context(
                        streamable_http_client(self._config.url, http_client=http_client)  # type: ignore[misc]
                    )
                    session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as error:  # noqa: BLE001 — 建立期任何失败装箱上交
            if not self._ready.is_set():
                self._setup_error = error
                self._ready.set()
            # 运行期死亡（transport 断开）由 call_tool 侧发现并处理

    async def _reap_owner(self) -> None:
        task, self._owner_task = self._owner_task, None
        self._session = None
        if task is None or task.done():
            return
        self._stop.set()
        if self._ready.is_set():
            # owner 已建立完成、待命在 _stop.wait()：优雅退出窗口有效。
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except BaseException:  # noqa: BLE001 — 收尾路径：超时/取消/任意 owner 异常
                await self._hard_cancel_owner(task)
        else:
            # owner 还停在建立阶段（慢 npx spawn / 挂死的 initialize）：_stop
            # 只在建立完成后才被观察，优雅等待是纯死等——立即硬取消。CM 退出
            # 仍发生在 owner 任务内（anyio cancel scope 合规）。
            await self._hard_cancel_owner(task)
        # 收尾的 BaseException 捕获会吞掉等待期间到达的外部取消；这里把它还给
        # 调用方——取消中的任务不得继续跑后续流程（例如再发起一轮 connect）。
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError

    @staticmethod
    async def _hard_cancel_owner(task: asyncio.Task) -> None:
        """硬取消 owner 并等待其退出；退出噪声只落日志。"""
        task.cancel()
        try:
            await task
        except BaseException:  # 硬取消后的任意退出形状都不上抛
            logger.debug(
                "MCP owner task 硬取消后仍有退出噪声（已忽略）", exc_info=True,
            )

    async def reconnect(self) -> None:
        """恢复连接（不重执行任何历史调用）。

        停止→重建整体持锁：并发 reconnect / aclose 交叉会让后到者的 aclose
        拆掉先到者刚建好的 owner，最终停在 connected=True 但 _session=None。
        """
        async with self._lifecycle:
            await self._aclose_locked()
            await self._connect_locked()

    async def list_tools(self) -> list[types.Tool]:
        """discovery：tools/list。要求已连接。"""
        session = self._require_session()
        return (await session.list_tools()).tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        """执行远程工具；transport 死亡 → 标记断开 + MCPServerDownError。

        协议层 MCPError（未知工具/非法参数）连接仍存活，包成 MCPCallError 上抛。
        下次调用若已断开（或处于会话丢失的楔死态）：先重连（恢复连接），再执行
        本次模型主动发起的调用。
        """
        if not self.connected or self._session is None:
            await self.reconnect()
        session = self._require_session()
        try:
            return await session.call_tool(name, arguments or {})
        except asyncio.CancelledError:
            raise
        except MCPError as error:
            raise MCPCallError(
                f"server '{self._config.name}' 拒绝调用 {name!r}: {error}"
            ) from error
        except BaseException as error:
            # transport/协议框架死亡（ClosedResourceError 等）→ 连接标记断开；
            # 本次调用失败，下次调用重连。
            self.connected = False
            raise MCPServerDownError(
                f"server '{self._config.name}' transport failure during call {name!r}: "
                f"{type(error).__name__}"
            ) from error

    async def aclose(self) -> None:
        """关闭连接：发停止信号，owner task 在自己的任务内退出全部 CM。"""
        async with self._lifecycle:
            await self._aclose_locked()

    async def _aclose_locked(self) -> None:
        self.connected = False
        self._session = None
        self._stop.set()
        await self._reap_owner()

    def _require_session(self) -> ClientSession:
        if not self.connected or self._session is None:
            raise MCPServerDownError(f"server '{self._config.name}' 未连接")
        return self._session
