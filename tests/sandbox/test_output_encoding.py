"""子进程输出解码：GBK（中文 Windows cmd.exe）不得被当成 UTF-8 解出乱码（OBS-011）。

为什么值得一个专文件：乱码一旦落进 append-only JSONL 就**不可逆**（回放 / eval /
Langfuse 都读它），且会让「模型看到的工具输出」与真相不一致。此前
`sandbox/local.py` 把子进程输出**硬编码**按 `utf-8 + errors="replace"` 解码，于是
中文 Windows 上 cmd.exe 的 GBK 输出被解成 `ʱ��Ӧ��` 这类字符并固化进事件日志。

测试缝：`LocalSubprocessSandbox.exec()` 是真实子进程路径（不是 mock），用
`sys.executable` 绝对路径发字节，避免依赖 PATH。
"""

from __future__ import annotations

import codecs
import sys
from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.sandbox.decoding import (
    PROBE_LIMIT as _PROBE_LIMIT,
)
from agent_harness.sandbox.decoding import StreamDecoder, platform_fallback_encoding

# 一段真实场景的文案：cmd.exe 在中文 Windows 上解析 bash 语法失败时的报错。
CMD_ERROR_TEXT = "此时不应有 i。"


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    """显式把兜底编码钉成 cp936——GBK 回退路径才能在**任何平台**的 CI 上被测。"""
    return LocalSubprocessSandbox(workspace_root=tmp_path, fallback_encoding="cp936")


class TestPlatformFallbackEncoding:
    def test_returns_a_usable_codec(self):
        """缺省兜底编码必须是本机 codecs 认得的名字（否则回退路径自己会崩）。"""
        name = platform_fallback_encoding()

        codecs.lookup(name)  # 认不出会直接抛 LookupError

    @pytest.mark.skipif(sys.platform != "win32", reason="OEM 代码页只存在于 Windows")
    def test_windows_returns_the_real_oem_codepage(self):
        """必须取**控制台真实代码页**，不能退化成 utf-8。

        非空洞断言：`codecs.lookup("utf-8")` 同样通过，所以「返回 utf-8」这种
        退化实现只能靠与 `GetOEMCP()` 比对来识破。本项目环境有 `PYTHONUTF8=1`，
        也正是 `locale.getpreferredencoding(False)` 会骗人的那条路。
        """
        import ctypes

        expected = f"cp{int(ctypes.windll.kernel32.GetOEMCP())}"

        assert platform_fallback_encoding() == expected


def _emit_bytes(sandbox: LocalSubprocessSandbox, tmp_path: Path, expr: str) -> str:
    """让子进程往 stdout 写**原始字节**，返回 sandbox 捕获的 stdout。

    用 `sys.executable` 的绝对路径，不依赖 PATH / 不依赖 `python` 这个名字。
    """
    script = tmp_path / "emit_bytes.py"
    script.write_bytes(f"import sys\nsys.stdout.buffer.write({expr})\n".encode())
    result = sandbox.exec(f'"{sys.executable}" "{script.name}"')
    assert result.exit_code == 0, result.stderr
    return result.stdout


class TestSubprocessOutputDecoding:
    """走真实子进程路径的解码行为（OBS-011 的验收面）。"""

    def test_gbk_output_is_decoded_readably(self, sandbox, tmp_path):
        """GBK 字节 → 中文可读，且**没有** U+FFFD（乱码标记）。"""
        stdout = _emit_bytes(
            sandbox, tmp_path, f"{CMD_ERROR_TEXT!r}.encode('gbk')"
        )

        assert "\ufffd" not in stdout, f"乱码标记出现在输出里：{stdout!r}"
        assert CMD_ERROR_TEXT in stdout

    def test_utf8_output_is_unchanged(self, sandbox, tmp_path):
        """UTF-8 字节（GNU 工具 / python 的常态）→ 与原行为完全一致（回归锁）。"""
        stdout = _emit_bytes(sandbox, tmp_path, "'中文 UTF-8'.encode('utf-8')")

        assert stdout.strip() == "中文 UTF-8"

    def test_undecodable_bytes_do_not_crash(self, sandbox, tmp_path):
        """纯二进制垃圾不得让解码崩掉，且调用方拿到的仍是合法 str。"""
        stdout = _emit_bytes(sandbox, tmp_path, "b'\\xff\\xfe\\x00\\x80\\x01'")

        assert isinstance(stdout, str)
        assert stdout  # 有内容（怎么替换是一回事，丢光就是另一回事）

    def test_late_invalid_byte_does_not_truncate_stream(self, sandbox, tmp_path):
        """真实子进程路径上的截断回归：坏字节出现在已判定 UTF-8 之后。"""
        expr = "b'A' * 70000 + b'\\xff' + b'TAIL-mark'"
        stdout = _emit_bytes(sandbox, tmp_path, expr)

        assert stdout.startswith("A" * 70000), f"头部被截断：{len(stdout)} 字符"
        assert stdout.endswith("TAIL-mark"), f"尾标丢失：…{stdout[-40:]!r}"


