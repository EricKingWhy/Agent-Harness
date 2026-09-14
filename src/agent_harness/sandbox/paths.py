"""Workspace 路径的**唯一**规范化入口（WS-1 / issue #151 AC5）。

会话侧锚（`session/started` 的 `cwd`）与 `WorkspaceRegistry` 映射文件里的
`workspace_root` 是同一个物理目录的**两个写入点**。若两处各自规范化，同名目录
在尾部斜杠、`.`/`..`、符号链接等写法差异下会产出**不同字符串**，于是"同一路径"
被当成两个——成员资格校验的结果就会随写入点漂移。故规范化只此一处，两处都调它。
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


def canonical_workspace_path(path: str | Path) -> str:
    """→ 规范化绝对路径（`fs.realpath` 语义）。

    解析尾部斜杠、`.`/`..`、以及**符号链接/junction**（`D:\\a\\b\\`、
    `D:\\a\\..\\a\\b`、指向 `b` 的链接三者产出同一字符串）。

    `realpath` 只解析**已存在**的链接；路径里不存在的段只能做词法归一。链接能不能
    被解析取决于它本身在不在，**不取决于本函数之前是否 mkdir**——`WorkspaceRegistry
    .create` 先建目录是它原本就要做的事（确保 workspace 目录存在），规范化紧随其后，
    两者没有因果依赖。
    """
    return os.path.realpath(os.fspath(path))


def is_absolute_path(value: str) -> bool:
    """用户提供的路径是不是**本平台**的绝对路径（形态判定，不 touch 文件系统）。

    为什么不能统一用 `PureWindowsPath(...).is_absolute()`（本仓曾有三处这样写）：
    `PureWindowsPath("/home/user/proj")` 的 `drive` 为空 → `is_absolute()` 为 **False**，
    于是 POSIX 上任何合法绝对路径都被判成相对路径、被 422 拒掉（`C:\\x` 在 POSIX 上
    的真实错误应该是"不存在"，不是"不是绝对路径"）。反之，用 `os.path.isabs` 判
    Windows 路径也不对：`os.path.isabs("\\\\foo")` 为 True（有根无盘符，**盘符相关**），
    接受它会把一次歧义路径变成"当前盘根 + foo"的静默锚定。

    所以按平台分支——各平台只接受自己那套绝对形态（Windows 仍要求盘符 + 根，与
    `_validate_workspace_name` / `_require_absolute_path` 的既有口径逐字一致）。

    **必须在任何 `realpath` / `exists` 之前调用**：`os.path.realpath("relative/x")` 会
    按进程当前工作目录解析，把一次笔误变成"落在服务器碰巧启动的目录"。
    """
    if os.name == "nt":
        return PureWindowsPath(value).is_absolute()
    return os.path.isabs(value)
