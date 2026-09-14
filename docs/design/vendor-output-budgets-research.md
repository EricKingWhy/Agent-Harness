# 厂商设计研究：工具输出预算 + 沙箱协作取消（R8-2 / C1 / C2 实施依据）

> 来源：用户拍板后授权的研究（参考 oh-my-pi / pi-mono / deepseek-harness / Claude Code / Codex）。
> 本文件是 R8-2（read/grep 输出预算）、C1（协作取消）、C2（env 白名单）的设计依据。

## 一、输出预算推荐数字（业界实测值）

| 工具 | 上限 | 来源 |
|---|---|---|
| read 文件 | 2000 行 或 50KB（先到为准） | pi-mono `packages/agent/src/harness/utils/truncate.ts`（`DEFAULT_MAX_LINES=2000`，`DEFAULT_MAX_BYTES=50KB`）；Claude Code Read 同为 2000 行 |
| grep | 100 个 match（`limit` 可调）、单行 500 字符、总量 50KB | pi-mono `tools/grep.ts`；oh-my-pi 放宽到 3000 行 / 单行 512 列（`session/streaming-output.ts`） |
| bash/命令输出 | 保留**尾部** 2000 行/50KB（错误在尾部）+ 全量落盘 spill | pi-mono `bash-executor.ts`（`truncateTail` + `fullOutputPath`）；Codex CLI 256 行/10KiB head+tail（openai/codex#6426）；Claude Code Bash 30000 字符 |
| 兜底总闸 | 对所有 tool 最终文本结果统一 maxInlineBytes≈50KB，超出 head/tail 预览 + spill | deepseek-harness `2026-07-08-tool-output-spill-files.md` |

关键分层（dsh 明确区分）：**资源上限**（保护网络/内存）≠ **上下文上限**（保护模型 context）。
spill 策略**跳过 read 工具**避免 `read→spill→再read` 死循环。

## 二、截断标记格式（对模型有效的是"可执行的下一步"）

- read 行数截断：`[Showing lines 1-2000 of 8500. Use offset=2001 to continue.]`；字节截断额外标注 limit
- bash：`[Showing lines X-Y of N. Full output: /tmp/pi-output-xxx.log]`（spill 路径给模型，可二次检索）
- grep：`[100 matches limit reached. Use limit=200 for more, or refine pattern. Some lines truncated to 500 chars.]`；行内截断后缀 `... [truncated]`
- dsh 版本：`(Omitted N bytes. Full formatted result stored at: <path>. Use read with offset/limit, or grep this path.)`
- dsh 失败语义：spill 写盘失败时**返回原结果不截断**，绝不把成功调用变成 error

## 三、分页 vs 简单截断

- **read：加 offset/limit，值得。** pi-mono 与 Claude Code 都采用；dsh 把 read 的行窗口契约
  （行号、totalLines、offset 越界报错、字节帽中途停扫）独立于通用截断——分页是 read 的领域语义。
- **grep：不加分页，用 match 数上限**（命中即杀扫描），提示"refine pattern"。
- **bash：不加分页，用 tail + spill 文件**（错误/结果在尾部）。

## 四、协作取消：从 asyncio 超时打通到子进程

**本仓现状**：`tools/bash.py` 用 `asyncio.to_thread(sandbox.exec, ...)`，executor 用
`asyncio.timeout` 包 await——取消只取消 await，线程里的 subprocess 继续跑。

**dsh 核心原则**（`2026-07-19-cooperative-tool-cancellation.md`）：**绝不 race 工具 promise 后弃之
不管**——取消信号必须驱动工具"到静默（quiescence）"才结算；区分 `ABORTED_BEFORE_DISPATCH`
（未进工具体，无副作用）与 `ABORTED`（可能已有副作用）——与本仓 Operation Ledger 的 reconcile 直接对应。

**推荐接线（Python 版 pi-mono 模式）**，来源 pi-mono `env-nodejs.ts`：

1. 弃用 `asyncio.to_thread(subprocess.run)`，改 `Popen(start_new_session=True)`（POSIX 成组长）+
   `asyncio.wait_for(proc.communicate(), timeout)`，在 `except (TimeoutError, CancelledError)` 中
   **同步地**调 kill（复用本仓 `local.py::_kill_process_tree`），等进程收敛再结算结果。
2. 升级阶梯（pi-mono：SIGTERM→5s→SIGKILL；omp：TERM 波→graceful_ms(1000)→KILL 波）：
   本仓已有 taskkill/killpg 整树击杀，补 TERM→宽限→KILL 两段式；Windows `taskkill /T /F` 一步到位。
3. 取消后**保留已产出输出**并结算为结构化结果：结果带 `cancelled/timedOut` 标志（pi-mono
   `BashResult{cancelled, timedOut, exitCode:undefined}` 模式），模型能看到被杀前的 stdout。
4. 收尾防悬挂：exit 后对 stdio 管道加短闲时宽限再关读取器，防孙进程握管道丢尾行（pi-mono#5303）。

## 五、oh-my-pi 值得移植的点

1. **CancelToken 三因设计**（`pi-shell/cancel.rs`）：reason 枚举（Timeout/Signal/User/Unknown）+
   `heartbeat()` 协作检查点。Python 等价 = `threading.Event` + 原因字段。
2. **基线快照 + 终止波**：取消时对"启动后新出现的后代"按快照差集发 TERM→2s→KILL；安全护栏：
   拒绝 kill 自己所属进程组。
3. **输出管线**：`TailBuffer(50KB)` 滚动缓冲 + 内联帽 + 截断即写 artifact（复用同一 artifact id）。
4. **超时后读尾**：命令结束后再等"250ms 无新输出或 2s 上限"才关读取器，防尾行竞态。

## 六、落地建议（对应本仓最小改动）

- Feature 1（R8-2）：read 工具加 `offset/limit` + `Use offset=N to continue.` 标记；grep 加 match
  上限提前终止 + 单行 500 字符截断；bash 保留尾 50KB + spill 路径写进结果文本。所有上限写进工具
  description 让模型自知。
- Feature 2（C1）：`bash.py` 改 Popen + `asyncio.wait_for(communicate)`，cancel 路径复用
  `local.py::_kill_process_tree`，TERM→2s→KILL 阶梯；结果带 `cancelled/timedOut` 标志并保留已捕获输出。

**参考来源**：pi-mono（badlogic/pi-mono）；oh-my-pi（can1357/oh-my-pi）；deepseek-harness
（`.agents/notes/implemented/architecture/2026-07-{06,07,08,19}`）；Claude Code tools-reference；
openai/codex#6426。
