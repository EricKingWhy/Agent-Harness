/** 项目列表 + 项目动作（WS-5 / #155）。
 *
 *  **不做第二套真相**（不变量 #22）：本 hook 只持有 `GET /api/projects` 的最近一次
 *  响应，"项目有哪些会话"永远从账本（`session_ids`）读，不在前端累积成员名单。
 *  每次写操作后**重新拉取**而不是本地改一份影子列表——后端有一次原子性 + 成员资格
 *  过滤（WS-2/WS-3），本地重算必然会在某个边界上和它不一致。
 *
 *  失败时也会刷新一次：写操作失败最常见的两类原因（409 会话 cwd 不一致 / 账本已被
 *  别处改动）都意味着**本地看到的状态已经过期**，刷新让 UI 立刻追上真相，而不是让
 *  用户对着一个永远失败的按钮重试。 */

import { useCallback, useMemo, useRef, useState } from 'react';
import {
  attachSessionToProject,
  createProject,
  deleteProject,
  detachSessionFromProject,
  listProjects,
  renameProject,
  reorderProjectSession,
} from '../lib/api';
import type { Project, ProjectDeleted } from '../types';

export interface ProjectActions {
  /** 注册一个**已存在**的目录（幂等）。失败抛 ProjectError（404 路径不存在等）。 */
  create: (path: string, title?: string | null) => Promise<Project>;
  rename: (projectId: string, title: string) => Promise<void>;
  /** **软删除**：只摘注册记录与账本，返回后端写好的 `detail`（AC5 要原样展示）。 */
  remove: (projectId: string) => Promise<ProjectDeleted>;
  attach: (projectId: string, sessionId: string) => Promise<void>;
  detach: (projectId: string, sessionId: string) => Promise<void>;
  /** `before=null` → 追加队尾（DOM insertBefore 语义）。 */
  reorder: (projectId: string, sessionId: string, before: string | null) => Promise<void>;
}

export interface ProjectsState {
  projects: Project[];
  /** `GET /api/projects` 失败的原因（**不**清空既有列表：清空会把每条会话都变成
   *  未分组、并把项目行整片抹掉——一次网络抖动不该重排用户的界面）。 */
  loadError: string | null;
  refresh: () => Promise<void>;
  actions: ProjectActions;
}

export function useProjects(): ProjectsState {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 两个守卫解决**不同**的问题，都需要：
  //  - inflight：启动时调用方会在 `sessions` 一到位后再刷一次（effect 依赖它），
  //    与挂载那次重叠。合并并发请求省一次 GET，也免得"两次响应的先后"决定列表。
  //  - generation：两次**不重叠**但乱序返回的刷新（写操作后的重新拉取 vs 用户点
  //    「重试」）只允许最后一次落地——先发后到的旧列表不能覆盖新真相。
  const inflight = useRef<Promise<void> | null>(null);
  const generation = useRef(0);

  const start = useCallback(async () => {
    const gen = ++generation.current;
    try {
      const list = await listProjects();
      if (gen !== generation.current) return; // 已有更新的请求发出，丢弃本次结果
      setProjects(list);
      setLoadError(null);
    } catch (e) {
      if (gen !== generation.current) return;
      setLoadError((e as Error).message || '加载项目失败');
    }
  }, []);

  /** 后台刷新（挂载 / 会话列表变化 / 用户点重试）：并发调用合并成一次请求。 */
  const refresh = useCallback(async () => {
    if (!inflight.current) {
      // `.finally` 只在"没有更新的请求顶上"时清标记：否则一个旧请求收尾会把
      // 新请求在飞的标记抹掉（`refetch` 之后紧跟一次 `refresh` 就会走到这条）。
      let pending: Promise<void>;
      pending = start().finally(() => {
        if (inflight.current === pending) inflight.current = null;
      });
      inflight.current = pending;
    }
    return inflight.current;
  }, [start]);

  /** 写操作后的重新拉取：**绕过合并**——正在飞的那个请求可能是写之前发出的，
   *  复用它会把列表停在被写操作改掉之前的状态（先发后到的旧响应）。 */
  const refetch = useCallback(async () => {
    inflight.current = null;
    return start();
  }, [start]);

  /** 写操作 → 拉取最新真相；失败同样拉取（见文件头注释），再把错误抛给调用方
   *  （由对话框或项目区错误条负责显示——hook 自己不弹 UI）。 */
  const after = useCallback(
    async <T,>(run: () => Promise<T>): Promise<T> => {
      try {
        const result = await run();
        await refetch();
        return result;
      } catch (e) {
        await refetch().catch(() => undefined);
        throw e;
      }
    },
    [refetch],
  );

  const actions = useMemo<ProjectActions>(
    () => ({
      create: (path, title) => after(() => createProject(path, title)),
      rename: async (projectId, title) => {
        await after(() => renameProject(projectId, title));
      },
      remove: (projectId) => after(() => deleteProject(projectId)),
      attach: async (projectId, sessionId) => {
        await after(() => attachSessionToProject(projectId, sessionId));
      },
      detach: async (projectId, sessionId) => {
        await after(() => detachSessionFromProject(projectId, sessionId));
      },
      reorder: async (projectId, sessionId, before) => {
        await after(() => reorderProjectSession(projectId, sessionId, before));
      },
    }),
    [after],
  );

  return { projects, loadError, refresh, actions };
}
