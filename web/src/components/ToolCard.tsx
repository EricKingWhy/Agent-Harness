/** ToolCard — per-tool renderer with specialized layouts.
 *
 * L0-L2 Progressive Disclosure（PRD §6，ADR-0014 D2）：
 *   - L0 → summary row only（status/icon/name/args/duration）
 *   - L1 → + Input/Output inline detail
 *   - L2 → + full content surface（bash/diff/read/slice 专属块）+ raw event JSON
 * 生效级 = App 层 manual override ?? 全局 density 默认；点击行循环 L0→L1→L2。
 * hover "Inspect" chip → 进 Inspector（PRD §9.1 联动）。
 *
 * Four content shapes (L2):
 *   - bash → terminal block (mono, dark inset, exit code badge)
 *   - edit/apply_patch/write → diff view (green/red, before/after)
 *   - inspect_artifact → artifact slice view (numbered lines, per-line truncation chips)
 *   - read → continuation-aware block；everything else → generic JSON card
 *
 * Status color: running=warning, success=green, failed=red.
 */

import { memo } from 'react';
import { Check, Scissors, Square, X } from 'lucide-react';
import type { ToolCall } from '../types';
import type { TraceDensity } from '../lib/density';
import { defaultLevelFor, type DisclosureLevel } from '../lib/disclosure';
import { formatDuration, stringifyForDisplay, truncateForDisplay } from '../lib/format';
import { KIND_ICON, toolKind } from '../lib/eventKind';
import {
  GREP_TRUNCATED_SUFFIX,
  hasGrepTruncatedSuffix,
  parseErrorShape,
  parseReadShape,
  splitMcpToolName,
  stripGrepTruncatedSuffix,
  type ReadShape,
} from '../lib/toolShapes';
import { CopyButton } from './CopyButton';
import { ToolOutputStream } from './ToolOutputStream';
import { ArtifactViewer } from './ArtifactViewer';
import { DiffBlock } from './DiffBlock';
import { JsonTree } from './JsonTree';

interface Props {
  tool: ToolCall;
  density: TraceDensity;
  /** 生效展开级（override ?? density 默认）。缺省 = density 推导（未接 disclosure 的旧用法）。 */
  level?: DisclosureLevel;
  /** 点击行 → 循环 L 级（App 层 setLevel(nextLevel)）。缺省回退旧行为。 */
  onCycleLevel?: () => void;
  /** hover Inspect chip 点击 → 进 Inspector。缺省时点击行为回退（旧：onFocus / 本地展开）。 */
  onFocus?: (tool: ToolCall) => void;
  /** #186：归档 diff 的「就地展开」要按会话读 artifact 内容。缺省 = 不提供展开入口。 */
  sessionId?: string;
}

