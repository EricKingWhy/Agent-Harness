"""子进程输出解码：优先 UTF-8，遇到确凿的非法序列则整体改用宿主控制台编码。

问题（OBS-011）：`LocalSubprocessSandbox` 此前把输出**硬编码**按
`utf-8 + errors="replace"` 解码。中文 Windows 上 cmd.exe 的报错是 GBK 字节，
按 UTF-8 解会得到 `ʱ��Ӧ��` 这类字符——而且这些字符会被**固化进 append-only 的
事件 JSONL**（回放 / eval / Langfuse 都读它），不可逆。

为什么不能固定一个 encoding：同一个 workspace 里 GNU 工具（ls/grep/python）
输出 UTF-8，cmd.exe 内建报错输出 GBK。固定任一侧都会把另一侧解成乱码。
实测形态是「**一次命令调用一种编码**」，故按流做一次粘性判定即可。

判定必须增量：多字节字符常被 chunk 边界切开，逐块独立解码会丢字或误判。
"""

from __future__ import annotations

import codecs
import logging
import os

logger = logging.getLogger("agent_harness.sandbox.decoding")

#: 未判定前最多缓冲多少字节；超过即认定 UTF-8（避免无上限缓冲）。
PROBE_LIMIT = 64 * 1024


def platform_fallback_encoding() -> str:
    """本机子进程输出的**兜底**编码（UTF-8 解码失败时用）。

    Windows 取 OEM 代码页（`GetOEMCP`，中文系统 = 936/GBK）——那正是 cmd.exe
    写字节用的代码页。

    ⚠ 不能用 `locale.getpreferredencoding()`：Python 的 UTF-8 模式
    （`PYTHONUTF8=1`，本项目环境即如此）会让它返回 `utf-8`，正好丢掉我们要的
    信息；`GetOEMCP()` 反映的是控制台真实代码页，不受 Python 模式影响。
    """
    if os.name == "nt":
        try:
            import ctypes

            codepage = int(ctypes.windll.kernel32.GetOEMCP())
            if codepage > 0:
                return f"cp{codepage}"
        except Exception as error:  # noqa: BLE001 — 探测失败不能影响执行路径
            logger.debug("GetOEMCP probe failed, falling back to utf-8: %s",
                         type(error).__name__)
    return "utf-8"


