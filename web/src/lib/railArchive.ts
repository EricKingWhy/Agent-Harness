/** 侧栏「显示已归档」开关的持久化（#171 AC10）。
 *
 *  与 `density.ts` 同一条纪律：**视图状态**落 localStorage，键统一 `ahi.*` 前缀；
 *  读取必须是**纯函数 + 同步**的——侧栏首帧就要按它决定渲染哪些行，
 *  "先渲染默认态、再在 effect 里改"会闪一下。
 *
 *  **不缓存到模块级变量**：e2e 会在同一个浏览器里多次挂载/卸载侧栏（切换会话、
 *  重新加载），模块级缓存会让"上一次的开关"粘住下一次挂载。localStorage 本身就是
 *  单一真相，读它有开销但不值得为它引入失效逻辑。
 */

export const SHOW_ARCHIVED_KEY = 'ahi.showArchived';

/** 默认**关**：归档的意义就是"平时别占地方"，默认打开会让新用户面对一个更长的列表。 */
export const DEFAULT_SHOW_ARCHIVED = false;

/** 读开关状态。任何非 `'1'` 的值（缺失 / 手改 / 旧版本写的别的形状）一律回默认值——
 *  开关是布尔语义，没有"半个开关"可表达，猜一个中间态只会撒谎。 */
export function readShowArchived(): boolean {
  try {
    return localStorage.getItem(SHOW_ARCHIVED_KEY) === '1';
  } catch {
    // 隐私模式 / 存储被禁用：读不到就按默认值走，不让侧栏因为持久化失败而崩
    // （`localStorage` 在部分隔离环境里连属性访问都会抛）。
    return DEFAULT_SHOW_ARCHIVED;
  }
}

/** 写开关状态（`true` → `'1'`，其余 `'0'`——取值域收窄成可读的字面量）。 */
export function writeShowArchived(value: boolean): void {
  try {
    localStorage.setItem(SHOW_ARCHIVED_KEY, value ? '1' : '0');
  } catch {
    // 同上：持久化失败不该让一次视图切换失败（本次切换已经生效在内存里）。
  }
}