class TestStreamDecoderUnit:
    """解码器单元面：不启用子进程，直接锁决策规则本身。"""

    def test_prefers_utf8_when_bytes_are_valid_utf8(self):
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed("中文".encode()) + decoder.flush()

        assert text == "中文"
        assert decoder.encoding == "utf-8"
        # `encoding` 在未判定时也返回 "utf-8"，必须同时断言真的判定过
        assert decoder.decided

    def test_falls_back_to_preferred_encoding_on_invalid_utf8(self):
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed(CMD_ERROR_TEXT.encode("gbk")) + decoder.flush()

        assert text == CMD_ERROR_TEXT, f"回退解码结果不对：{text!r}"
        assert decoder.encoding == "cp936"
        assert decoder.decided

    def test_fallback_is_sticky_within_one_stream(self):
        """同一条流一旦判定为非 UTF-8，后续段沿用同一编码（不要逐段反复横跳）。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        first = decoder.feed("中文".encode("gbk"))
        second = decoder.feed("继续".encode("gbk"))
        text = first + second + decoder.flush()

        assert "中文继续" == text
        assert decoder.encoding == "cp936"

    def test_multibyte_char_split_across_chunks_is_not_lost(self):
        """多字节字符被 chunk 边界切开也不能丢字（增量解码，不是逐块独立解码）。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        raw = "中文".encode()
        # 在第一个字符的 3 字节中间切开
        text = decoder.feed(raw[:2]) + decoder.feed(raw[2:]) + decoder.flush()

        assert text == "中文"


class TestLateInvalidBytes:
    """已判定 UTF-8 之后才出现的坏字节：只能替换，**绝不能抛**（抛=静默丢流）。

    回归锁对应一次真实回归：判定后接管严格探测解码器，`decode()` 在坏字节上抛
    `UnicodeDecodeError`，被 `_drain_stream` 的宽 `except` 吞掉 → 之后的内容
    全部丢失（70000 字节输出只剩 65536，尾标不见）。
    """

    def test_invalid_byte_after_commit_keeps_the_rest(self):
        decoder = StreamDecoder(fallback_encoding="cp936")
        head = decoder.feed(b"A" * _PROBE_LIMIT)
        middle = decoder.feed(b"\xff")
        tail = decoder.feed(b"TAIL-mark") + decoder.flush()

        assert head == "A" * _PROBE_LIMIT
        assert decoder.decided and decoder.encoding == "utf-8"
        assert "\ufffd" in middle
        assert tail == "TAIL-mark", f"判定后的流被截断：{tail!r}"

    def test_trailing_incomplete_utf8_after_commit_survives_flush(self):
        """flush 时挂在末尾的不完整 UTF-8 序列 → 替换字符，而不是抛异常。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        decoder.feed(b"A" * _PROBE_LIMIT)  # 先判定 UTF-8
        decoder.feed(b"\xe4")  # 一个 3 字节序列的开头，永远等不到后续

        assert decoder.flush() == "\ufffd"

    def test_flush_finalizes_fallback_pending_bytes(self):
        """回退路径上 flush 也要收尾：挂在末尾的不完整字节不能被无声丢掉。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        assert decoder.feed(b"abc\xe4") == ""  # 尚未判定，继续缓冲

        assert decoder.flush() == "abc\ufffd"

    def test_multibyte_char_split_exactly_at_commit_boundary(self):
        """多字节字符正好跨在「判定 UTF-8」的分界上：一个字都不能丢或变形。

        `_commit_utf8` 靠 `len(text.encode())` 反推严格探测解码器消费了多少字节，
        再把余下的尾字节交给宽松解码器。上面各例的提交点都落在纯 ASCII 上、余量为
        空——这一例专门让提交点切在一个汉字的中间。
        """
        decoder = StreamDecoder(fallback_encoding="cp936")
        raw = b"A" * (_PROBE_LIMIT - 2) + "中".encode()
        text = decoder.feed(raw[:_PROBE_LIMIT]) + decoder.feed(raw[_PROBE_LIMIT:])
        text += decoder.flush()

        assert text == "A" * (_PROBE_LIMIT - 2) + "中"
        assert decoder.decided and decoder.encoding == "utf-8"

    def test_unknown_fallback_encoding_fails_fast(self):
        """非法编码名必须在构造时就报错。

        否则要到第一次遇到非法字节才在解码线程里抛 LookupError，被
        `_drain_stream` 的宽 except 吞掉——正是本次要消灭的静默截断。
        """
        with pytest.raises(LookupError):
            StreamDecoder("definitely-not-a-codec")


