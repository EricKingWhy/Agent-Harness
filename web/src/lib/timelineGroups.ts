/** UI-03：Inspector 时间线的 run 分组——纯函数，SSR/组件层共用。
 *
 *  分组规则（docs/UI_POLISH_TICKETS.md UI-03 规格 1）：
 *  - 按 run_id 的**首次出现顺序**分组；序数（ordinal）在全会话范围编号——
 *    时间线尾窗裁剪后组号不得重排（窗口内看到 Run 2 必须仍叫 Run 2）。
 *  - run_id 缺失的事件（如会话开场帧）归属当前已打开的组；尚无组时归入
 *    领头的 runId=null 组（渲染层标「会话」）。
 *  - 组状态由组内终态事件推导：completed > failed > interrupted > running
 *    （一个 run 正常只有一种终态；多种并存时按严重度取，不静默丢）。 */
import { EventType } from '../types';
import type { AgentEvent } from '../types';

export type RunGroupStatus = 'completed' | 'failed' | 'interrupted' | 'running';

export interface RunGroup {
  /** run_id（缺失 = 领头的「会话」组） */
  runId: string | null;
  /** 1-based 序数（仅 runId 组；null 组恒 0） */
  ordinal: number;
  status: RunGroupStatus;
  /** 组内事件数 */
  count: number;
  /** 组在原数组中的起始下标（渲染层用区间求与尾窗的交集） */
  start: number;
}

const TERMINAL_STATUS: Partial<Record<string, RunGroupStatus>> = {
  [EventType.RUN_COMPLETED]: 'completed',
  [EventType.RUN_FAILED]: 'failed',
  [EventType.RUN_INTERRUPTED]: 'interrupted',
};

export function groupEventsByRun(events: AgentEvent[]): RunGroup[] {
  const groups: RunGroup[] = [];
  // 序数 = run 在会话中**首次出现**的次序（跨交错段稳定：r1,r2,r1 都叫 Run 1）。
  const ordinalOfRun = new Map<string, number>();
  let current: RunGroup | null = null;

  for (let i = 0; i < events.length; i++) {
    const e = events[i];
    const runId = e.run_id ?? null;
    if (!current || (runId !== null && current.runId !== runId)) {
      let ordinal = 0;
      if (runId !== null) {
        let next = ordinalOfRun.get(runId);
        if (next === undefined) {
          next = ordinalOfRun.size + 1;
          ordinalOfRun.set(runId, next);
        }
        ordinal = next;
      }
      current = { runId, ordinal, status: 'running', count: 0, start: i };
      groups.push(current);
    }
    current.count += 1;
    const terminal = TERMINAL_STATUS[e.type];
    if (terminal) {
      // 严重度优先级：interrupted > failed > completed（并存的罕见脏数据下取更醒目的）
      if (
        current.status === 'running' ||
        (terminal === 'interrupted' && current.status !== 'interrupted') ||
        (terminal === 'failed' && current.status === 'completed')
      ) {
        current.status = terminal;
      }
    }
  }
  return groups;
}

/** 会话内出现过的 distinct run 数（头标「N runs · M 事件」用；null 不计）。 */
export function countRuns(events: AgentEvent[]): number {
  const seen = new Set<string>();
  for (const e of events) {
    if (e.run_id) seen.add(e.run_id);
  }
  return seen.size;
}
