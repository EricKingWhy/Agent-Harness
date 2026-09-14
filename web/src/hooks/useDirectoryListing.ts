/** 目录列举状态机（WS-7 / #170，ADR-0028）——「新建项目」内嵌浏览器的数据侧。
 *
 *  为什么单独成 hook：浏览器组件本身是**纯呈现**（见 DirectoryBrowser.tsx），
 *  状态与请求在这里收口，于是同一套"列举 → 导航 → 回填"逻辑将来换个外壳就能复用
 *  （PRD §4.5 明确要求浏览器可复用）。也避免在组件里写"同步 props 到 state"的
 *  effect——本仓的既有纪律是：只在打开时挂载、挂载即初始化（ProjectDialogs 顶部）。
 *
 *  两个必须守住的点：
 *  1. **迟到的响应不覆盖新导航**：用户连点两层子目录时会有两个在途请求，先发的
 *     可能后到。用请求代号（generation）作废过期响应，与 useSession 的流代号同一手法。
 *  2. **onChange 用 ref 持有**：父级传进来的回调每次渲染都是新引用，若进依赖数组，
 *     挂载时的首跳会被反复触发（每次父级渲染都重列一次目录）。ref 只保证"读到的
 *     是最新回调"，不参与依赖。 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { describeProjectError, getHostDirs } from '../lib/api';
import type { HostDirsListing } from '../types';

export interface DirectoryListing {
  /** 当前列出的目录；null = 还没加载出来（或加载失败）。 */
  listing: HostDirsListing | null;
  loading: boolean;
  /** 后端 detail 原文（403 无权限 / 404 不存在 / 422 不是目录…）——原样显示，
   *  界面不翻译（PRD §4.4 的错误矩阵就是按"前端不翻译"设计的）。 */
  error: string | null;
  /** 跳到 `path`（null = 列根）。成功后回填父级输入框；失败就地显示原因。 */
  goto: (path: string | null) => void;
}

export function useDirectoryListing(opts?: {
  /** 起始路径；缺省 = 列根（Windows 盘符 / POSIX `/`）。只在挂载时读一次——
   *  之后的每一次跳转都由用户动作驱动，不跟 props 变。 */
  initialPath?: string | null;
  /** 成功列目录后回填（"浏览器 → 输入框"方向的双向同步）。 */
  onPathChange?: (path: string) => void;
}): DirectoryListing {
  const [listing, setListing] = useState<HostDirsListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const genRef = useRef(0);

  const onChangeRef = useRef(opts?.onPathChange);
  useEffect(() => {
    onChangeRef.current = opts?.onPathChange;
  }, [opts?.onPathChange]);

  const goto = useCallback(async (path: string | null) => {
    const gen = ++genRef.current;
    setLoading(true);
    setError(null);
    try {
      const next = await getHostDirs(path);
      if (genRef.current !== gen) return; // 过期响应：新导航已经接管
      setListing(next);
      // 根模式下没有"当前目录"，不回填（否则输入框会显示一个不存在的路径）。
      if (next.path) onChangeRef.current?.(next.path);
    } catch (e) {
      if (genRef.current !== gen) return;
      // 保留上一份 listing：错误条下面还看得见刚才的目录，用户能继续往上走，
      // 而不是整块界面变成空白（失败不该抹掉已知事实）。
      setError(describeProjectError(e, '加载目录失败'));
    } finally {
      if (genRef.current === gen) setLoading(false);
    }
  }, []);

  const initialRef = useRef(opts?.initialPath ?? null);
  useEffect(() => {
    void goto(initialRef.current);
  }, [goto]);

  return { listing, loading, error, goto };
}
