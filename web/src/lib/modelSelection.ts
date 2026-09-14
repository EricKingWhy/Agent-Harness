/** 模型选择器的值 → 「要 POST 给 `/model` 的模型名」（第十一轮 FE-R11-02）。
 *
 * ## 为什么需要这层解析
 *
 * 后端清掉「会话级模型覆盖」的**合法入参**是 `GET /api/models` 里 `is_default` 那个条目的
 * **名字**：`session/model_switch.py::is_default_selection()` 命中即解析成
 * `to_model_id=None` 并写一条 `model/changed{to=None}`（= 回到默认链）。
 * `web/src/lib/api.ts` 的注释也写明同一件事："默认条目（is_default=true）也是合法 POST target"。
 *
 * 而选择器的「默认链」项提交的是 `null`。此前 `handleModelChange` 的 `if (selectedId && name)`
 * 会直接跳过 POST —— 于是**已有会话**上选「默认链」什么都不会发生：
 * 界面显示「默认链」，会话却继续用上一个非默认模型。
 *
 * 真机实证（会话 `fb3619c6`）：选 `glm-5.3-flash` → 新增 `model/changed{to=glm-5.3-flash}`；
 * 再选「默认链」→ 事件流**不新增任何事件**，Inspector 的 MODEL 区仍显示 `glm-5.3-flash`；
 * 同一屏内 composer 说「默认链」、Inspector 说 `glm-5.3-flash`。刷新也不会纠正
 * （picker 只反映本地 state，不从会话事件反推）。
 *
 * ## 契约
 *
 * - `selected` 非空 → 原样返回（用户显式选了具体模型）。
 * - `selected === null` → 返回 catalog 里 `default` 条目的名字（= 清覆盖）。
 * - 找不到 `default` 条目 → `null`：调用方**保持既有行为**（不发请求），不伪造目标。
 *   后端保证 `GET /api/models` 至少有一个默认条目，所以这条是防御性分支。
 */
import type { ModelCatalogEntry } from './api';

export function modelChangeTarget(
  selected: string | null,
  models: readonly ModelCatalogEntry[],
): string | null {
  if (selected) return selected;
  return models.find((m) => m.default)?.name ?? null;
}
