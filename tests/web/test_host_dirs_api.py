"""WS-7 / #170 后端半：`GET /api/host/dirs` 只读目录列举（ADR-0028）契约测试。

契约（PRD §4.4，detail 文案即契约）：

| 输入 | 结果 |
| --- | --- |
| `path` 缺省 | 根模式：`path=null`、`parent=null`，`entries` = 注入 provider 的根列表（按 name 排序） |
| `path` 是目录 | `path` = 规范路径；`entries` = **仅直接子目录**（depth=1、按 name 排序）；`parent` = 上一级 |
| 条目数 > 上限 | 截断 + `truncated: true`（不静默） |
| `path` 非绝对 | 422 `path 必须是绝对路径` |
| `path` 不存在 | 404 `目录不存在：<规范路径>` |
| `path` 是文件 | 422 `不是目录：<规范路径>` |
| 无权限列举 | 403 `无权限访问：<规范路径>` |
| 不受信 `Origin` | 403（与项目/记忆端点**同一份** require_trusted_origin） |

**根枚举一律用注入的假 provider**（PRD §5）：测试不真扫盘符——真扫盘既慢又依赖机器。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.web import host_dirs
from agent_harness.web.app import create_app


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test"
    )
    return TestClient(create_app(settings, enable_cors=False))


def _get(client: TestClient, path: str | None = None) -> dict:
    params = {} if path is None else {"path": path}
    resp = client.get("/api/host/dirs", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mkdirs(root: Path, *names: str) -> None:
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)


# ── 根模式（AC1）──


def test_roots_mode_uses_injected_provider_and_sorts(tmp_path: Path, monkeypatch) -> None:
    """根枚举走可注入 provider；端点自己对 entries 排序（provider 顺序不作数）。"""
    monkeypatch.setattr(
        host_dirs,
        "ROOTS_PROVIDER",
        lambda: [
            host_dirs.DirEntry(name="D:\\", path="D:\\"),
            host_dirs.DirEntry(name="C:\\", path="C:\\"),
        ],
    )
    body = _get(_client(tmp_path))
    assert body["path"] is None
    assert body["parent"] is None
    assert body["truncated"] is False
    assert [e["name"] for e in body["entries"]] == ["C:\\", "D:\\"]


# ── 一层列举（AC2/AC4/AC6）──


def test_lists_only_direct_subdirectories_sorted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = tmp_path / "base"
    base.mkdir()
    _mkdirs(base, "zeta", "Alpha", "beta")
    (base / "a-file.txt").write_text("x", encoding="utf-8")
    # 子目录里再套一层：depth=1 契约要求它**不**出现在本次结果里
    _mkdirs(base / "zeta", "nested")

    body = _get(client, str(base))
    assert Path(body["path"]) == base.resolve()
    assert Path(body["parent"]) == base.resolve().parent
    assert [e["name"] for e in body["entries"]] == ["Alpha", "beta", "zeta"]
    assert all(Path(e["path"]).is_dir() for e in body["entries"])
    # 条目 path = 父目录 + 名字**拼出**（不是 realpath 展开，见 AC6）
    for entry in body["entries"]:
        assert entry["path"] == os.path.join(str(base.resolve()), entry["name"])
    assert body["truncated"] is False


def test_truncates_and_flags_when_over_limit(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    base = tmp_path / "many"
    base.mkdir()
    _mkdirs(base, "d1", "d2", "d3")
    monkeypatch.setattr(host_dirs, "MAX_ENTRIES", 2)

    body = _get(client, str(base))
    assert body["truncated"] is True
    assert [e["name"] for e in body["entries"]] == ["d1", "d2"]


def test_exactly_at_the_limit_is_not_truncated(tmp_path: Path, monkeypatch) -> None:
    """边界锁：`truncated` 是 `> 上限`，恰好等于上限不算截断。"""
    client = _client(tmp_path)
    base = tmp_path / "exact"
    base.mkdir()
    _mkdirs(base, "d1", "d2")
    monkeypatch.setattr(host_dirs, "MAX_ENTRIES", 2)

    body = _get(client, str(base))
    assert body["truncated"] is False
    assert [e["name"] for e in body["entries"]] == ["d1", "d2"]


def test_parent_is_null_at_filesystem_root(tmp_path: Path) -> None:
    """盘根的"上一级"必须是 null（否则"向上"会在根上原地打转）。"""
    client = _client(tmp_path)
    anchor = Path(tmp_path).anchor  # 如 "C:\\" / "/"
    resp = client.get("/api/host/dirs", params={"path": anchor})
    if resp.status_code == 403:
        pytest.skip("当前环境不允许列举盘根（权限），无法验证 parent=null")
    assert resp.status_code == 200, resp.text
    assert resp.json()["parent"] is None


def _make_dir_link(link: Path, target: Path) -> bool:
    """建一个指向目录的链接：优先符号链接；Windows 无特权时退回**目录联接**（junction）。

    为什么要这条回退：Windows 上 `os.symlink` 需要开发者模式/管理员（WinError 1314），
    而 `mklink /J` 不需要——ADR-0028 对 symlink 目录有明确承诺，不能让这条断言在
    开发机上永远 skip（跳过等于没有覆盖）。
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        if done.returncode == 0 and link.is_dir():
            return True
    return False


