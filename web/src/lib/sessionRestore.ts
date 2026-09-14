/** sessionRestore — 选中会话的持久化 + BUG-006「接回流」的两条纯决策。
 *
 * 背景（BUG-005）：`useSession` 的 mode 初始态恒为 `idle`，而全仓只有 theme /
 * density / apiToken 三处 localStorage，**会话选择没有持久化**——刷新后 67 条
 * 会话还在，选中的那一条与它的全部内容消失、主区退回空态（真实浏览器实测：
 * 8 轮 → 0 轮，正文 4102 字符 → 0）。
 *
 * 这里只做不碰 React 的纯事：读写一个 localStorage 键、算接流游标、判定「要不要
 * 再发起一次自动恢复」。恢复动作本身（`resumeLiveStream`）留在 hook——历史重建
 * 走既有的 `GET /events` + `projectHistory` 通路，不新增数据面（不变量 #22：
 * UI 不维护第二套会话真相）。
 *
 * 键名沿用本仓 `ahi.` 前缀（`ahi.theme` / `ahi.traceDensity` / `ahi.apiToken`）。 */

export const SELECTED_SESSION_KEY = 'ahi.selectedSession';

/** 读取上次选中的会话 id；无持久化能力（隐私模式等）时返回 null。 */
export function readStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SELECTED_SESSION_KEY);
  } catch {
    return null;
  }
}

/** 记住 / 忘记选中的会话。`null` = 显式回到空态（新建会话）——刷新后不得
 *  复活一个用户已经离开的会话。写失败即静默：持久化是尽力而为，不影响本次会话。 */
export function writeStoredSessionId(id: string | null): void {
  try {
    if (id) localStorage.setItem(SELECTED_SESSION_KEY, id);
    else localStorage.removeItem(SELECTED_SESSION_KEY);
  } catch {
    /* 不可用即不持久化 */
  }
}

/** 已加载事件里的最大持久 seq——恢复时接续实时流的游标（`?after_seq=`）。
 *  只认真实 seq，跳过流式帧的 null seq（与投影层的 in-registry 规则一致）。 */
export function maxEventSeq(events: { seq: number | null }[]): number {
  let max = -1;
  for (const e of events) {
    if (e.seq !== null && e.seq > max) max = e.seq;
  }
  return max;
}

/** 「自动接回流」的尝试记录：sid → 上次试过的游标。 */
export type ResumeAttempts = ReadonlyMap<string, number>;

/** 判定要不要为 `sid` 再自动发起一次接流；要则返回**更新后**的记录，不要则 null。
 *
 *  按 `(sid, afterSeq)` 而不是只按 sid 去重，同时解决两件相反的事：
 *  - **斩断死循环**：零帧收流（服务端已无在跑的 run）会把 mode 退回
 *    `viewing(sid)`，而历史装载 effect 以 mode 为依赖 → 重新装载 → 又看到
 *    `hasUnterminatedRun` → 再发起恢复。「viewing → 接流 → 空流 → viewing」
 *    每轮都会算出**同一个游标**（空流没带来新事件），于是第二次被这里拦下。
 *  - **保住正当重试**：用户在 A/B 间来回切换、期间 A 的 run 又落了新事件——
 *    重新装载算出的游标变大 → 允许再接一次。只按 sid 记会把这个正常用法也禁掉
 *    （那是本功能的初衷：切回来还能接着看）。
 *
 *  `afterSeq` 不变即「自上次尝试以来服务端没有任何新事件」，此时空流结论仍然
 *  成立（活着的 run 不会零帧 EOF），重试没有意义。 */
export function nextResumeAttempt(
  attempted: ResumeAttempts,
  sid: string,
  afterSeq: number,
): Map<string, number> | null {
  if (attempted.get(sid) === afterSeq) return null;
  const next = new Map(attempted);
  next.set(sid, afterSeq);
  return next;
}

/** 用户**显式选中**某会话时忘掉它的记账——「切走再切回来接着看」是正当用法，
 *  不该被自动去重拦住。去重只为斩断**自动重入**的死循环（那条路经历史装载 effect
 *  re-enter，不经过这里），所以这里清掉是安全的。
 *  为什么不只靠游标判定就够：两次尝试之间若只落了非持久帧（seq=null），
 *  游标不变 → 会被 `nextResumeAttempt` 拦下，此时用户手动切回来就成了假冻结。
 *  无记录时原样返回（保持引用稳定，避免无意义的 map 复制）。 */
export function forgetResumeAttempt(attempted: ResumeAttempts, sid: string): ResumeAttempts {
  if (!attempted.has(sid)) return attempted;
  const next = new Map(attempted);
  next.delete(sid);
  return next;
}