class TestDrainCoupling:
    """`_DRAIN_CHUNK_BYTES <= PROBE_LIMIT` 是解码判定正确性的前提，别悄悄改。"""

    def test_drain_chunk_stays_within_probe_budget(self):
        from agent_harness.sandbox import local as local_module

        assert local_module._DRAIN_CHUNK_BYTES <= _PROBE_LIMIT, (
            "单次喂入超过探测预算时，「已满上限的合法 UTF-8 + 同段坏字节」会被判成"
            "兜底编码，判定结果将取决于坏字节落在哪一段——必须保持 <= PROBE_LIMIT"
        )


class TestNewlineNormalization:
    """保留 `text=True` 时代的通用换行归一（否则 Windows 每条输出多一个 `\\r`）。"""

    def test_crlf_becomes_lf(self):
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed(b"a\r\nb\r\n") + decoder.flush()

        assert text == "a\nb\n"

    def test_crlf_split_across_chunks_is_one_newline(self):
        """`\\r` 与 `\\n` 分属两个 chunk 时也必须只产生一个换行（不得变成两个）。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed(b"a\r") + decoder.feed(b"\nb") + decoder.flush()

        assert text == "a\nb"

    def test_lone_cr_becomes_lf(self):
        """孤立 `\\r`（老式换行 / 进度条）按通用换行语义归一为 `\\n`。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed(b"a\rb") + decoder.flush()

        assert text == "a\nb"

    def test_trailing_cr_at_eof_becomes_lf(self):
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed(b"a\r") + decoder.flush()

        assert text == "a\n"

    def test_newline_normalization_applies_on_fallback_path_too(self):
        """回退编码路径同样要归一（两条路径行为必须一致）。"""
        decoder = StreamDecoder(fallback_encoding="cp936")
        text = decoder.feed("中文\r\n".encode("gbk")) + decoder.flush()

        assert text == "中文\n"


class TestDurablePathHasNoMojibake:
    """OBS-011 的**真实验收面**：乱码不得进 append-only JSONL（落了就不可逆）。

    单看 `exec()` 返回值还不够——本项断言的是「写进事件存储的字节里没有 U+FFFD」，
    即回放 / eval / Langfuse 读到的东西是干净的。
    """

    def test_gbk_tool_output_stored_in_jsonl_is_readable(self, tmp_path):
        from agent_harness.session.event import TOOL_RESULT
        from tests.conftest import make_session

        sandbox = LocalSubprocessSandbox(
            workspace_root=tmp_path / "ws", fallback_encoding="cp936"
        )
        script = tmp_path / "ws" / "emit_gbk.py"
        script.write_bytes(
            "import sys\n"
            f"sys.stdout.buffer.write({CMD_ERROR_TEXT!r}.encode('gbk'))\n".encode()
        )
        result = sandbox.exec(f'"{sys.executable}" "{script.name}"')
        assert "\ufffd" not in result.stdout

        session = make_session(tmp_path / "sessions")
        session.append(TOOL_RESULT, {
            "tool_call_id": "tc-1", "ok": True,
            "stdout": result.stdout, "exit_code": 0,
        })

        jsonl = tmp_path / "sessions" / session.session_id / "events.jsonl"
        stored = jsonl.read_bytes().decode("utf-8")  # 文件本身必须是合法 UTF-8

        assert stored.count("\ufffd") == 0, "乱码被固化进了事件日志"
        assert CMD_ERROR_TEXT in stored