def test_symlinked_directory_is_listed_once_without_expansion(tmp_path: Path) -> None:
    """AC6 negative 锁：symlink 目录照列一个条目；进入时按真实目标解析，仍是一层。"""
    client = _client(tmp_path)
    base = tmp_path / "base"
    base.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    _mkdirs(target, "inside")
    link = base / "link"
    if not _make_dir_link(link, target):
        pytest.skip("当前环境既不允许符号链接也不允许目录联接")

    body = _get(client, str(base))
    assert [e["name"] for e in body["entries"]] == ["link"]
    # AC6：条目 path 是"父目录 + 条目名"拼出的**链接本身**，不是 realpath 后的目标
    assert body["entries"][0]["path"] == os.path.join(str(base.resolve()), "link")
    assert body["entries"][0]["path"] != str(target.resolve())

    inside = _get(client, str(link))
    assert [e["name"] for e in inside["entries"]] == ["inside"]


# ── 错误矩阵（AC3）──


def test_error_matrix(tmp_path: Path) -> None:
    client = _client(tmp_path)

    resp = client.get("/api/host/dirs", params={"path": "relative/dir"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "path 必须是绝对路径"

    missing = tmp_path / "nope"
    resp = client.get("/api/host/dirs", params={"path": str(missing)})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == f"目录不存在：{os.path.realpath(missing)}"

    a_file = tmp_path / "f.txt"
    a_file.write_text("x", encoding="utf-8")
    resp = client.get("/api/host/dirs", params={"path": str(a_file)})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == f"不是目录：{os.path.realpath(a_file)}"


def test_nul_path_is_422_not_500(tmp_path: Path) -> None:
    """含 NUL 的路径必须在 realpath 之前挡住（POSIX 的 realpath 对 NUL 抛 ValueError）。"""
    client = _client(tmp_path)
    nul = f"{tmp_path}{os.sep}x\x00y"
    resp = client.get("/api/host/dirs", params={"path": nul})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "path 含非法字符（NUL）"


def test_missing_directory_race_is_404_not_500(tmp_path: Path, monkeypatch) -> None:
    """TOCTOU：检查通过后目录被删 → `listdir` 抛 FileNotFoundError，也必须走 404。

    只抓 `PermissionError` 的话这类 errno 会冒成 500，与本端点"不冒 500"的契约冲突。
    """
    client = _client(tmp_path)

    def boom(_path: str) -> list[str]:
        raise FileNotFoundError(2, "gone")

    monkeypatch.setattr(host_dirs.os, "listdir", boom)
    resp = client.get("/api/host/dirs", params={"path": str(tmp_path)})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == f"目录不存在：{os.path.realpath(tmp_path)}"


def test_permission_error_is_403_not_500(tmp_path: Path, monkeypatch) -> None:
    """无权限 = 403 明确原因，不降级成空列表、不冒成 500。"""
    client = _client(tmp_path)

    def boom(_path: str) -> list[str]:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(host_dirs.os, "listdir", boom)
    resp = client.get("/api/host/dirs", params={"path": str(tmp_path)})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == f"无权限访问：{os.path.realpath(tmp_path)}"


# ── 来源闸（AC5）──


def test_trusted_origin_gate(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/host/dirs", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403, resp.text
    resp = client.get("/api/host/dirs", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200, resp.text