// memo：投影层 copy-on-write 保证未触及的 tool 引用稳定——同 turn 内其它工具卡
// 在本工具更新时跳过重渲染（配合 App 层 useCallback 稳定的回调）。
export const ToolCard = memo(function ToolCard({ tool, density, level, onCycleLevel, onFocus, sessionId }: Props) {
  const isBash = tool.name === 'bash';
  const isDiffTool = ['edit', 'apply_patch', 'write'].includes(tool.name);
  const slice = tool.name === 'inspect_artifact' ? tryParseSlice(tool.result) : null;
  // read 新形状（df4f7d8 §1.3）：解析续读/单行截断标记；形状不符回退 GenericBlock。
  const readShape = tool.name === 'read' ? parseReadShape(tool.result) : null;
  const duration = formatDuration(tool.started_at, tool.completed_at);
  // 生效 L 级：显式 level 优先，否则 density 推导（旧契约：detailed/raw 展开明细）。
  const effectiveLevel: DisclosureLevel = level ?? defaultLevelFor(density);
  const hasInspect = Boolean(onFocus);
  // PRD §5.2/§10.2：语义图标按工具 kind 分发（终端/查阅/写入/MCP/扳手），
  // 替换原 bash/其它 二分；状态仍由 act-status 列表达（中断 ≠ 错误）。
  const KindIcon = KIND_ICON[toolKind(tool.name)];
  // 失败摘要（PRD §5.2 Error：第二行 error_code 摘要，不满屏红、不强制展开）。
  const errorShape = tool.status === 'failed' ? parseErrorShape(tool.result) : null;

  const handleRowClick = () => {
    if (onCycleLevel) {
      onCycleLevel();
      return;
    }
    // 旧回退（未接 disclosure 的用法）：点击 = 进 Inspector。
    onFocus?.(tool);
  };

  return (
    <>
      {/* data-stream-key：Main↔Inspector 联动定位锚（PRD §9.2 反向跳转目标）+ pulse */}
      <div
        className={`act-node-wrap${tool.status === 'failed' ? ' act-node-wrap-error' : ''}`}
        data-stream-key={`tool:${tool.tool_call_id}`}
      >
        <button
          className={`act-node act-node-${density}`}
          onClick={handleRowClick}
          aria-level={effectiveLevel}
          aria-expanded={effectiveLevel > 0}
        >
          <span className={`act-status act-status-${tool.status}`}>
            {tool.status === 'success' && <Check size={14} />}
            {tool.status === 'failed' && <X size={14} />}
            {tool.status === 'stopped' && <Square size={14} />}
            {tool.status === 'running' && <span className="status-spinner" />}
          </span>
          {density !== 'compact' && <span className="act-icon"><KindIcon size={14} /></span>}
        {/* MCP 工具名（da394a9 Phase 8）：mcp__{server}__{tool} 拆 server 徽章 + 工具名 */}
        {(() => {
          const mcp = splitMcpToolName(tool.name);
          return mcp ? (
            <span className="act-name">
              <span className="act-server" title={`MCP server: ${mcp.server}`}>{mcp.server}</span>
              {mcp.tool}
            </span>
          ) : (
            <span className="act-name">{tool.name}</span>
          );
        })()}
        {density !== 'compact' && <span className="act-args">{summarizeArgs(tool)}</span>}
        {duration && <span className="act-duration">{duration}</span>}
        {density === 'compact' && (
          <span className="act-args act-args-compact">{summarizeArgs(tool, 32)}</span>
        )}
        </button>
        {/* hover Inspect chip（PRD §9.1）：点击进 Inspector 联动，不触发行点击。
            真按钮（code-review P0：span+tabIndex=-1 键盘不可达）——Tab 聚焦后
            Enter/Space 原生触发，:focus-visible 时浮现（样式已覆盖）。 */}
        {hasInspect && (
          <button
            type="button"
            className="act-inspect-chip"
            onClick={(e) => {
              e.stopPropagation();
              onFocus?.(tool);
            }}
          >
            Inspect
          </button>
        )}
      </div>

      {/* T3（#96）：流式输出尾窗——running 渲染 chunks 活流（S14 活流不需展开）；
          终态以 result 校准（契约 C2「tool/result 终态全量兜底」——delta 缺口/
          重连丢失时 partial chunks 不得永久遮蔽全量），result 无可渲染输出时
          chunks 兜底。chunks 数据本身永不清除（events/raw 可查）。 */}
      {tool.output && tool.output.length > 0 && (tool.status === 'running' || !tool.result) && (
        <ToolOutputStream chunks={tool.output} streaming={tool.status === 'running'} />
      )}

      {/* 失败摘要行（PRD §5.2 Error：TIMEOUT · 10.0s 式轻量摘要）——保持折叠，
          只给关键错误信号；完整 Raw 留给 Inspector（D6：失败不强制全展开）。 */}
      {errorShape && (
        <div className="act-error-summary" role="status">
          <span className="act-error-code">{errorShape.errorCode}</span>
          {errorShape.message && <span className="act-error-msg">{truncate(errorShape.message, 120)}</span>}
        </div>
      )}

      {/* L1 inline detail：Input/Output 摘要（C3 微标签分区，与 Inspector io-tabs 同语言）。 */}
      {effectiveLevel >= 1 && (
        <div className="act-detail-inline">
          <div className="act-field">
            <div className="act-field-label">Input</div>
            <pre className="act-detail-args">{JSON.stringify(tool.args, null, 2)}</pre>
          </div>
          {tool.result !== undefined && (
            <div className="act-field">
              <div className="act-field-label">Output</div>
              <pre className="act-detail-result">
                {truncate(
                  typeof tool.result === 'string' ? tool.result : JSON.stringify(tool.result, null, 2),
                  400,
                )}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* L2 advanced inline：完整内容面（四形态专属块）+ 原始事件 JSON。 */}
      {effectiveLevel >= 2 && (
        <div className="tool-card-body">
          {isBash && <BashBlock tool={tool} />}
          {isDiffTool && tool.diff && <DiffBlock diff={tool.diff} sessionId={sessionId} />}
          {slice && <ArtifactSliceBlock slice={slice} />}
          {readShape && <ReadBlock shape={readShape} />}
          {!isBash && !isDiffTool && !slice && !readShape && <GenericBlock tool={tool} />}
          {/* 被截断处的「就地展开」（#186 AC2）：判据用**投影**挂上的 `tool.artifact`
              （来自 `artifact/externalized`），不在视图里解析 marker——标记长什么样是
              后端的事，前端只认投影这一份真相（AC7 / 不变量 #22）。与 Artifacts 清单
              共用 `ArtifactViewer`，不新开导航面。
              这里同时覆盖命令输出与通用结果两条外置路径（不需要各写一遍）。

              归档 diff 例外：那一份已经由上面的 `DiffBlock` 给了展开入口（`tool.diff`
              归档时，内容就是同一个 artifact），再渲染一次会变成两个同名同效的按钮。 */}
          {tool.artifact && sessionId && !(isDiffTool && tool.diff?.archived) && (
            <ArtifactViewer
              sessionId={sessionId}
              artifactId={tool.artifact.artifact_id}
              label="查看完整内容"
            />
          )}
        </div>
      )}
      {effectiveLevel >= 2 && (tool.raw_call || tool.raw_result) && (
        <div className="act-raw">
          {tool.raw_call && (
            <div className="act-raw-section">
              <div className="act-raw-label">tool/call 原始事件</div>
              <pre>{JSON.stringify(tool.raw_call, null, 2)}</pre>
            </div>
          )}
          {tool.raw_result && (
            <div className="act-raw-section">
              <div className="act-raw-label">tool/result 原始事件</div>
              <pre>{JSON.stringify(tool.raw_result, null, 2)}</pre>
            </div>
          )}
        </div>
      )}
    </>
  );
});

function summarizeArgs(tool: ToolCall, max = 60): string {
  const a = tool.args;
  if (tool.name === 'bash') return String(a.command ?? '').slice(0, max);
  if ('path' in a) return String(a.path);
  const entries = Object.entries(a).slice(0, 2);
  return entries.map(([k, v]) => `${k}=${truncate(JSON.stringify(v), 30)}`).join(' ');
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function BashBlock({ tool }: { tool: ToolCall }) {
  const cmd = String(tool.args.command ?? '');
  const out = typeof tool.result === 'string' ? tool.result : JSON.stringify(tool.result ?? '', null, 2);
  const exitCode = (tool.result as { exit_code?: number } | string | undefined);
  const code = typeof exitCode === 'object' && exitCode ? exitCode.exit_code : undefined;
  // bash 被取消（data.cancelled，df4f7d8 §1.3）——展示"已取消"而非普通失败
  // （投影层已把 status 映射为 stopped；这里补明确文案，注明后端保证的语义）。
  const cancelled = (tool.result as { cancelled?: boolean } | null | undefined)?.cancelled === true;

  return (
    <div className="bash-block">
      <div className="bash-cmd-line">
        <span className="bash-prompt">$</span>
        <code>{cmd}</code>
      </div>
      {/* T3（#96）：仅 running+chunks 时屏蔽 result 输出行（活流双写）；
          终态由 result 校准渲染（stream 区已退位，无双写）。 */}
      {!(tool.status === 'running' && tool.output?.length) && out && (
        <pre className="bash-output">{truncateForDisplay(out)}</pre>
      )}
      {cancelled && (
        <span className="bash-cancelled" title="命令被超时/断连取消，进程树已终止">
          已取消
        </span>
      )}
      {code !== undefined && (
        <span className={`exit-badge ${code === 0 ? 'exit-ok' : 'exit-err'}`}>exit {code}</span>
      )}
    </div>
  );
}

function GenericBlock({ tool }: { tool: ToolCall }) {
  const resultIsObject = typeof tool.result === 'object' && tool.result !== null;
  return (
    <div className="generic-block">
      <div className="generic-section">
        <div className="generic-label">参数</div>
        <div className="detail-json">
          <JsonTree value={tool.args} />
        </div>
      </div>
      {tool.result !== undefined && (
        <div className="generic-section">
          <div className="generic-label">结果</div>
          {resultIsObject ? (
            <div className="detail-json">
              <JsonTree value={tool.result} />
            </div>
          ) : (
            <TruncationAwarePre
              text={truncateForDisplay(stringifyForDisplay(tool.result))}
              className="generic-result"
            />
          )}
        </div>
      )}
    </div>
  );
}

/** 逐行渲染并把 grep 截断尾巴（`... [truncated]`，单行 >500 字符，df4f7d8 §1.3）
 *  弱化为静音标记——内容是真实的，但视觉上明确"此处有省略"，不与正文混淆。 */
function TruncationAwarePre({ text, className }: { text: string; className?: string }) {
  if (!text.includes(GREP_TRUNCATED_SUFFIX)) return <pre className={className}>{text}</pre>;
  const lines = text.split('\n');
  return (
    <pre className={className}>
      {lines.map((line, i) => {
        const cut = hasGrepTruncatedSuffix(line);
        return (
          <span key={i}>
            {cut ? (
              <>
                {stripGrepTruncatedSuffix(line)}
                <span className="trunc-suffix" title="该行因超长被截断">{GREP_TRUNCATED_SUFFIX}</span>
              </>
            ) : (
              line
            )}
            {i < lines.length - 1 ? '\n' : ''}
          </span>
        );
      })}
    </pre>
  );
}

// ── read 专用渲染（df4f7d8 §1.3：续读标记 / 单行截断 / 空文件）──

function ReadBlock({ shape }: { shape: ReadShape }) {
  // 空文件是正常成功（content:"" + total_lines:0），不渲染成失败或空泡。
  const empty = shape.content === '' && (shape.totalLines === null || shape.totalLines === 0);
  return (
    <div className="read-block">
      <div className="read-meta">
        {empty && <span className="read-empty">空文件（0 行）</span>}
        {!empty && shape.totalLines !== null && (
          <span className="read-total">共 {shape.totalLines.toLocaleString()} 行</span>
        )}
        {shape.continuation && (
          <span className="read-range">
            已显示 {shape.continuation.shownFrom}–{shape.continuation.shownTo} 行
          </span>
        )}
        {shape.lineTruncated && (
          <span
            className="read-line-trunc"
            title="该行超过 51200 字节被截断，不可续读——需用 bash 分段读取"
          >
            第 {shape.lineTruncated.line} 行超长截断（{shape.lineTruncated.bytes.toLocaleString()} 字节）· 不可续读
          </span>
        )}
      </div>
      {!empty && shape.content !== '' && <pre className="read-content">{truncateForDisplay(shape.content)}</pre>}
      {shape.continuation && (
        <div className="read-continue">
          <span className="read-continue-hint">续读参数（下一次 read 调用的 offset）</span>
          <code className="read-continue-code">offset={shape.continuation.nextOffset}</code>
          <CopyButton text={`offset=${shape.continuation.nextOffset}`} label="复制续读 offset" />
        </div>
      )}
    </div>
  );
}

// ── inspect_artifact 专用渲染 ──

/** 后端 ArtifactSlice.lines 的单行 item 形状（spec 06 §4 / storage/artifact.py）。
 *  超长行截断后额外携带 truncated=true + full_length（原始字符数）。 */
interface SliceLine {
  line_number: number;
  text: string;
  truncated?: boolean;
  full_length?: number;
}

interface SliceData {
  artifact_id: string;
  lines: SliceLine[];
  total_lines: number;
  returned_lines: number;
  truncated: boolean;
}

/** 从 ToolResult 中解析 ArtifactSlice（data 字段经 tryParseContent 已是对象）。
 *  形状不符（失败结果 / 旧数据）返回 null，回退 GenericBlock。 */
function tryParseSlice(result: unknown): SliceData | null {
  if (typeof result !== 'object' || result === null) return null;
  const r = result as Record<string, unknown>;
  if (!Array.isArray(r.lines)) return null;
  const lines = r.lines.filter(
    (l): l is SliceLine =>
      typeof l === 'object' && l !== null &&
      typeof (l as Record<string, unknown>).line_number === 'number' &&
      typeof (l as Record<string, unknown>).text === 'string',
  );
  if (lines.length === 0) return null;
  return {
    artifact_id: String(r.artifact_id ?? ''),
    lines,
    total_lines: Number(r.total_lines ?? 0),
    returned_lines: Number(r.returned_lines ?? lines.length),
    truncated: r.truncated === true,
  };
}

function ArtifactSliceBlock({ slice }: { slice: SliceData }) {
  const truncatedCount = slice.lines.filter((l) => l.truncated).length;
  return (
    <div className="slice-block">
      <div className="slice-meta">
        <span className="slice-meta-item">共 {slice.total_lines} 行</span>
        {slice.truncated && <span className="slice-meta-item">返回 {slice.lines.length} 行</span>}
        {truncatedCount > 0 && (
          <span className="slice-trunc-chip">
            <Scissors size={14} />
            {truncatedCount} 行超长截断 · 可放宽 max_chars_per_line 重读
          </span>
        )}
      </div>
      <div className="slice-lines">
        {slice.lines.map((l) => (
          <div key={l.line_number} className={`slice-line ${l.truncated ? 'slice-line-trunc' : ''}`}>
            <span className="slice-line-no">{l.line_number}</span>
            <code className="slice-line-text">{l.text}</code>
            {l.truncated && (
              <span className="slice-line-chip" title={`原始 ${l.full_length ?? '?'} 字符，当前显示前 2000`}>
                …{l.full_length ?? '?'} 字符
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
