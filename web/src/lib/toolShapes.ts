/** lib/toolShapes — 工具结果新形状的纯解析（后端 df4f7d8 硬化批次 §1.3）。
 *
 * 后端在 ToolResult.data 里用文本标记表达截断/续读语义；这里把标记解析成
 * 结构化事实，渲染层（ToolCard）据此出提示。纯函数、可测、零伪造——标记
 * 不匹配就返回 null 回退通用渲染，绝不猜。
 */

export interface ReadContinuation {
  /** 本次已显示的行范围（1-based，含端点）。 */
  shownFrom: number;
  shownTo: number;
  /** 文件总行数（后端 data.total_lines 真值）。 */
  totalLines: number;
  /** 续读起始 offset（= shownTo + 1，read 的 1-based 参数）。 */
  nextOffset: number;
}

export interface ReadShape {
  /** 去掉尾部标记后的正文（无标记时即原文）。 */
  content: string;
  /** 后端 data.total_lines（缺失为 null——不伪造）。 */
  totalLines: number | null;
  /** 续读标记解析结果（无标记 null）。 */
  continuation: ReadContinuation | null;
  /** 单行超长截断标记（不可续读）：{ line, bytes } 或 null。 */
  lineTruncated: { line: number; bytes: number } | null;
}

const CONTINUATION_RE = /\[Showing lines (\d+)-(\d+) of (\d+)\. Use offset=(\d+) to continue\.\]\s*$/;
const LINE_TRUNCATED_RE = /\[Line (\d+) truncated at (\d+) bytes[^\]]*\]\s*$/;

/** 解析 read 工具的 data（{ content?, total_lines? }）。形状不符返回 null。 */
export function parseReadShape(data: unknown): ReadShape | null {
  if (typeof data !== 'object' || data === null) return null;
  const d = data as Record<string, unknown>;
  if (typeof d.content !== 'string') return null;
  const content = d.content;
  const totalLines = typeof d.total_lines === 'number' && Number.isFinite(d.total_lines) ? d.total_lines : null;

  const contMatch = CONTINUATION_RE.exec(content);
  let continuation: ReadContinuation | null = null;
  let body = content;
  if (contMatch) {
    const shownFrom = Number(contMatch[1]);
    const shownTo = Number(contMatch[2]);
    const total = Number(contMatch[3]);
    const nextOffset = Number(contMatch[4]);
    if ([shownFrom, shownTo, total, nextOffset].every(Number.isFinite)) {
      continuation = { shownFrom, shownTo, totalLines: total, nextOffset };
      body = content.slice(0, contMatch.index).replace(/\n$/, '');
    }
  }

  let lineTruncated: ReadShape['lineTruncated'] = null;
  const lineMatch = LINE_TRUNCATED_RE.exec(body);
  if (lineMatch) {
    const line = Number(lineMatch[1]);
    const bytes = Number(lineMatch[2]);
    if (Number.isFinite(line) && Number.isFinite(bytes)) {
      lineTruncated = { line, bytes };
      body = body.slice(0, lineMatch.index).replace(/\n$/, '');
    }
  }

  return { content: body, totalLines, continuation, lineTruncated };
}

/** grep 匹配行尾标记（单行 >500 字符被后端截断）。 */
export const GREP_TRUNCATED_SUFFIX = '... [truncated]';

/** 行是否以截断尾巴结束（渲染层把尾巴弱化为静音标记）。 */
export function hasGrepTruncatedSuffix(line: string): boolean {
  return line.endsWith(GREP_TRUNCATED_SUFFIX);
}

/** 剥离行尾截断尾巴，返回正文（无尾巴时原样返回）。
 *  标记语义归 toolShapes 单点所有——渲染层不再手写 slice 偏移。 */
export function stripGrepTruncatedSuffix(line: string): string {
  return hasGrepTruncatedSuffix(line) ? line.slice(0, -GREP_TRUNCATED_SUFFIX.length) : line;
}

// ── da394a9 批：diff 归档 marker / MCP 工具名 ──

/** 失败工具的 L0 错误摘要形状（PRD §5.2：× bash sleep 25 / TIMEOUT · 10.0s）。
 *  后端 ToolResult 序列化形状 {ok, message, error_code, ...}；形状不符返回 null
 *  ——零伪造，解析不出就退回通用渲染。 */
export interface ErrorShape {
  errorCode: string;
  message: string;
}

/** 从 tool.result（tryParseContent 后的对象）提取错误摘要。ok=true / 非对象 / 无
 *  error_code 都返回 null（成功与未知形状不是错误摘要）。 */
export function parseErrorShape(result: unknown): ErrorShape | null {
  if (typeof result !== 'object' || result === null) return null;
  const r = result as Record<string, unknown>;
  if (r.ok === true) return null;
  const errorCode = typeof r.error_code === 'string' && r.error_code ? r.error_code : null;
  if (!errorCode) return null;
  const message = typeof r.message === 'string' ? r.message : '';
  return { errorCode, message };
}


/** 后端外置摘要里的读回提示（#186 AC4）。
 *
 *  **两个工具名都要认**：后端按"与本 store 配对的读回工具"决定用哪个名字
 *  （`storage/artifact_select.py`：S3 → `inspect_artifact`，MinIO / Local →
 *  `read_artifact`，而 Local 是默认 Provider）。此前这里只认 `inspect_artifact`，
 *  于是**默认部署**的 marker 一个都解析不出来 ⇒ `archived` 永远为 false ⇒ 界面上的
 *  归档占位与"统计不可得"全是死路径（批 2 审查发现）。只认一个名字，等于在前端把
 *  "这个部署用哪个 store"又猜了一遍。
 *
 *  捕获组：1 = 工具名（**原样保留**，回显与复制都用它，模型才调得到对的那个），
 *  2 = artifact_id。 */
const ARTIFACT_MARKER_RE = /use (inspect_artifact|read_artifact)\(([^)]+)\)/;

export interface ArtifactMarker {
  /** 后端建议的读回工具名——照抄，不要在前端替换成另一个。 */
  toolName: string;
  artifactId: string;
}

/** 从 diff / 工具结果的截断摘要中提取归档引用（后端 >2000 字符时内嵌 marker）。
 *  无 marker 返回 null——零伪造，不猜 id。 */
export function parseArtifactMarker(text: string): ArtifactMarker | null {
  const m = ARTIFACT_MARKER_RE.exec(text);
  const artifactId = m?.[2]?.trim();
  const toolName = m?.[1];
  if (!toolName || !artifactId) return null;
  return { artifactId, toolName };
}

export interface McpToolName {
  server: string;
  tool: string;
}

/** 拆解 MCP 工具名 mcp__{server}__{tool}（da394a9 Phase 8）。
 *  非 MCP 名返回 null；tool 部分可能含下划线，以首个 `__` 后界分段：
 *  mcp__github__list_issues → { server: 'github', tool: 'list_issues' }。 */
export function splitMcpToolName(name: string): McpToolName | null {
  if (!name.startsWith('mcp__')) return null;
  const rest = name.slice('mcp__'.length);
  const sep = rest.indexOf('__');
  if (sep <= 0) return null;
  const server = rest.slice(0, sep);
  const tool = rest.slice(sep + 2);
  if (!server || !tool) return null;
  return { server, tool };
}
