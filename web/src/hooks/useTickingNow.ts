/** useTickingNow — 周期推进的 `now` 时间戳，驱动相对时间自动刷新。
 *
 * 背景：formatRelativeTime 在渲染时计算，组件不重渲染就一直显示旧值（issue #40）。
 * 这个 hook 暴露一个会自己更新的 `now`，把它喂给 formatRelativeTime 即可让相对
 * 时间随真实时间流逝刷新——而不是停在挂载瞬间的快照。
 *
 * heartbeatMs 默认 60s，与 formatRelativeTime 的最小语义粒度（分钟）对齐；
 * 秒级消费者（T2 reasoning 流式时长）显式传 1000——只在叶子组件用，避免
 * 每秒重渲染扩散到正文子树（规格 03 §7.1 ticker 隔离）。组件卸载即清 interval。 */
import { useEffect, useState } from 'react';

export function useTickingNow(heartbeatMs: number = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), heartbeatMs);
    return () => clearInterval(id);
  }, [heartbeatMs]);
  return now;
}
