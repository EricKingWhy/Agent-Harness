/** 请求兜底超时（**不是**通用 API 超时）。
 *
 *  `api.ts` 刻意没有全局超时（其余请求同病，见 App.tsx 的 FORK_TIMEOUT_MS 注释）；
 *  这个助手只给**会让界面进入临时状态**的请求用：请求既不 resolve 也不 reject
 *  （socket 挂死）时，界面必须能自己走回收尾路径，而不是永远停在"进行中"。
 *
 *  语义提醒：超时**不代表对端没执行**（请求可能已经在后端完成，只是响应没回来）。
 *  调用方据此必须做的是"按后端重新对账"，而不是假设操作失败。
 *
 *  用裸 `setTimeout` 而非 `window.setTimeout`：本模块要能在 node（vitest 单测）
 *  下跑——`window` 在那里不存在。`ReturnType<typeof setTimeout>` 同时覆盖
 *  DOM（number）与 node（Timeout）两种返回类型。 */

/** Promise.race + 定时器；无论哪个先落地都会清掉定时器（不留下悬空 timeout）。 */
export function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${label}超时（${Math.round(ms / 1000)}s）`)),
      ms,
    );
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}
