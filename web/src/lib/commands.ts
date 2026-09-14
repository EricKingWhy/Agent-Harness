/** lib/commands — Command Palette 数据层（PRD §15，ADR-0014）。
 *
 * 命令 = 静态动作（切换密度 / Inspector / 主题 / 复制）+ 动态事件项
 * （Search Runtime Events：最近事件直出为可选项，选中即定位）。
 * fuzzy 匹配是纯函数：子序列匹配 + 前缀/连续加分，null = 不命中。
 * 不引第三方 palette 库——Radix Dialog（已有依赖）承担浮层语义。
 */

export interface CommandItem {
  id: string;
  label: string;
  /** 不显示的可搜索别名（英文术语 / 同义说法）。`label` 是中文（与工具栏一致），
   *  但 `Toggle Theme` / `Copy Run ID` / `Compact` 这些英文说法要照样搜得到——
   *  否则用英文肌肉记忆输入的老用户会以为命令没了。 */
  keywords?: string;
  /** 右侧弱化提示：快捷键 / 事件类型 / 状态。 */
  hint?: string;
  group: 'actions' | 'density' | 'events';
  run: () => void;
}

/** 子序列 fuzzy 打分：query 每个字符按序出现在 text 中即命中。
 *  得分 = 命中基础上前缀 +40 / 连续命中每对 +8 / 越早命中 +（剩余长度）。
 *  不命中返回 null。大小写不敏感。 */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.trim().toLowerCase();
  if (!q) return 0; // 空 query = 全量（调用方决定展示上限）
  const t = text.toLowerCase();
  let score = 0;
  let ti = 0;
  let prevHit = -2;
  for (let qi = 0; qi < q.length; qi++) {
    const ch = q[qi];
    const idx = t.indexOf(ch, ti);
    if (idx === -1) return null;
    if (idx === 0) score += 40; // 前缀命中
    if (idx === prevHit + 1) score += 8; // 连续命中（子串）
    score += Math.max(0, 20 - idx); // 越早越好
    prevHit = idx;
    ti = idx + 1;
  }
  return score;
}

/** 过滤 + 排序：命中项按分数降序（稳定——同分保持原序，事件按时间新→旧自然可读）。
 *  空 query 原序返回。
 *
 *  匹配的 haystack 是 `label + keywords`。label 在前，所以**只按 label 命中的那条
 *  打分逐字不变**（追加文本不会移动 label 字符的贪心下标，已穷举 3 字符以内 query
 *  验证：0 个既有命中失分或改分）。但**跨命令仍按分数比大小**：一条命令靠 keywords
 *  命中、打的分数高于另一条靠 label 命中的，它就会排到前面（例：query `to` 下
 *  `切换主题` 经 keyword `toggle theme` 高于 `切换 Run Inspector` 的 `Inspector`）。
 *  这是可接受的——`keywords` 的存在就是为了让中文 label 命令仍能被英文搜到。 */
export function filterCommands(items: readonly CommandItem[], query: string): CommandItem[] {
  if (!query.trim()) return [...items];
  return items
    .map((item) => ({
      item,
      score: fuzzyScore(query, item.keywords ? `${item.label} ${item.keywords}` : item.label),
    }))
    .filter((x): x is { item: CommandItem; score: number } => x.score !== null)
    .sort((a, b) => b.score - a.score)
    .map((x) => x.item);
}

/** 快捷键判定：Ctrl（Win/Linux）或 Cmd（macOS）+ K。 */
export function isPaletteShortcut(e: {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
}): boolean {
  return (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k';
}
