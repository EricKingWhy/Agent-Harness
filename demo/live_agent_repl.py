"""T3 #133：CLI 续聊 REPL + slash 命令。

重构 demo/live_agent.py 的交互模式：
- 进程持有 current_session_id，普通 prompt 在同一 session 上续聊
- slash 命令集（/new /resume /fork /compact /model /history /cancel /clear /help）
- 流式输出到终端，Ctrl+C 取消当前 run

设计原则（PRD §7）：
- REPL 持有 current_session_id
- 普通 prompt 调 SessionService.send_message(current_id, content)
- /new 显式新建同级 session 并切换 current
- 不再每条 _new_session()
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlashCommand:
    """slash 命令定义：name、description、usage。"""
    name: str
    description: str
    usage: str = ""


# PRD §7.2 定义的 9 个 slash 命令
SLASH_COMMANDS: list[SlashCommand] = [
    SlashCommand(
        name="new",
        description="显式新建同级 session 并切换 current",
        usage="/new",
    ),
    SlashCommand(
        name="resume",
        description="从历史 session 列表选一个继续",
        usage="/resume [session_id]",
    ),
    SlashCommand(
        name="fork",
        description="从当前/指定历史点派生新 session（省略 seq = 最近切点）",
        usage="/fork [from_seq]",
    ),
    SlashCommand(
        name="compact",
        description="手动触发压缩",
        usage="/compact",
    ),
    SlashCommand(
        name="model",
        description="切换当前 session 模型",
        usage="/model <provider> <model>",
    ),
    SlashCommand(
        name="history",
        description="列出当前 workspace 的 session",
        usage="/history",
    ),
    SlashCommand(
        name="cancel",
        description="取消当前在跑的 run",
        usage="/cancel",
    ),
    SlashCommand(
        name="clear",
        description="清屏（不删 session）",
        usage="/clear",
    ),
    SlashCommand(
        name="help",
        description="列出所有命令",
        usage="/help",
    ),
]

# 快速查找表
_COMMAND_NAMES: frozenset[str] = frozenset(cmd.name for cmd in SLASH_COMMANDS)


@dataclass(frozen=True)
class ParsedSlash:
    """解析后的 slash 命令：name + args 列表。"""
    name: str
    args: list[str] = field(default_factory=list)


def parse_slash_command(text: str) -> ParsedSlash | None:
    """解析用户输入是否为 slash 命令。

    返回 None 的情况：
    - 空字符串或纯空白
    - 不以 / 开头（普通文本）
    - 以 / 开头但不是已知命令（未知命令）

    返回 ParsedSlash(name, args) 的情况：
    - /new → ParsedSlash("new", [])
    - /model openai gpt-4o → ParsedSlash("model", ["openai", "gpt-4o"])
    """
    stripped = text.strip()
    if not stripped:
        return None
    if not stripped.startswith("/"):
        return None
    # 分割命令名和参数
    parts = stripped[1:].split()
    if not parts:
        return None
    cmd_name = parts[0]
    if cmd_name not in _COMMAND_NAMES:
        return None
    return ParsedSlash(name=cmd_name, args=parts[1:])


def format_help() -> str:
    """生成 /help 输出文本。"""
    lines = ["[bold cyan]Slash Commands[/bold cyan]\n"]
    for cmd in SLASH_COMMANDS:
        usage = cmd.usage if cmd.usage else f"/{cmd.name}"
        lines.append(f"  [yellow]{usage}[/yellow]")
        lines.append(f"    {cmd.description}")
    return "\n".join(lines)
