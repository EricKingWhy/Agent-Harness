"""`sandbox.paths` 的形态判定契约（#170 批次抽出的 `is_absolute_path`）。

为什么单独锁这个小函数：它是 `POST /api/sessions`（`cwd`）、`POST /api/projects`、
`GET /api/host/dirs` 三处"realpath 之前的形态闸"的**唯一**实现。原先三处各写一遍
`PureWindowsPath(value).is_absolute()`——在 POSIX 上把合法绝对路径（`/home/x`，无
drive → False）一律拒掉。

跨平台锁是第一条用例（断言"当前平台自己的绝对路径必须被接受"）：它在 Windows 与
POSIX 上都必须绿；在 POSIX 上跑时，它正是那个缺陷的红灯。第三条只把**缺陷机制**
文档化（`PureWindowsPath("/home/x").is_absolute()` 为 False）——不假装在 Windows 上
模拟 POSIX 分支：`os.path` 在 Windows 上绑定的是 `ntpath`，模拟出来的不是真语义。
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from agent_harness.sandbox.paths import is_absolute_path


def test_accepts_current_platform_absolute_path(tmp_path: Path) -> None:
    """当前平台自己的绝对路径必须被接受（POSIX 上这是原缺陷的回归锁）。"""
    assert is_absolute_path(str(tmp_path)) is True
    assert is_absolute_path(str(tmp_path / "sub")) is True


def test_rejects_relative_and_blank_values() -> None:
    for value in ("relative/dir", "a", "", "   ", "./x", "../x"):
        assert is_absolute_path(value) is False, value


def test_documented_defect_mechanism_pure_windows_path_rejects_posix_input() -> None:
    """缺陷机制（可执行文档）：`PureWindowsPath` 对 POSIX 绝对路径判 False（无 drive）。

    据此可推：`if not PureWindowsPath(v).is_absolute(): raise` 在 POSIX 上会拒掉一切合法
    绝对路径。所以形态闸必须按平台分支（`os.name == "nt"` → `PureWindowsPath`，否则
    `os.path.isabs`）。Windows 侧另有一条既有事实：`/home/x` 是"有根无盘符"的歧义形态，
    判 False 是**有意**的（见 helper docstring），别为了"通用"改成 `os.path.isabs`——
    那会接受歧义形态并静默锚到当前盘根。
    """
    assert PureWindowsPath("/home/user/proj").is_absolute() is False
    assert PureWindowsPath("/").is_absolute() is False
