"""Sandbox 抽象契约：Coding Tool 的隔离执行环境。

Sandbox 是 Runtime 安全边界而非 Prompt 约束（ADR-0001）：模型即使尝试访问
workspace 外的路径，Sandbox 也会拒绝。它定义了 read / write / bash 等 Coding Tool
运行的唯一接口，具体后端（本机子进程 / Docker 容器）实现这一契约。

ExecResult 是 Sandbox 层的原生返回，不感知 ToolResult——Tool 层负责映射。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ShellFamily(str, Enum):
    """解释器家族——决定**语法能力**，而不只是名字（OBS-012 深化）。

    为什么是 str Enum：与 `ToolSideEffect` / `ErrorCode` 同理，日志可读、可序列化。

    只有真的会被区分对待的家族：`BASH`（不能否认自己是 bash）、`CMD`（cmd.exe
    专有陷阱）、`POSIX_SH`（其余 POSIX 兼容 sh 的保守归类）。刻意不加 `UNKNOWN`——
    没有消费者的枚举值是投机抽象；后端未覆写时基类默认就是 POSIX sh，与它声明的
    名字 `sh` 自洽。
    """

    POSIX_SH = "posix_sh"
    BASH = "bash"
    CMD = "cmd"


@dataclass(frozen=True)
class ShellEnvironment:
    """该后端执行 `command` 时**实际**使用的解释器事实。

    `name` 是模型可见的解释器名，`family` 决定语法能力。两者**必须一起声明**——
    这正是本类型存在的理由：只给名字时，消费方（`BashTool`）只能靠
    `"cmd" in name` 子串嗅探重新推导行为，等于把 Sandbox 一侧的知识漏过了 seam；
    而「名字是 cmd.exe、家族却按 POSIX 处理」这种静默不一致在只给名字的接口下
    根本无法表达。
    """

    name: str
    family: ShellFamily


@dataclass(frozen=True)
class ExecResult:
    """Sandbox 执行一条 shell 命令后的原生结果。

    Sandbox 不返回 ToolResult（那是 Tool 层的语义），只返回执行事实：
    exit_code 是 shell 命令的真实退出码（非零 = 命令业务失败，但 Sandbox 调用本身成功）。
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = field(default=0.0)
    # 协作取消（R7-1/C1）：进程因取消信号被整树击杀时置 True——
    # 上层（Tool/Ledger）据此区分"自然结束"与"被取消（副作用未知）"。
    cancelled: bool = field(default=False)


