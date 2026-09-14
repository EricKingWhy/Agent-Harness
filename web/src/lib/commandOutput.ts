/** #190 —— 命令输出的**聚合层**（纯函数，无 DOM、无 React）。
 *
 *  本仓已有两处在读命令输出，但读的不是同一份东西：
 *  - Inspector 的 `TerminalTab`（`StepDetail.tsx`）只读 `tool.result.stdout`，不看流式
 *    `tool.output` 块、也不看 stderr；
 *  - 对话里的工具卡（`ToolCard.tsx` → `ToolOutputStream`）渲染流式 `tool.output` 块
 *    （stdout/stderr 分色、有界尾窗、贴底跟随、全量复制）。
 *
 *  #190 的中心「输出」面不能自己再写第三份（票面 AC9：同一数据不得两份独立渲染）。
 *  所以这里只把"哪些调用算命令、它们的输出是什么"定成**一份纯数据**，渲染交给既有的
 *  `ToolOutputStream`。
 *
 *  终态优先级（与投影层注释同一口径——"终态顺序由 result 真相恢复"）：
 *  1. 有终态 `stdout` / `stderr` → 以 result 为准（权威终态文本，含顺序）；
 *  2. 终态里没有输出（还在跑、或被中断/取消）→ 回落流式块——否则**正在跑的命令在面板里
 *     会是一片空白**，而它明明是唯一一个"现在就有输出"的命令；
 *  3. 两者都没有 → 空块：渲染层只显示命令与状态，不编内容。
 *
 *  ⚠ 被外置（overflow）过的结果里，`stdout` 已被后端换成"摘要 + `use read_artifact(<id>)`
 *  标记"，这里**原样显示**。把标记解析成可点的入口是 #186 的活（两端 marker 文案统一也在
 *  那张票），本票不碰——也不在这里猜第二套 marker 形状。
 */

import type { ToolCall, ToolOutputChunk } from '../types';

export interface CommandOutput {
  toolCallId: string;
  /** 命令原文（`args.command`）。缺失即空串——不伪造。 */
  command: string;
  /** 输出块（channel 保真，顺序 = stdout 后 stderr / 或流式到达顺序）。 */
  chunks: ToolOutputChunk[];
  exitCode: number | null;
  /** 调用终态（running / success / failed / stopped）——面板据此如实说明状态。 */
  status: ToolCall['status'];
  /** 是否仍在流式（渲染器据此贴底跟随 + 画光标）。已终态的调用一律 false。 */
  streaming: boolean;
}

/** 只认 `name === 'bash'`：其余工具（read/write/edit…）的产出不是"命令输出"。
 *
 *  **与 Inspector 的 `TerminalTab` 共用这一个判定**（票面 AC2 要求复用既有聚合逻辑）：
 *  "什么算一次命令"只能有一处答案，否则两边会各自演化。 */
export function isCommand(tool: ToolCall): boolean {
  return tool.name === 'bash';
}

/** 命令的终态读取（`result` 里 `exit_code` / `stdout` / `stderr`）。
 *
 *  形状刻意与 TerminalTab 原来的私有 `bashResult` 一致（字段可缺省 = `undefined`）——
 *  两边共用同一份读取，Inspector 的渲染判断因此可以逐字不变（AC7）。
 *  后端 `ToolResult.data` 里三个字段的真实来源：`tools/bash.py:126-132`。 */
export function commandResult(tool: ToolCall): {
  exit_code?: number;
  stdout?: string;
  stderr?: string;
} | null {
  if (typeof tool.result !== 'object' || tool.result === null) return null;
  const r = tool.result as Record<string, unknown>;
  return {
    exit_code: typeof r.exit_code === 'number' ? r.exit_code : undefined,
    stdout: typeof r.stdout === 'string' ? r.stdout : undefined,
    stderr: typeof r.stderr === 'string' ? r.stderr : undefined,
  };
}

/** 终态文本 → 输出块。空字符串**不成块**（不该渲染一个空的 stderr 块）。 */
function chunksFromResult(result: ReturnType<typeof commandResult>): ToolOutputChunk[] | null {
  if (result === null) return null;
  const chunks: ToolOutputChunk[] = [];
  for (const channel of ['stdout', 'stderr'] as const) {
    const text = result[channel];
    if (typeof text === 'string' && text !== '') chunks.push({ channel, text });
  }
  return chunks.length > 0 ? chunks : null;
}

export function commandOutputs(tools: readonly ToolCall[]): CommandOutput[] {
  return tools.filter(isCommand).map((tool) => {
    const result = commandResult(tool);
    const fromResult = chunksFromResult(result);
    const live = tool.output ?? [];
    const streaming = tool.status === 'running';
    return {
      toolCallId: tool.tool_call_id,
      command: tool.args.command === undefined ? '' : String(tool.args.command),
      chunks: fromResult ?? live,
      exitCode: result?.exit_code ?? null,
      status: tool.status,
      // 终态调用即便还留着流式块也不再跟随（内容已经定格）。
      streaming,
    };
  });
}

/** 复制用文本：全部块按序拼接（stdout + stderr 都在——只复制 stdout 会漏掉报错）。 */
export function commandOutputText(output: CommandOutput): string {
  return output.chunks.map((c) => c.text).join('');
}
