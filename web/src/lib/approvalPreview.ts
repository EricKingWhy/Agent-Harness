/** 审批参数预览的结构化分类（UI-01，PRD R7：不给用户直出转义 JSON）。
 *
 *  后端 `arguments_preview` 是任意形状的 Record。已知语义键被**结构化消费**
 *  （path 置顶、command 终端块、content 原文块、old+new → diff），其余键进
 *  `rest` 由调用方做 JSON 兜底渲染。只认字符串值——类型不符的一律进 rest，
 *  绝不猜（与 toolShapes 同一纪律）。
 *
 *  键名适配：审批参数用 `old`/`new`，DiffBlock 用 `before`/`after`——适配
 *  在本模块完成（ApprovalCard/ToolCard 两侧零改动）。 */

export interface ClassifiedPreview {
  /** 路径语义键的值（path → file_path → file 优先级；只认字符串）。 */
  path: string | null;
  command?: string;
  /** old+new 适配成 DiffBlock 的 diff 形状（truncated 恒 false——预览不经截断管线）。 */
  diff?: { before: string; after: string; truncated: false };
  content?: string;
  /** 未被结构化消费的剩余键（含类型不符的已知键）——调用方 JSON 兜底。 */
  rest: Record<string, unknown>;
}

const PATH_KEYS = ['path', 'file_path', 'file'] as const;

export function classifyPreviewArgs(preview: Record<string, unknown> | undefined): ClassifiedPreview {
  const args = preview ?? {};
  const rest: Record<string, unknown> = { ...args };
  const out: ClassifiedPreview = { path: null, rest };

  // 空串不算消费（U-1 review P3）：`{command:''}` 留在 rest 里走 JSON 兜底，
  // 信息不静默消失；渲染层的真值判断也就不会出现空容器。
  for (const key of PATH_KEYS) {
    const value = args[key];
    if (typeof value === 'string' && value.length > 0) {
      out.path = value;
      delete rest[key];
      break;
    }
  }

  if (typeof args.command === 'string' && args.command.length > 0) {
    out.command = args.command;
    delete rest.command;
  }
  if (typeof args.content === 'string' && args.content.length > 0) {
    out.content = args.content;
    delete rest.content;
  }
  if (typeof args.old === 'string' && args.old.length > 0 && typeof args.new === 'string' && args.new.length > 0) {
    out.diff = { before: args.old, after: args.new, truncated: false };
    delete rest.old;
    delete rest.new;
  }

  return out;
}