class Sandbox(ABC):
    """Coding Tool 的隔离执行环境契约。

    6 个方法一次定全（ADR-0001），即使某后端暂时用不到某个方法也在基类里声明，
    避免未来加后端时改契约（破坏性变更）。

    workspace 路径边界由 Sandbox 统一强制（ADR-0001 / Q11(a)）：
    所有接受路径的方法把传入路径 resolve 后校验是否在 workspace 内，越界抛 PermissionError。
    """

    @abstractmethod
    def ensure_started(self) -> None:
        """惰性启动执行环境。幂等：多次调用不报错。

        LocalSubprocess 是 no-op（进程总在）；Docker 起容器。
        """

    @abstractmethod
    def exec(self, command: str, *, timeout: float | None = None,
             cancel_event: threading.Event | None = None,
             on_output: Callable[[str, str], None] | None = None) -> ExecResult:
        """执行 shell 命令，返回 ExecResult。

        timeout 为秒；None 表示用后端默认值。超时行为由后端决定。
        cancel_event 是协作取消钩子（C1）：置位后后端必须尽快击杀进程树并返回
        cancelled=True 的结果——asyncio 超时/断连只能取消 await，杀不掉已经
        跑起来的子进程，没有这个钩子，"超时返回"之后命令还会继续改 workspace。
        on_output 是输出流回调（ADR-0016 §4.2）：后端支持时按读取进度以
        (channel, text) 逐段回调（channel ∈ {"stdout", "stderr"}），在【任意
        线程】调用——调用方负责线程安全。None = 不需要流式（默认，零开销）；
        后端不支持流式时可接受并忽略（如 Docker V1）。
        """

    @abstractmethod
    def list_files(self, pattern: str) -> list[str]:
        """枚举 workspace 内匹配 glob 模式的文件，返回 workspace 相对路径列表。

        - 仅返回文件，不返回目录。
        - 相对路径用 POSIX 风格（正斜杠），按路径排序。
        - pattern 为空字符串或 "*" 时返回 workspace 内所有文件。
        - 越界访问（pattern 解析出 workspace 外）抛 PermissionError。

        这是 grep / glob Coding Tool 跨后端枚举文件的唯一可移植入口；
        LocalSubprocessSandbox 用 os.walk，DockerSandbox 用 exec("find")。
        """

    @abstractmethod
    def read_text(self, path: str) -> str:
        """读 workspace 内文件，返回文本。路径越界抛 PermissionError。"""

    @abstractmethod
    def write_text(self, path: str, content: str) -> None:
        """覆盖写 workspace 内文件。路径越界抛 PermissionError。"""

    @abstractmethod
    def copy_in(self, host_path: Path, workspace_path: str) -> None:
        """把宿主文件拷入 workspace 内指定位置。

        LocalSubprocess 用文件复制到 workspace 目录；Docker 用 docker cp。
        workspace_path 越界抛 PermissionError。
        """

    @abstractmethod
    def stop(self) -> None:
        """停止 Sandbox（保留持久状态以便 resume）。幂等：多次调用不报错。

        语义：停容器/进程，但不删 workspace 数据/Volume——下次 ensure_started 可恢复。
        对无持久化需要的后端（LocalSubprocess）可以是 no-op。
        """

    @abstractmethod
    def delete(self) -> None:
        """彻底清理 Sandbox 资源（容器 + Volume + workspace 目录）。幂等。

        语义：完全销毁，不可 resume。WorkspaceRegistry.delete() 调它。
        对 LocalSubprocess，删除 workspace_root 目录；对 Docker，移除容器和 Volume。
        """

    # —— 路径安全工具（具体方法，子类复用） ——

    def resolve_within_workspace(self, path: str) -> Path:
        """把传入路径 resolve 成 workspace 内绝对路径，越界抛 PermissionError。

        这是 ADR-0001 路径边界的唯一强制点：所有子类接受路径的方法都先调它。

        **公开**（原 `_resolve_within_workspace`，#191）：Web 层也需要"只校验、不读"这一动作
        ——`GET .../workspace/git/status|diff` 的 pathspec 要先过边界才能交给 git。
        与其在 web 层再写一份路径校验（ADR-0001 明确只该有一处），不如把边界本身公开。
        调用方拿到的是**解析后的绝对路径**；只想校验时忽略返回值即可。
        """
        workspace = self.workspace_root
        resolved = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if not resolved.is_relative_to(workspace):
            raise PermissionError(
                f"路径 '{path}' 解析为 '{resolved}'，越出 workspace '{workspace}' 边界，拒绝访问"
            )
        return resolved

    @property
    @abstractmethod
    def workspace_root(self) -> Path:
        """workspace 根目录的绝对路径（路径边界的基准）。"""

    # —— 执行环境事实（供模型可见的工具描述声明真相） ——

    @property
    def shell_environment(self) -> ShellEnvironment:
        """该后端执行 `command` 时的**实际**解释器事实（名 + 家族）。

        OBS-012：`BashTool` 的名字叫 bash，但**没有任何后端真的用 bash**——
        LocalSubprocessSandbox 走 `subprocess` 的平台默认（POSIX = `/bin/sh`，
        Windows = `cmd.exe`），DockerSandbox 硬编码 `["/bin/sh", "-lc", command]`。
        模型按工具名以为是 bash，就会写出该解释器不认的语法（本机实证：cmd.exe 对
        bash 语法报「此时不应有 i。」）。工具描述据此声明真相——**不要**让 Tool 层
        自己用 `os.name` 猜：宿主是 Windows 时 Docker 容器内仍是 sh。

        非抽象（**不并入 ADR-0001 冻结的 6 个抽象方法契约**，避免破坏既有/第三方后端
        实现）：基类给保守的 POSIX sh 默认，子类应覆写为真实解释器 + 家族。
        未覆写的第三方后端会得到 POSIX sh 行为——这是非抽象默认的固有代价，
        已在此声明；两个具体后端都覆写。
        """
        return ShellEnvironment(name="sh", family=ShellFamily.POSIX_SH)
