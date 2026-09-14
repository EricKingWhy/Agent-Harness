/** sessionDelete — 会话硬删的**回执文案**（#172 / ADR-0029）。
 *
 *  为什么单独成模块：回执是这张票的 AC 之一（"用 events / detached_from_projects 写
 *  确认回执"），而后端给的是两个裸计数。计数 → 人话的映射必须落在能单测的地方——
 *  对话框本身是 Radix 浮层，而本仓 vitest 车道是 node-only（无 jsdom、无 Testing
 *  Library），把话术塞在组件里就只能靠 e2e 兜住。与 `lib/runState.ts` 的
 *  `recoverDoneMessage` 同一手法（同样是"计数 → 人话"的纯函数）。
 *
 *  两个计数的语义由后端契约钉死，前端零推导：
 *   - `events`：**删除前**日志里的事件条数（后端在删之前取；成功删除必然 ≥ 1——0 条
 *     事件的会话走的是 404，所以 0 在这里的含义是"回执没给这个数"，不是"删了 0 条"）。
 *   - `detached_from_projects`：本次从几个项目账本里摘掉了它，正常 0/1。0 = 它本来
 *     就不在任何项目账本里（不是"项目没删掉"）。 */

/** 硬删成功后的回执。两个计数都来自后端响应（缺失时由 api 层给 0）。 */
export function sessionDeletedMessage(receipt: {
  events: number;
  detached_from_projects: number;
}): string {
  // `events === 0` 只可能意味着"回执没给这个数"：成功删除的会话必然 ≥ 1 条事件
  // （0 条的会话在后端就是 404，见 api.ts 的 deleteSession 注释）。所以缺数时
  // **不报数**，而不是把缺数说成"已删除 0 条事件记录"——那从"话说少了"变成了
  // "说了一句可能为假的话"，在同一句里还挂着"不可恢复"，代价不对等。
  const removed =
    receipt.events > 0
      ? `已永久删除 ${receipt.events} 条事件记录（不可恢复）`
      : '已永久删除（不可恢复）';
  return receipt.detached_from_projects > 0
    ? `${removed}，并从 ${receipt.detached_from_projects} 个项目里解除。`
    : `${removed}；它不在任何项目里。`;
}
