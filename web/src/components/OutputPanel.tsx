/** 中心列「输出」面（#190）。
 *
 *  **为什么不叫 Terminal**：本项目**没有 PTY**——命令是一次性 `subprocess` 执行，输出经
 *  `tool/output_delta` 合帧推来。叫 Terminal 等于承诺一个不存在的输入能力（撞 PRD
 *  "不得伪造"）。业界只读输出的先例都叫 Console / Logs / Tasks / Progress（PRD §3.0），
 *  所以这里叫「输出」。面内**明示**这一点（AC1）——不是免责声明，是如实描述能力边界。
 *
 *  **与别处的关系**：
 *  - 聚合只有一份（`lib/commandOutput.ts`）；渲染只有一份（`ToolOutputStream`，与对话里的
 *    工具卡同一个组件）——票面 AC9 禁止"同一数据两份独立渲染"；
 *  - Inspector 的 `TerminalTab`（`StepDetail.tsx`）本票**不动**（AC7：那边 #183 还要用）。
 *
 *  **不得出现任何暗示可输入的元素**（AC5）：无 textarea / input / contenteditable、无"运行"
 *  按钮、无光标。这是本面的核心约束——一个看起来能敲命令的面板，就是在骗人。
 */
import { ScrollText } from 'lucide-react';
import type { ToolCall } from '../types';
import { commandOutputs } from '../lib/commandOutput';
import { ToolOutputStream } from './ToolOutputStream';

/** 命令执行状态 → 人话。只列非成功态：成功由 exit code 承担（`exit 0` 比"成功"信息量大）。 */
const STATUS_LABEL: Partial<Record<ToolCall['status'], string>> = {
  running: '运行中…',
  failed: '失败',
  stopped: '已中断',
};

export function OutputPanel({ tools }: { tools: readonly ToolCall[] }) {
  const outputs = commandOutputs(tools);

  return (
    <div className="output-panel" role="region" aria-label="输出">
      {/* AC1：面内明示只读 + 原因。**两个分支都要有**——空态也是这个面的一部分，
          不能在"没有输出"时就把能力边界那句话收起来。`role="note"` 让读屏知道这是说明。 */}
      <p className="output-note" role="note">
        只读：本项目命令为一次性执行，无交互终端（不能在此输入或重跑）。
      </p>
      {outputs.length === 0 ? (
        <div className="detail-tab-empty">
          {/* 中性图标：这个面的存在理由就是"不要看起来像终端"（PRD §3.5）。 */}
          <ScrollText size={24} className="detail-empty-icon" aria-hidden="true" />
          <div className="detail-empty-hint">本次会话未执行命令——没有输出可显示。</div>
        </div>
      ) : (
        <ol className="output-list">
          {outputs.map((output, i) => (
            <li className="output-item" key={output.toolCallId}>
              <div className="output-item-head">
                {/* 序号让"第几次命令"可指认（复制/排查时对得上）。 */}
                <span className="output-item-index">#{i + 1}</span>
                <code className="output-item-cmd">
                  <span className="bash-prompt">$</span> {output.command || '(命令文本缺失)'}
                </code>
                {output.exitCode !== null && (
                  <span
                    className={`exit-badge ${output.exitCode === 0 ? 'exit-ok' : 'exit-err'}`}
                  >
                    exit {output.exitCode}
                  </span>
                )}
                {STATUS_LABEL[output.status] && (
                  <span className="output-item-status">{STATUS_LABEL[output.status]}</span>
                )}
                {/* 复制按钮在输出块自己的工具条里（「复制全部输出」）——**不在头部再放一个**：
                    同一段文本两个复制按钮只会让人犹豫点哪个。 */}
              </div>
              {output.chunks.length > 0 ? (
                // 同一渲染器（对话里的工具卡也是它）：stdout/stderr 分色、有界尾窗、
                // 全量复制。长输出**就地**折叠/展开（AC3），不新开导航面。
                // `showCaret={false}`：AC5 明令面上不得出现任何"可输入"的暗示，流式光标
                // 正是终端提示符的样子——运行中用头部那句"运行中…"如实表达即可。
                <ToolOutputStream chunks={output.chunks} streaming={output.streaming} showCaret={false} expandable />
              ) : (
                <div className="output-item-empty">
                  {/* 在跑 ≠ 没有输出：说成"没有输出"是假事实（PRD §4 No fake values）。 */}
                  {output.status === 'running' ? '等待输出…' : '这次命令没有输出。'}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
