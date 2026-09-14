"""LocalSubprocessSandbox：在本机子进程执行命令的 Sandbox 后端。

开发/测试默认后端，零外部依赖（不需要 Docker daemon）。workspace_root 是本机
一个真实目录，命令通过 subprocess.run 执行，文件读写用标准 pathlib。

生产环境隔离请用 DockerSandbox；本后端不做进程级隔离。
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import signal
import subprocess
import threading
from contextlib import suppress
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from agent_harness.sandbox.base import (
    ExecResult,
    Sandbox,
    ShellEnvironment,
    ShellFamily,
)
from agent_harness.sandbox.decoding import StreamDecoder, platform_fallback_encoding

#: LocalSubprocess 的默认命令超时（秒）。None 表示不超时。
DEFAULT_EXEC_TIMEOUT: float = 60.0

logger = logging.getLogger("agent_harness.sandbox.local")

#: 捕获流读取块大小（字节——流以 text=False 打开，解码见 sandbox/decoding.py）。
#: ⚠ 必须 <= decoding.PROBE_LIMIT：单次喂入超过剩余探测预算会让「已满上限的
#: 合法 UTF-8 + 同段坏字节」被判成兜底编码（与坏字节落在下一段的结果不一致）。
_DRAIN_CHUNK_BYTES = 65536


class _CappedCapture:
    """有上限的捕获缓冲：超限后继续排空管道（让子进程自然结束）但丢弃内容。

    没有它，`subprocess.run(capture_output=True)` 会把任意大的 stdout/stderr
    整体读进内存——一个 cat 大文件的命令就能 OOM 掉整个 agent 进程（D4）。
    """

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self._chunks: list[str] = []
        self._remaining = max_chars
        self.truncated = False
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        with self._lock:
            if self._remaining > 0:
                keep = text[: self._remaining]
                self._chunks.append(keep)
                self._remaining -= len(keep)
                if len(keep) < len(text):
                    self.truncated = True
            elif text:
                self.truncated = True

    def value(self) -> str:
        with self._lock:
            return "".join(self._chunks)


def _glob_match(rel_path: str, pattern: str) -> bool:
    """对 workspace 相对路径做 glob 匹配，支持 ** 递归。

    pathlib.PurePath.match 不支持顶级 ** 前缀跨多段目录匹配，
    所以这里把 ** 模式规范化后用 fnmatch 逐段处理。
    """
    if pattern in ("", "*"):
        return True
    if "**" in pattern:
        # 把 "**/" 收敛成 ""，让 fnmatch 对完整相对路径匹配剩余字面段。
        # 简化策略：如果模式含 **，剥掉 **/ 后对路径末尾段做匹配。
        normalized = pattern.replace("**/", "").replace("**", "*")
        return fnmatch.fnmatch(rel_path, normalized) or fnmatch.fnmatch(
            Path(rel_path).name, normalized
        )
    return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(
        Path(rel_path).name, pattern
    )


class LocalSubprocessSandbox(Sandbox):
    """本机子进程 Sandbox：命令在本机 subprocess 里跑，文件读写落在 workspace 目录。

    workspace_root 在构造时确定；所有路径操作都经过 resolve_within_workspace 校验。
    进程不存在"启动"概念，ensure_started 是 no-op；stop 也不需要清理（幂等空操作）。
    """

    #: 传给子进程的环境变量白名单（C2，R3-5 落地）：bash 继承完整 host env 时，
    #: 部署机上 export 过的密钥（API keys、tokens）对模型可执行命令可见
    #: （echo $MY_TOKEN 即泄漏）。白名单只保留 OS 运行必需项，不含任何凭据。
    DEFAULT_ENV_ALLOWLIST = (
        # Windows 运行必需
        "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
        "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES",
        "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "USERPROFILE",
        "USERDOMAIN", "USERNAME", "NUMBER_OF_PROCESSORS", "OS",
        # POSIX 运行必需
        "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM", "USER", "LOGNAME", "SHELL",
        # 编码（无凭据风险，缺了会让子进程输出编码漂移）
        "PYTHONIOENCODING", "PYTHONUTF8",
        # 网络环境（pip/curl 等在代理/企业环境下可用性；标准做法：
        # 代理变量属运营配置，不是凭据——真正要防的是 API keys/tokens）
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
    )

    def __init__(
        self,
        workspace_root: Path,
        *,
        max_capture_chars: int = 2_000_000,
        env_allowlist: tuple[str, ...] | None = None,
        passthrough_env: bool = False,
        fallback_encoding: str | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._max_capture_chars = max_capture_chars
        # 输出解码的兜底编码（UTF-8 试探失败时用）：缺省取宿主控制台代码页。
        # 显式传参是测试缝——让 GBK 回退路径可以在任何平台上被测（OBS-011）。
        self._fallback_encoding = fallback_encoding or platform_fallback_encoding()
        # passthrough_env=True 是显式逃生门（本地调试）；默认过滤。
        if passthrough_env:
            self._env: dict[str, str] | None = None
        else:
            allowlist = env_allowlist if env_allowlist is not None else self.DEFAULT_ENV_ALLOWLIST
            self._env = {k: os.environ[k] for k in allowlist if k in os.environ}

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    @property
    def shell_environment(self) -> ShellEnvironment:
        """`shell=True` 实际用的解释器 + 家族（OBS-012）。

        CPython 的 `shell=True` 在 Windows 用 `%COMSPEC%`（缺省 `cmd.exe`），
        在 POSIX 用 `/bin/sh`——**都不是 bash**。名字取 basename，避免把
        `C:\\Windows\\system32\\cmd.exe` 整条路径塞进模型可见的工具描述；
        家族与 `exec` 的真实机制一致（Windows = cmd，POSIX = sh）。
        """
        if os.name == "nt":
            # COMSPEC 可能被引号包住（部分环境写成 "\"C:\\...\\cmd.exe\""），
            # 不剥引号会让模型可见描述出现 `cmd.exe"`。空值则回落到 cmd.exe。
            comspec = os.environ.get("COMSPEC", "cmd.exe").strip().strip('"')
            return ShellEnvironment(
                name=Path(comspec).name or "cmd.exe", family=ShellFamily.CMD,
            )
        return ShellEnvironment(name="/bin/sh", family=ShellFamily.POSIX_SH)

    def ensure_started(self) -> None:
        """no-op：本机进程总在，无需启动。幂等。"""

    def exec(self, command: str, *, timeout: float | None = None,
             cancel_event=None,
             on_output=None) -> ExecResult:
        """在本机 subprocess 执行命令，cwd 锁定在 workspace_root。

        timeout 默认 DEFAULT_EXEC_TIMEOUT 秒；到点杀掉整个进程树并返回
        ExecResult(exit_code=-1, stderr="命令超时…")，不抛异常。
        stdout/stderr 捕获到 max_capture_chars 上限，超限丢弃并附截断标记
        （D4：无上限捕获会被大输出 OOM）。管道由 reader 线程持续排空，
        子进程可自然结束，不会因为缓冲塞满而死锁。
        on_output（ADR-0016 §4.2）：提供时 reader 线程按读取进度逐段回调
        (channel, text)——回调在 reader 线程上下文执行，调用方负责线程安全；
        回调异常不中断排空（捕获完整性优先，异常只落 debug 日志）。
        """
        self.ensure_started()
        effective_timeout = timeout if timeout is not None else DEFAULT_EXEC_TIMEOUT

        # 输出解码（OBS-011）：子进程写的是**原始字节**，编码取决于产出方——
        # GNU 工具多为 UTF-8，cmd.exe 内建报错是宿主控制台代码页（中文 Windows=GBK）。
        # 固定任一编码都会把另一侧解成乱码，而乱码会固化进 append-only JSONL。
        # 故走 StreamDecoder：优先 UTF-8，遇到确凿非法序列整体回退宿主编码。
        # 注意：这里必须 text=False 自己解，不能让 Popen 的 TextIOWrapper 定死编码。
        t0 = perf_counter()
        # POSIX：start_new_session 让子进程自成进程组，超时可 killpg 整树击杀；
        # Windows 不支持该参数（走 taskkill /T，见 _kill_process_tree）。
        popen_kwargs: dict[str, object] = (
            {"start_new_session": True} if os.name == "posix" else {}
        )
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=self._workspace_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # 字节流：解码由 StreamDecoder 负责（见上）
            env=self._env,
            **popen_kwargs,
        )
        stdout_cap = _CappedCapture(self._max_capture_chars)
        stderr_cap = _CappedCapture(self._max_capture_chars)
        readers = [
            threading.Thread(target=self._drain_stream,
                             args=(process.stdout, stdout_cap, "stdout", on_output,
                                   self._output_decoder()),
                             daemon=True),
            threading.Thread(target=self._drain_stream,
                             args=(process.stderr, stderr_cap, "stderr", on_output,
                                   self._output_decoder()),
                             daemon=True),
        ]
        for reader in readers:
            reader.start()

        timed_out = False
        cancelled = False
        if cancel_event is None:
            try:
                exit_code = process.wait(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_process_tree(process)
                try:
                    exit_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover — kill 后通常立即退出
                    exit_code = -1
        else:
            # 协作取消（C1）：小步轮询等退出；置位即击杀整树。
            # pi-mono 同款"取消信号驱动到静默"模式；无 cancel_event 时保持
            # 原单次 wait 路径（git 等只读命令零轮询开销）。
            deadline = perf_counter() + effective_timeout
            while True:
                remaining = deadline - perf_counter()
                try:
                    exit_code = process.wait(timeout=max(0.05, min(0.1, remaining)))
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event.is_set():
                        cancelled = True
                        self._kill_process_tree(process)
                        try:
                            exit_code = process.wait(timeout=5)
                        except subprocess.TimeoutExpired:  # pragma: no cover
                            exit_code = -1
                        break
                    if perf_counter() >= deadline:
                        timed_out = True
                        self._kill_process_tree(process)
                        try:
                            exit_code = process.wait(timeout=5)
                        except subprocess.TimeoutExpired:  # pragma: no cover
                            exit_code = -1
                        break
        for reader in readers:
            reader.join(5)

        stdout, stderr = stdout_cap.value(), stderr_cap.value()
        if stdout_cap.truncated:
            stdout += f"\n[stdout 超过捕获上限 {self._max_capture_chars} 字符，已截断]"
        if stderr_cap.truncated:
            stderr += f"\n[stderr 超过捕获上限 {self._max_capture_chars} 字符，已截断]"
        if cancelled:
            exit_code = -1
            stderr += "\n命令被取消，进程树已终止"
        if timed_out:
            exit_code = -1
            stderr += f"\n命令超时（上限 {effective_timeout} 秒）"
        return ExecResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round((perf_counter() - t0) * 1000, 1),
            cancelled=cancelled,
        )

    @staticmethod
    def _kill_process_tree(process: subprocess.Popen) -> None:
        """超时击杀整棵进程树，而不只 shell 壳。

        shell=True 时 process 只是 cmd.exe / /bin -c 壳，真正干活的是孙进程；
        只杀壳会漏掉它们：继续改 workspace、占住捕获管道（reader join 超时），
        锁住的文件还会让 delete() 的 rmtree 静默失败。
        """
        if os.name == "nt":
            killed = False
            try:
                # taskkill /T 沿父子链整树击杀（含 start /b 脱管孙进程）。
                result = subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                killed = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired) as error:  # pragma: no cover
                logger.debug("taskkill 调用失败，回退 process.kill()：%s", type(error).__name__)
            if not killed:
                process.kill()
        else:
            # POSIX：子进程已在独立进程组（见 Popen start_new_session），整组 SIGKILL。
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:  # 进程组已退出，无须再杀
                process.kill()

    def _output_decoder(self) -> StreamDecoder:
        """每条流一个解码器（stdout/stderr 各自独立判定，互不影响）。"""
        return StreamDecoder(self._fallback_encoding)

    @staticmethod
    def _drain_stream(stream, cap: _CappedCapture, channel: str,
                      on_output=None, decoder: StreamDecoder | None = None) -> None:
        """后台排空一条捕获流；超限后只读不存，保证子进程不被管道背压卡死。

        流是**字节**流（Popen text=False），这里经 decoder 增量解码后交给 cap
        与 on_output——解码策略见 `sandbox/decoding.py`（OBS-011）。

        on_output 提供时逐段回调 (channel, chunk)——在 reader 线程上下文执行，
        回调异常只落 debug 日志（捕获完整性优先，流式是附加通道不是数据面）。
        """
        if decoder is None:  # 防御：无解码器时按 UTF-8 宽松解（等价旧行为）
            decoder = StreamDecoder("utf-8")
        try:
            while raw := stream.read(_DRAIN_CHUNK_BYTES):
                chunk = decoder.feed(raw)
                if not chunk:
                    continue
                cap.append(chunk)
                if on_output is not None:
                    try:
                        on_output(channel, chunk)
                    except Exception as error:  # noqa: BLE001 — 流式回调故障不损捕获
                        logger.debug("on_output callback failed: %s",
                                     type(error).__name__)
            tail = decoder.flush()
            if tail:
                cap.append(tail)
                if on_output is not None:
                    try:
                        on_output(channel, tail)
                    except Exception as error:  # noqa: BLE001 — 同上
                        logger.debug("on_output callback failed: %s",
                                     type(error).__name__)
            # 记录本次解码判定（OBS-011 可审计性）：日后质疑乱码时，可直接看出
            # 这条输出是按 UTF-8 还是按宿主代码页解的。
            logger.debug("captured %s decoded as %s (decided=%s)",
                         channel, decoder.encoding, decoder.decided)
        except Exception as error:  # noqa: BLE001 — 流被随 kill 关闭属正常路径
            logger.debug("capture stream closed during drain: %s", type(error).__name__)
        finally:
            try:
                stream.close()
            except Exception as error:  # noqa: BLE001 — 关闭失败不影响结果
                logger.debug("capture stream close failed: %s", type(error).__name__)

    def list_files(self, pattern: str) -> list[str]:
        """枚举 workspace 内匹配 glob 模式的文件，返回 POSIX 风格相对路径（排序）。

        用 os.walk 遍历 workspace_root，对每个文件的【相对路径】做 glob 匹配。
        pattern 为空或 "*" 时返回所有文件。仅返回文件，不返回目录。
        """
        effective = pattern if pattern else "*"
        results: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(self._workspace_root):
            for fname in filenames:
                full = Path(dirpath) / fname
                rel = full.relative_to(self._workspace_root)
                rel_posix = rel.as_posix()
                if _glob_match(rel_posix, effective):
                    results.append(rel_posix)
        results.sort()
        return results

    def read_text(self, path: str) -> str:
        """读 workspace 内文件。路径越界抛 PermissionError，文件不存在抛 FileNotFoundError。

        newline=""：字节透传，不做 universal-newlines 折叠——否则 CRLF 文件读出
        变 LF，edit 回写即产生整文件 diff（EOL 破坏用户工作区）。
        """
        resolved = self.resolve_within_workspace(path)
        # open() 而非 Path.read_text()：newline="" 关键字参数在 Python 3.12+
        # 才加入 pathlib（PEP 436 backport），3.11 上会 TypeError。
        with open(resolved, "r", encoding="utf-8", newline="") as f:
            return f.read()

    def write_text(self, path: str, content: str) -> None:
        """覆盖写 workspace 内文件（父目录自动创建）。路径越界抛 PermissionError。

        两点字节级保证：
        - newline=""：\\n 不翻译成 os.linesep（win32 上 LF→CRLF 会把 .sh/
          Makefile 类文件写坏、git 显示整文件改动）。
        - temp + os.replace 原子落盘：truncate-in-place 在进程被 kill 的写中途
          不可逆损毁原文件；同目录 rename 在 POSIX/Windows 上都是原子操作。
        """
        resolved = self.resolve_within_workspace(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp = resolved.with_name(f".{resolved.name}.{os.getpid()}.{uuid4().hex[:8]}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, resolved)
        finally:
            with suppress(OSError):
                tmp.unlink()  # Windows AV/索引器可能短暂锁住；清理失败不掩盖主流程

    def copy_in(self, host_path: Path, workspace_path: str) -> None:
        """把宿主文件/目录拷入 workspace 内指定位置。workspace_path 越界抛 PermissionError。"""
        resolved = self.resolve_within_workspace(workspace_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        host = Path(host_path)
        if host.is_dir():
            shutil.copytree(host, resolved)
        else:
            shutil.copy2(host, resolved)

    def stop(self) -> None:
        """no-op：本机进程不需要清理。幂等。"""

    def delete(self) -> None:
        """彻底删除 workspace 目录。幂等（目录不存在也不报错）。

        删除未完成（文件被锁/AV 占用等）时显式抛错——调用方（Registry）据
        此保留映射以便重试，而不是留下无记录的孤儿目录（R8-6）。
        """
        shutil.rmtree(self._workspace_root, ignore_errors=True)
        if self._workspace_root.exists():
            raise RuntimeError(
                f"workspace {self._workspace_root} 删除未完成（文件被占用？），请重试"
            )
