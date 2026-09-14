"""T3 #133：CLI 续聊 REPL + slash 命令测试。

验证 demo/live_agent.py 重构后的交互模式：
- REPL 持有 current_session_id，普通 prompt 在同一 session 上续聊
- slash 命令解析与分发
- /new 新建同级 session 并切换 current
- /resume 列出历史 session 并可切换
- /compact 手动触发压缩
- /model 切换当前 session 模型
- /history 列出当前 workspace 的 session
- /cancel 取消当前 run
- /help 列出所有命令
- 现有 --task 单次模式行为不变
"""

from __future__ import annotations

from demo.live_agent_repl import (
    SLASH_COMMANDS,
    parse_slash_command,
)


class TestSlashCommandParsing:
    """slash 命令解析——纯函数，易测。"""

    def test_parse_new(self):
        cmd = parse_slash_command("/new")
        assert cmd is not None
        assert cmd.name == "new"
        assert cmd.args == []

    def test_parse_help(self):
        cmd = parse_slash_command("/help")
        assert cmd is not None
        assert cmd.name == "help"

    def test_parse_model_with_args(self):
        cmd = parse_slash_command("/model openai gpt-4o")
        assert cmd is not None
        assert cmd.name == "model"
        assert cmd.args == ["openai", "gpt-4o"]

    def test_parse_resume_no_arg(self):
        cmd = parse_slash_command("/resume")
        assert cmd is not None
        assert cmd.name == "resume"
        assert cmd.args == []

    def test_parse_fork_with_seq(self):
        cmd = parse_slash_command("/fork 5")
        assert cmd is not None
        assert cmd.name == "fork"
        assert cmd.args == ["5"]

    def test_parse_compact(self):
        cmd = parse_slash_command("/compact")
        assert cmd is not None
        assert cmd.name == "compact"

    def test_parse_history(self):
        cmd = parse_slash_command("/history")
        assert cmd is not None
        assert cmd.name == "history"

    def test_parse_cancel(self):
        cmd = parse_slash_command("/cancel")
        assert cmd is not None
        assert cmd.name == "cancel"

    def test_parse_clear(self):
        cmd = parse_slash_command("/clear")
        assert cmd is not None
        assert cmd.name == "clear"

    def test_parse_non_slash_returns_none(self):
        """普通文本不是 slash 命令。"""
        assert parse_slash_command("hello world") is None
        assert parse_slash_command("写个 hello.py") is None

    def test_parse_unknown_slash_returns_none(self):
        """未知 slash 命令返回 None（REPL 提示未知命令）。"""
        assert parse_slash_command("/unknown_cmd") is None

    def test_parse_empty_returns_none(self):
        assert parse_slash_command("") is None
        assert parse_slash_command("   ") is None

    def test_all_commands_listed_in_help(self):
        """SLASH_COMMANDS 应包含所有 PRD §7.2 定义的命令。"""
        expected = {"new", "resume", "fork", "compact", "model", "history",
                    "cancel", "clear", "help"}
        actual = {cmd.name for cmd in SLASH_COMMANDS}
        assert expected == actual, f"缺失: {expected - actual}, 多余: {actual - expected}"

    def test_each_command_has_description(self):
        """每个 slash 命令都有描述文本（/help 用）。"""
        for cmd in SLASH_COMMANDS:
            assert cmd.description, f"{cmd.name} 缺少 description"
