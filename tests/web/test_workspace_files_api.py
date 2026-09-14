"""#191：会话工作区的只读浏览 API（列文件 / 读文件 / git 状态 / 单文件 diff）。

票面（`docs/WORKSPACE_PANEL_PRD.md` §3.3 / §6 票 8，`WORKSPACE_PANEL_TICKETS.md` T8）：
「文件/改动」面当前只显示**本次会话改过的文件**（由事件推导）；本票补上"**看工作区的
实际内容**"这条供给面——列全部文件、读某个文件、看 git 状态与单文件 diff。

本文件的测法（为什么这样测）
----------------------------

- **边界用"真有那份文件"来证明**：越界用例会在 workspace **之外**真造一个文件，再断言
  读不到它。只断言"404/403"而外部文件不存在的话，一个"根本没去找"的实现也会绿。
- **路径越界的基准是 Sandbox（ADR-0001 的唯一强制点）**，不是本模块自己写的字符串校验；
  所以用例既覆盖相对穿越（`../../x`）也覆盖绝对路径指向外部。
- **平台差异如实登记**：把一个**目录**当文件读，POSIX 是 `IsADirectoryError`（422
  `不是文件`），win32 的 `open()` 对目录抛 `PermissionError`（403 `无权限访问`）。前者用
  确定性用例（替身 `read_text` 抛该异常）钉住映射，后者不强求同一状态码——两个都不是
  500，且文案各自如实。
- **git 语义不验证第二遍**：`git status --porcelain=v1` / `git diff [--staged]` 的语义由
  `tests/tools/test_git_tools.py` 钉住（同一个命令构造器），这里只断言"经 HTTP 走通 +
  命令确实由共享构造器拼出"。
- **不泄漏宿主绝对路径**：所有响应体都不该出现 workspace 的绝对根路径（工作区是相对
  浏览面，绝对路径是宿主信息）。

契约矩阵
--------

| 条件 | 结果 |
| --- | --- |
| `session_id` 形态非法 | 422（`InvalidSessionId`，与既有路由同一份校验） |
| 会话不存在 | 404（`SessionNotFound`） |
| 会话存在但无 workspace 映射 | 404（如实：不是"文件不存在"） |
| `offset` < 1 / `limit` 越界 | 422 |
| 路径越出 workspace（相对穿越或绝对路径） | 403（Sandbox `PermissionError`） |
| 文件不存在 | 404 `文件不存在：<path>` |
| 目标是目录（POSIX 路径） | 422 `不是文件：<path>` |
| 内容不是 UTF-8 文本 | 415（不支持该媒体类型，不伪造文本） |
| git 命令退出码非零（如不是 git 仓库） | 200 + 如实 `exit_code`/`stderr`（ADR-0002） |
| 来源不可信（跨源 Origin） | 403（`require_trusted_origin`，ADR-0028 D2 同一份） |
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.config import Settings
from agent_harness.web.app import create_app
from tests.scripted_model import ScriptedModel

if TYPE_CHECKING:
    from agent_harness.sandbox import Sandbox

_DATA_PREFIX = "data:"

#: 四个路由的公共前缀（会话工作区）。
_PREFIX = "/api/sessions/{sid}/workspace"


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        **overrides,
    )
    return TestClient(create_app(settings, enable_cors=False))


def _create_session(client: TestClient) -> str:
    """建一个真会话（真 runtime + 替身模型），返回 session_id。

    与 `test_artifacts_api.py` 同一口径：会话是**真建**的，于是 workspace 映射也是真的
    ——边界用例才有意义（对着替身 workspace 断言越界，测不出任何东西）。
    """
    with patch(
        "agent_harness.assembly.create_chat_model",
        return_value=ScriptedModel(responses=[AIMessage(content="ok")]),
    ):
        resp = client.post("/api/sessions", json={"task": "hi", "max_steps": 1})
    assert resp.status_code == 200, resp.text
    frames = [
        json.loads(line[len(_DATA_PREFIX):].strip())
        for line in resp.text.splitlines()
        if line.startswith(_DATA_PREFIX)
    ]
    session_id = next((f["session_id"] for f in frames if f.get("session_id")), None)
    assert session_id, f"SSE 流里没有 session_id：{frames[:3]}"
    return str(session_id)


def _sandbox(client: TestClient, session_id: str) -> Sandbox:
    """拿到会话**真实**的 sandbox（映射里的那一个）。"""
    return client.app.state.agent.workspace_registry.get(session_id)


def _root(client: TestClient, session_id: str) -> Path:
    return Path(_sandbox(client, session_id).workspace_root)


def _seed(root: Path, rel: str, content: str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    return target


def _outside_file(root: Path, tmp_path: Path) -> Path:
    """在 workspace **之外**造一个真文件，返回可由 root 相对穿越到的路径。

    位置由 `tmp_path` 定（而不是硬编码 `../x`）：workspace 的实际布局是实现细节，
    硬编码相对段会在布局变化时静默变成"文件不存在"——那正是本文件要避免的假绿。
    """
    outside = tmp_path / "outside-of-workspace.txt"
    outside.write_text("OUTSIDE-SECRET\n", encoding="utf-8")
    assert not outside.is_relative_to(root), "测试自身前提被破坏：外部文件落在了 workspace 里"
    return outside


def _url(session_id: str, suffix: str) -> str:
    return _PREFIX.replace("{sid}", session_id) + suffix


# ── AC1：列工作区文件 ──


def test_lists_files_as_sorted_relative_posix_paths(tmp_path: Path) -> None:
    """列文件：相对 POSIX 路径、排序、**只列文件不列目录**。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "src/main.py", "print('hi')\n")
    _seed(root, "README.md", "# readme\n")
    _seed(root, "src/nested/deep.txt", "deep\n")
    (root / "emptydir").mkdir(exist_ok=True)

    resp = client.get(_url(sid, "/files"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["files"] == ["README.md", "src/main.py", "src/nested/deep.txt"]
    assert body["total"] == 3
    assert body["returned"] == 3
    assert body["truncated"] is False


def test_pattern_filters_and_total_counts_matches(tmp_path: Path) -> None:
    """`pattern` 是 glob 过滤（对相对路径整体或文件名匹配，`**` 支持递归）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "src/a.py", "a\n")
    _seed(root, "src/b.py", "b\n")
    _seed(root, "src/c.txt", "c\n")

    resp = client.get(_url(sid, "/files"), params={"pattern": "*.py"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["files"] == ["src/a.py", "src/b.py"]
    assert body["total"] == 2


def test_limit_truncates_and_returns_the_sorted_prefix(tmp_path: Path) -> None:
    """超过 `limit` 时截断并**如实**标记：返回的是排序后的前缀，`total` 不受 limit 影响。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    for i in range(5):
        _seed(root, f"f{i}.txt", f"{i}\n")

    resp = client.get(_url(sid, "/files"), params={"limit": 2})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["files"] == ["f0.txt", "f1.txt"]
    assert body["returned"] == 2
    assert body["total"] == 5
    assert body["truncated"] is True


def test_pattern_cannot_reach_outside_the_workspace(tmp_path: Path) -> None:
    """`pattern` 只是过滤器：穿越型模式也变不出 workspace 之外的文件。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "inside.txt", "in\n")
    outside = _outside_file(root, tmp_path)

    for pattern in ("*", "../*", f"{outside.name}", f"../{outside.name}"):
        resp = client.get(_url(sid, "/files"), params={"pattern": pattern})
        assert resp.status_code == 200, resp.text
        files = resp.json()["files"]
        assert outside.name not in files, f"pattern={pattern!r} 漏出了 workspace 外文件：{files}"


# ── AC2：读单个文件 ──


def test_reads_file_with_slice_envelope(tmp_path: Path) -> None:
    """正常读取：行级信封（与 artifact 切片同名同义），未截断时 `next_offset` 为 null。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "src/main.py", "l1\nl2\nl3\n")

    resp = client.get(_url(sid, "/file"), params={"path": "src/main.py"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == "src/main.py"
    assert [ln["text"] for ln in body["lines"]] == ["l1", "l2", "l3"]
    assert [ln["line_number"] for ln in body["lines"]] == [1, 2, 3]
    assert body["total_lines"] == 3
    assert body["returned_lines"] == 3
    assert body["truncated"] is False
    assert body["next_offset"] is None


def test_offset_starts_at_the_requested_line(tmp_path: Path) -> None:
    """`offset` 从第 N 行开始（1-based），行号仍是**原文行号**。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "f.txt", "a\nb\nc\nd\n")

    resp = client.get(_url(sid, "/file"), params={"path": "f.txt", "offset": 3})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [ln["line_number"] for ln in body["lines"]] == [3, 4]
    assert body["total_lines"] == 4
    assert body["next_offset"] is None


def test_limit_truncates_and_next_offset_continues(tmp_path: Path) -> None:
    """`limit` 截断时给出可执行的续读指针（`next_offset`），不是只给一个 truncated 布尔。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "f.txt", "a\nb\nc\nd\ne\n")

    first = client.get(_url(sid, "/file"), params={"path": "f.txt", "limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert [ln["text"] for ln in body["lines"]] == ["a", "b"]
    assert body["total_lines"] == 5
    assert body["returned_lines"] == 2
    assert body["truncated"] is True
    assert body["next_offset"] == 3

    rest = client.get(_url(sid, "/file"), params={"path": "f.txt", "offset": body["next_offset"]})
    assert rest.status_code == 200, rest.text
    assert [ln["text"] for ln in rest.json()["lines"]] == ["c", "d", "e"]
    assert rest.json()["next_offset"] is None


def test_overlong_line_is_capped_and_marked(tmp_path: Path) -> None:
    """单行超长按上限截断，并**逐行标注** `truncated`/`full_length`（不静默改内容）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "long.txt", "x" * 3000 + "\nshort\n")

    resp = client.get(_url(sid, "/file"), params={"path": "long.txt"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    first, second = body["lines"]
    assert len(first["text"]) == 2000
    assert first["truncated"] is True
    assert first["full_length"] == 3000
    assert second == {"line_number": 2, "text": "short"}
    assert body["truncated"] is True
    assert body["total_lines"] == 2


def test_single_overlong_line_says_there_is_nothing_more_to_read(tmp_path: Path) -> None:
    """只有一行且被字符上限截断时 `next_offset` 必须是 null。

    这一行的行号已经被用掉了（它返回过了，只是被截短）——再给一个续读指针会让调用方
    去读一个不存在的行；截断这件事由该行的 `truncated`/`full_length` 如实交代。
    """
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "one.txt", "y" * 3000 + "\n")

    resp = client.get(_url(sid, "/file"), params={"path": "one.txt"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_lines"] == 1
    assert body["returned_lines"] == 1
    assert body["truncated"] is True
    assert body["next_offset"] is None
    assert body["lines"][0]["full_length"] == 3000


def test_nul_in_path_is_422_not_500(tmp_path: Path) -> None:
    """含 NUL 的路径 → 422。

    `Path.resolve()` 遇 NUL 抛 `ValueError`（**不是** OSError），不接就会穿透成 500
    （`host_dirs` 对同一形态有同样的守卫，见那边的注释）。
    """
    client = _client(tmp_path)
    sid = _create_session(client)
    _root(client, sid)

    resp = client.get(_url(sid, "/file"), params={"path": "a\x00b"})

    assert resp.status_code == 422, resp.text
    assert "非法字符" in resp.json()["detail"]


def test_binary_file_is_refused_honestly(tmp_path: Path) -> None:
    """非 UTF-8 内容 → 415 + 策展中文说明（不猜编码、不吐乱码当文本）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    (root / "blob.bin").write_bytes(b"\xff\xfe\x00\x01\x80")

    resp = client.get(_url(sid, "/file"), params={"path": "blob.bin"})

    assert resp.status_code == 415, resp.text
    assert "UTF-8" in resp.json()["detail"]
    assert "blob.bin" in resp.json()["detail"]


def test_missing_file_is_404_with_file_wording(tmp_path: Path) -> None:
    """不存在的文件：404，且文案说的是**文件**（目录浏览那套"目录不存在"在此是错的）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    _root(client, sid)

    resp = client.get(_url(sid, "/file"), params={"path": "nope/missing.txt"})

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"].startswith("文件不存在：")


def test_directory_read_maps_is_a_directory_to_422(tmp_path: Path) -> None:
    """目录当文件读：POSIX 的 `IsADirectoryError` → 422 `不是文件：<path>`（不是 500）。

    用替身异常钉住映射（不依赖本机平台）：win32 的 `open()` 对目录抛 `PermissionError`，
    那时如实报 403（见下一条），两条路径都不冒 500。
    """
    client = _client(tmp_path)
    sid = _create_session(client)
    target = _root(client, sid) / "adir"
    target.mkdir(exist_ok=True)

    with patch.object(type(_sandbox(client, sid)), "read_text", side_effect=IsADirectoryError):
        resp = client.get(_url(sid, "/file"), params={"path": "adir"})

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"].startswith("不是文件：")


def test_directory_read_never_500s_on_this_platform(tmp_path: Path) -> None:
    """真实平台上把目录（或不可读路径）当文件读：403/422 都是如实答案，**不是 500**。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    (root / "adir").mkdir(exist_ok=True)

    resp = client.get(_url(sid, "/file"), params={"path": "adir"})

    assert resp.status_code in (403, 422), resp.text
    # 文案必须点名路径，且与"参数写错"（422 的参数级 detail）区分得开。
    assert str(root) not in resp.json()["detail"]  # 不泄漏宿主绝对路径


def test_relative_traversal_out_of_workspace_is_403(tmp_path: Path) -> None:
    """相对穿越：403，且**真造过的外部文件**没有被读出来。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    outside = _outside_file(root, tmp_path)
    rel = os.path.relpath(outside, root).replace(os.sep, "/")

    resp = client.get(_url(sid, "/file"), params={"path": rel})

    assert resp.status_code == 403, resp.text
    assert "OUTSIDE-SECRET" not in resp.text
    assert os.path.dirname(str(outside)) not in resp.text  # 不泄漏宿主绝对路径


def test_absolute_path_out_of_workspace_is_403(tmp_path: Path) -> None:
    """绝对路径指向 workspace 之外：同样 403（边界与工具层同一份强制点）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    outside = _outside_file(root, tmp_path)

    resp = client.get(_url(sid, "/file"), params={"path": str(outside)})

    assert resp.status_code == 403, resp.text
    assert "OUTSIDE-SECRET" not in resp.text


def test_absolute_path_inside_workspace_is_allowed(tmp_path: Path) -> None:
    """workspace **之内**的绝对路径允许（与 `read` 工具同一口径：绝对/相对都认）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    target = _seed(root, "inside.txt", "inside\n")

    resp = client.get(_url(sid, "/file"), params={"path": str(target)})

    assert resp.status_code == 200, resp.text
    assert [ln["text"] for ln in resp.json()["lines"]] == ["inside"]


# ── AC3：git 状态 / 单文件 diff（复用工具层的命令语义）──


def _init_git_repo(client: TestClient, sid: str) -> None:
    """与 `tests/tools/test_git_tools.py` 同一套初始化（同一命令语义，只是经 HTTP 验）。"""
    sandbox = _sandbox(client, sid)
    sandbox.exec("git init -q")
    sandbox.exec("git config user.email test@test.com")
    sandbox.exec("git config user.name test")
    sandbox.exec("git config core.quotepath false")


def test_git_status_reports_porcelain(tmp_path: Path) -> None:
    """`git status --porcelain=v1`：未跟踪文件如实出现，`exit_code=0`。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _init_git_repo(client, sid)
    _seed(root, "new.py", "print('hi')\n")

    resp = client.get(_url(sid, "/git/status"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exit_code"] == 0
    assert "?? new.py" in body["stdout"]


def test_git_status_pathspec_filters(tmp_path: Path) -> None:
    """`pathspec` 过滤（纯路径，不支持通配符——与工具层同一份白名单）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _init_git_repo(client, sid)
    _seed(root, "a.py", "a\n")
    _seed(root, "b.txt", "b\n")

    resp = client.get(_url(sid, "/git/status"), params={"pathspec": "a.py"})

    assert resp.status_code == 200, resp.text
    stdout = resp.json()["stdout"]
    assert "a.py" in stdout
    assert "b.txt" not in stdout


def test_git_diff_returns_one_file_diff(tmp_path: Path) -> None:
    """单文件 diff：改一个已跟踪文件后 `git diff <path>` 给出该文件的 diff。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _init_git_repo(client, sid)
    _seed(root, "f.txt", "before\n")
    sandbox = _sandbox(client, sid)
    sandbox.exec("git add f.txt")
    sandbox.exec("git commit -q -m base")
    _seed(root, "f.txt", "after\n")

    resp = client.get(_url(sid, "/git/diff"), params={"path": "f.txt"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exit_code"] == 0
    assert "-before" in body["stdout"]
    assert "+after" in body["stdout"]


def test_git_staged_diff_uses_the_staged_flag(tmp_path: Path) -> None:
    """`staged=true` → `git diff --staged`（工具层同一个开关）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _init_git_repo(client, sid)
    _seed(root, "f.txt", "one\n")
    _sandbox(client, sid).exec("git add f.txt")

    unstaged = client.get(_url(sid, "/git/diff"), params={"path": "f.txt"})
    staged = client.get(_url(sid, "/git/diff"), params={"path": "f.txt", "staged": True})

    assert unstaged.status_code == 200 and staged.status_code == 200
    assert unstaged.json()["stdout"].strip() == "", "未暂存时不该有 diff"
    assert "+one" in staged.json()["stdout"]


def test_git_not_a_repo_is_honest_not_500(tmp_path: Path) -> None:
    """不是 git 仓库：200 + 如实 `exit_code`/`stderr`（ADR-0002，工具层同款语义）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    _root(client, sid)

    resp = client.get(_url(sid, "/git/status"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["exit_code"] != 0
    assert body["stderr"], "非仓库时 stderr 必须如实带回，不能是空字符串 + 假装成功"


def test_git_pathspec_with_shell_metacharacters_is_422(tmp_path: Path) -> None:
    """shell 元字符一律 422：白名单在**工具层**那一份，路由不许自己放行。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    _root(client, sid)
    _init_git_repo(client, sid)

    for bad in ("a; rm -rf .", "a&b", "`whoami`", "a|b", "a\nb", '"a"', "a\x00b"):
        resp = client.get(_url(sid, "/git/status"), params={"pathspec": bad})
        assert resp.status_code == 422, f"{bad!r} 未被拒绝：{resp.status_code} {resp.text}"
        resp_diff = client.get(_url(sid, "/git/diff"), params={"path": bad})
        assert resp_diff.status_code == 422, f"{bad!r} 未被拒绝：{resp_diff.text}"


# ── P0（code-review）：git 的范围是**仓库**，必须围回 workspace 子树 ──
#
# 默认布局是 `<workspace_dir>/workspaces/<session_id>`；只要 `workspace_dir` 落在某个
# 仓库里（开发机上几乎必然），工作区就"嵌"在那个仓库内，而 git 不认 workspace 边界：
# 修复前裸 `git diff` 会把仓库里 workspace **之外**的文件 diff 正文直接吐出来。
# 下面两条用**真的嵌进一个更大仓库**的布局来证明围栏与边界校验确实生效。


def _nest_workspace_in_a_bigger_repo(client: TestClient, sid: str, tmp_path: Path) -> Path:
    """把会话工作区嵌进一个更大的 git 仓库，返回仓库根。

    仓库建在 workspace 的**父目录**（`root.parent`）：无论 workspace 的布局是
    `<tmp>/workspaces/<sid>` 还是别的形状，父目录都是"工作区之外、但同一个仓库里"。
    外部文件放仓库根（= 工作区的上级），于是"穿越"就是一次 `..`。
    """
    root = _root(client, sid)
    repo = root.parent
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    secret = repo / "outside-secret.txt"
    secret.write_text("ORIGINAL\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    secret.write_text("LEAKED-SECRET-BODY\n", encoding="utf-8")  # 制造一个仓库内的改动
    return repo


def test_git_commands_are_pinned_to_the_workspace_subtree(tmp_path: Path) -> None:
    """工作区嵌在更大仓库里时，两条 git 路由都**不许**报告/吐出外面的文件。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    _nest_workspace_in_a_bigger_repo(client, sid, tmp_path)

    status = client.get(_url(sid, "/git/status"))
    assert status.status_code == 200, status.text
    assert "outside-secret.txt" not in status.json()["stdout"], (
        "裸 git status 列出了 workspace 之外的文件（缺 scope 围栏）"
    )

    diff = client.get(_url(sid, "/git/diff"))
    assert diff.status_code == 200, diff.text
    assert "LEAKED-SECRET-BODY" not in diff.text, (
        "裸 git diff 吐出了 workspace 之外文件的正文（P0）"
    )


def test_git_traversal_pathspec_is_refused(tmp_path: Path) -> None:
    """穿越型 pathspec：403（边界先于 git），且正文里没有外面文件的内容。

    只加围栏不够——多个 pathspec 是**并集**，`../../outside-secret.txt` 会把外面重新
    拉回来，所以 pathspec 必须先过 Sandbox 边界。
    """
    client = _client(tmp_path)
    sid = _create_session(client)
    repo = _nest_workspace_in_a_bigger_repo(client, sid, tmp_path)
    root = _root(client, sid)
    rel = os.path.relpath(repo / "outside-secret.txt", root).replace(os.sep, "/")
    assert rel.startswith(".."), f"测试前提被破坏：外部文件不在工作区之外（{rel}）"

    for url, params in (
        (_url(sid, "/git/status"), {"pathspec": rel}),
        (_url(sid, "/git/diff"), {"path": rel}),
        (_url(sid, "/git/diff"), {"path": "../outside-secret.txt"}),
    ):
        resp = client.get(url, params=params)
        assert resp.status_code == 403, f"{url} {params} 未被拒绝：{resp.status_code} {resp.text}"
        assert "LEAKED-SECRET-BODY" not in resp.text
        assert "ORIGINAL" not in resp.text


# ── 会话 / 映射 / 参数 / 来源闸 ──


def test_untrusted_origin_is_refused_on_every_route(tmp_path: Path) -> None:
    """四条路由都在宿主侧来源闸之后（ADR-0028 D2 同一份 `require_trusted_origin`）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    headers = {"Origin": "http://evil.example"}
    urls = [
        _url(sid, "/files"),
        _url(sid, "/file") + "?path=x.txt",
        _url(sid, "/git/status"),
        _url(sid, "/git/diff"),
    ]

    for url in urls:
        resp = client.get(url, headers=headers)
        assert resp.status_code == 403, f"{url} 未受来源闸保护：{resp.status_code} {resp.text}"
        assert "拒绝跨源访问" in resp.json()["detail"]


def test_trusted_origin_is_allowed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sid = _create_session(client)
    _root(client, sid)

    resp = client.get(_url(sid, "/files"), headers={"Origin": "http://localhost:5173"})

    assert resp.status_code == 200, resp.text


def test_invalid_session_id_is_422(tmp_path: Path) -> None:
    """含 `.` 的 id 能过 URL 路由、过不了 `validate_session_id` → 422（不是 404/500）。

    注意不能拿 `not/valid` 试：那个路径根本匹配不上 `{session_id}`（单段），
    会是路由层的 404——那样测的是 FastAPI 的路由表，不是我们这份校验。
    """
    client = _client(tmp_path)

    resp = client.get(_url("bad.id", "/files"))

    assert resp.status_code == 422, resp.text
    assert "session_id" in resp.json()["detail"]


def test_missing_session_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    resp = client.get(_url("0" * 32, "/files"))

    assert resp.status_code == 404, resp.text
    # 断言 detail 而不只是状态码：路由不存在时 FastAPI 也给 404，那样这条用例会**假绿**。
    assert "not found" in resp.json()["detail"]


def test_session_without_workspace_mapping_is_404_not_500(tmp_path: Path) -> None:
    """有会话但无 workspace 映射（映射被删 / 非本部署创建）→ 404 如实说明，不是 500。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    registry = client.app.state.agent.workspace_registry

    with patch.object(
        type(registry), "get", side_effect=KeyError(f"Session '{sid}' 没有对应的 workspace 映射记录。")
    ):
        resp = client.get(_url(sid, "/files"))

    assert resp.status_code == 404, resp.text
    assert "workspace" in resp.json()["detail"]


def test_offset_and_limit_are_validated(tmp_path: Path) -> None:
    """行号从 1 开始：`offset<1` 与越界的 `limit` 都是 422（与 artifact 路由同一口径）。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    _root(client, sid)

    assert client.get(_url(sid, "/file"), params={"path": "x", "offset": 0}).status_code == 422
    assert client.get(_url(sid, "/file"), params={"path": "x", "limit": 0}).status_code == 422
    assert client.get(_url(sid, "/file"), params={"path": "x", "limit": 10**6}).status_code == 422
    assert client.get(_url(sid, "/files"), params={"limit": 0}).status_code == 422


def test_no_response_leaks_the_host_workspace_root(tmp_path: Path) -> None:
    """工作区是**相对**浏览面：四条路由的正常响应都不含宿主绝对根路径。"""
    client = _client(tmp_path)
    sid = _create_session(client)
    root = _root(client, sid)
    _seed(root, "src/main.py", "print('hi')\n")
    _init_git_repo(client, sid)
    needle = str(root)

    bodies = [
        client.get(_url(sid, "/files")).text,
        client.get(_url(sid, "/file"), params={"path": "src/main.py"}).text,
        client.get(_url(sid, "/git/status")).text,
        client.get(_url(sid, "/git/diff")).text,
    ]

    for body in bodies:
        # 先确认这条**真是**一条成功响应：路由不存在时四个 body 都是 404 的"Not Found"，
        # 只断言"不含绝对路径"会让这条用例在什么都没有的时候也绿。
        assert needle not in body, f"响应体泄漏了宿主 workspace 绝对路径：{body[:200]}"
        assert "Not Found" not in body, f"请求没打到路由上，这条断言没有意义：{body[:200]}"