class StreamDecoder:
    """把一条子进程输出流的原始字节增量解码成 str。

    规则：
    1. 先按 UTF-8 **严格**试探（增量，能跨 chunk 缓冲不完整序列）；
    2. 探测到确凿的非法序列 → 判定整条流为 `fallback_encoding`，并**用该编码
       重解已缓冲的全部原始字节**（不丢前缀）；
    3. 判定是粘性的：同一条流不再反复横跳。

    `encoding` 属性暴露最终判定，供调用方记录（「这次解码是否可信」可审计）。

    另外保留 `text=True` 时代的**通用换行归一**（`\r\n` / 孤立 `\r` → `\n`）：
    改成字节流后不会自动发生，若丢掉，Windows 每条工具输出都会多出一个 `\r`
    进入模型上下文与 JSONL（token 噪音 + 与既有测试/消费者预期不符）。
    """

    def __init__(self, fallback_encoding: str) -> None:
        # 立刻校验编码名：否则要到**第一次遇到非法字节**时才在解码线程里炸出
        # LookupError，再被 _drain_stream 的宽 except 吞掉——又一类静默截断。
        codecs.lookup(fallback_encoding)
        self._fallback_encoding = fallback_encoding
        self._encoding: str | None = None
        self._probe = codecs.getincrementaldecoder("utf-8")("strict")
        self._probe_text: list[str] = []
        self._pending = bytearray()
        self._decoder = None
        #: 归一换行时暂存的结尾 `\r`（可能是下一段 `\n` 的前半，不能提前翻译）
        self._carry = ""

    @property
    def encoding(self) -> str:
        """已判定的编码；尚未判定时返回探测中的 `utf-8`（仅用于日志/审计）。"""
        return self._encoding or "utf-8"

    @property
    def decided(self) -> bool:
        return self._encoding is not None

    def _normalize_newlines(self, text: str) -> str:
        """通用换行归一（等价 TextIOWrapper 的 newline=None 读取语义）。

        结尾孤立的 `\\r` 先扣住：它可能是下一段 `\\n` 的前半，提前翻成 `\\n`
        会把一个 CRLF 拆成两个换行。
        """
        text = self._carry + text
        if text.endswith("\r"):
            self._carry = "\r"
            text = text[:-1]
        else:
            self._carry = ""
        if not text:
            return ""
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def feed(self, data: bytes) -> str:
        """喂入一段原始字节，返回其中**已能确定**的文本（可能为空串）。"""
        if not data:
            return ""
        if self._decoder is not None:
            # 判定之后绝不能再抛：抛出会被 _drain_stream 的宽 except 吞掉，
            # 导致**流的剩余部分被静默丢弃**。判定后的解码器一律是宽松的
            # （errors="replace"），与旧编码路径的容错等价。
            return self._normalize_newlines(self._decoder.decode(data))

        # 单次喂入不得超过剩余探测预算（调用方靠 `_DRAIN_CHUNK_BYTES <= PROBE_LIMIT`
        # 保证）：否则「已满上限的合法 UTF-8 + 同一段里的坏字节」会因探测先抛而被
        # 误判成兜底编码，与「坏字节落在下一段」的判定结果不一致。
        self._pending += data
        try:
            self._probe_text.append(self._probe.decode(data))
        except UnicodeDecodeError:
            return self._switch_to_fallback()
        if len(self._pending) >= PROBE_LIMIT:
            return self._commit_utf8()
        return ""

    def flush(self) -> str:
        """流结束：吐出剩余文本（含被缓冲的不完整序列与扣住的 `\\r`）。"""
        if self._decoder is not None:
            tail = self._normalize_newlines(self._decoder.decode(b"", True))
        else:
            try:
                # 尾部可能残留不完整序列：严格收尾会抛，说明它不是合法 UTF-8。
                self._probe.decode(b"", True)
            except UnicodeDecodeError:
                tail = self._switch_to_fallback(final=True)
            else:
                tail = self._commit_utf8()
        if self._carry:  # 文件以孤立 `\r` 结束 → 按通用换行语义算作一个换行
            tail += "\n"
            self._carry = ""
        return tail

    def _commit_utf8(self) -> str:
        """判定 UTF-8。

        不直接接管严格探测解码器：它持有「多字节序列不完整」的严格语义，之后遇到
        杂散非法字节会**抛异常**（P1：抛出→宽 except→流剩余部分丢失）。改为记下
        已解出的文本、把探测留下的不完整尾字节交给一个**宽松**解码器继续，
        既保留缓冲状态又不丢后续内容。
        """
        self._encoding = "utf-8"
        text = "".join(self._probe_text)
        self._probe_text.clear()
        # 严格解码器已消费的字节数 = 它吐出的文本按 UTF-8 回编码的长度
        consumed = len(text.encode("utf-8"))
        remainder = bytes(self._pending)[consumed:]
        self._pending.clear()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        tail = self._decoder.decode(remainder) if remainder else ""
        return self._normalize_newlines(text + tail)

    def _switch_to_fallback(self, final: bool = False) -> str:
        """判定兜底编码：丢弃试探出的 UTF-8 文本，重解已缓冲的全部字节。

        `final=True`（来自 flush）时把解码器收尾，否则流末尾挂在回退编码里的
        不完整字节会被无声丢掉。
        """
        self._encoding = self._fallback_encoding
        self._decoder = codecs.getincrementaldecoder(self._fallback_encoding)("replace")
        raw = bytes(self._pending)
        self._pending.clear()
        self._probe_text.clear()
        return self._normalize_newlines(self._decoder.decode(raw, final))
