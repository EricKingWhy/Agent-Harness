/** projection.ts 纯函数测试——事件→视图状态机的折叠语义契约。 */

import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../types';
import { EventType } from '../types';
import { applyEvent, awaitingApproval, deriveChain, deriveSessionTitle, emptyChildTurnIndex, firstForkableTurnIndex, hasSummaryOverflow, initConversation, projectHistory, summarizeEvent } from './projection';

function ev(partial: Partial<AgentEvent> & { type: string }): AgentEvent {
  return { data: {}, seq: null, run_id: null, step_id: null, ...partial };
}

describe('initConversation', () => {
  it('初始状态为空对话', () => {
    const s = initConversation('abc');
    expect(s).toEqual({
      session_id: 'abc', turns: [], active_step_id: null, run_status: 'idle', run_cancelled: false,
      compactions: [], reconcile_queue: [], pending_approvals: [], approval_decisions: [],
      permission_policy: null, events: [], unknown_events: [],
      model: null, usage_total: null, cost_usd: null, trace_id: null, trace_url: null, run_id: null,
      model_fallback: null,
      run_interrupted: null, turn_index: null,
      seenSeqs: new Set(),
    });
  });
});

describe('applyEvent — 折叠语义', () => {
  it('USER_MESSAGE 按 data.step 创建轮次并写入用户消息', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.USER_MESSAGE,
      data: { content: 'hi', step: 2 },
      step_id: 7,
    }));
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].step_id).toBe(2);
    expect(s.turns[0].user_message).toBe('hi');
  });

  it('RUN_STARTED → running；RUN_COMPLETED → completed 并折叠 streaming 轮次', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED }));
    expect(s.run_status).toBe('running');
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED }));
    expect(s.run_status).toBe('completed');
    expect(s.active_step_id).toBeNull();
    expect(s.turns[0].status).toBe('done');
    expect(s.turns[0].model.status).toBe('done');
  });

  it('RUN_FAILED → failed 且 streaming 轮次标记 failed', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 3 }));
    s = applyEvent(s, ev({ type: EventType.RUN_FAILED }));
    expect(s.run_status).toBe('failed');
    expect(s.turns[0].status).toBe('failed');
  });

  it('MODEL_DELTA 累积文本并保持 streaming', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'Hel' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'lo' }, step_id: 1 }));
    expect(s.turns[0].model.text).toBe('Hello');
    expect(s.turns[0].model.status).toBe('streaming');
  });

  it('MODEL_COMPLETED 的 content 覆盖累积 delta', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'partial' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_COMPLETED, data: { content: 'final' }, step_id: 1 }));
    expect(s.turns[0].model.text).toBe('final');
    expect(s.turns[0].model.status).toBe('done');
  });

  it('TOOL_CALL 创建 running 工具；重复 tool_call_id 不重复创建', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    const call = { type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash', args: { command: 'ls' } }, step_id: 1 };
    s = applyEvent(s, ev(call));
    s = applyEvent(s, ev(call));
    expect(s.turns[0].tools).toHaveLength(1);
    expect(s.turns[0].tools[0].status).toBe('running');
  });

  it('TOOL_RESULT 双重编码 content 解析：ok→success，diff 字段从 data 顶层提取', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'write' }, step_id: 1 }));
    const toolResult = JSON.stringify({
      ok: true,
      message: 'written',
      data: { before: '', after: 'hello', truncated: false },
    });
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: toolResult },
      step_id: 1,
    }));
    const tool = s.turns[0].tools[0];
    expect(tool.status).toBe('success');
    expect(tool.diff).toEqual({ before: '', after: 'hello', truncated: false });
  });

  it('TOOL_RESULT ok=false → failed', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' }, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: false, message: 'boom' }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].status).toBe('failed');
  });

  it('时间真值：durable 事件的 time 优先于客户端时钟', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'write' }, step_id: 1, time: '2026-09-04T01:02:03.000Z' }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true }) },
      step_id: 1,
      time: '2026-09-04T01:02:04.500Z',
    }));
    expect(s.turns[0].tools[0].started_at).toBe('2026-09-04T01:02:03.000Z');
    expect(s.turns[0].tools[0].completed_at).toBe('2026-09-04T01:02:04.500Z');
  });

  it('UnknownSurface 兜底：未知事件记录到 unknown_events 而非静默丢弃（冻结决策第 69 行）', () => {
    const s = applyEvent(initConversation('s'), ev({ type: 'future/thing', data: { x: 1 } }));
    expect(s.turns).toHaveLength(0);
    expect(s.unknown_events).toHaveLength(1);
    expect(s.unknown_events[0].type).toBe('future/thing');
    expect(s.events).toHaveLength(1);
  });

  it('已知生命周期事件 SESSION_STARTED / SESSION_RESUMED 不进 unknown_events', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.SESSION_STARTED }));
    s = applyEvent(s, ev({ type: EventType.SESSION_RESUMED }));
    expect(s.unknown_events).toHaveLength(0);
    expect(s.events).toHaveLength(2);
  });

  it('工具四态 stopped：run 结束时仍在 running 的工具被标记 stopped（DSH interrupted ≠ error）', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.TOOL_CALL,
      data: { tool_call_id: 't1', tool_name: 'bash' },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].status).toBe('running');
    // 未收到 TOOL_RESULT 就 RUN_FAILED → 工具被中断
    s = applyEvent(s, ev({ type: EventType.RUN_FAILED }));
    expect(s.turns[0].tools[0].status).toBe('stopped');
  });

  it('已完成（成功或失败）的工具在 run 结束时不被改成 stopped', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.TOOL_CALL,
      data: { tool_call_id: 't1', tool_name: 'bash' },
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].status).toBe('success');
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED }));
    // success 保持，不被 finalizeRun 改动
    expect(s.turns[0].tools[0].status).toBe('success');
  });
});

describe('deriveSessionTitle — Session Model E 轮首条用户消息投影', () => {
  it('返回首条 user/message 的 content', () => {
    const events = [
      ev({ type: EventType.SESSION_STARTED }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '写一个 FizzBuzz', step: 1 } }),
      ev({ type: EventType.MODEL_COMPLETED, data: { content: 'ok', step: 1 } }),
    ];
    expect(deriveSessionTitle(events)).toBe('写一个 FizzBuzz');
  });

  it('无 user/message 时返回空串（调用方回退到短 ID，不伪造）', () => {
    const events = [
      ev({ type: EventType.SESSION_STARTED }),
      ev({ type: EventType.RUN_STARTED }),
    ];
    expect(deriveSessionTitle(events)).toBe('');
  });

  it('空白 content 视为无标题（trim 后为空）', () => {
    const events = [
      ev({ type: EventType.USER_MESSAGE, data: { content: '   ', step: 1 } }),
    ];
    expect(deriveSessionTitle(events)).toBe('');
  });

  it('多条 user/message 只取首条（不随后续轮次更新）', () => {
    const events = [
      ev({ type: EventType.USER_MESSAGE, data: { content: '第一句', step: 1 } }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '第二句', step: 2 } }),
    ];
    expect(deriveSessionTitle(events)).toBe('第一句');
  });
});

describe('applyEvent — resolveStep 边界契约', () => {
  // 这组测试钉死 resolveStep 的语义优先级链（commit 3663ab8 统一后的形态），
  // 防止未来重构再次引入 6 处 step 解析变体时回退。
  // 优先级：data.step → step_id → active_step_id → turns.length+1

  it('data.step 优先于 step_id：当两者冲突时采纳 data.step（显式信号胜出）', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev({
      type: EventType.MODEL_STARTED,
      data: { step: 5 },      // 显式声明 step=5
      step_id: 9,             // 持久化携带 step_id=9（冲突）
    }));
    // turn 应落在 step=5，active_step_id 也应是 5
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].step_id).toBe(5);
    expect(s.active_step_id).toBe(5);
  });

  it('无 data.step 时回退到 step_id', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.MODEL_STARTED,
      step_id: 3,
    }));
    expect(s.turns[0].step_id).toBe(3);
    expect(s.active_step_id).toBe(3);
  });

  it('MODEL_STARTED 无 data.step 且无 step_id、已有 turn 时走 turns.length+1（非旧的 1）', () => {
    // 构造一个已有 1 个 turn 的状态（active_step_id 已被前一个 MODEL_STARTED 设过）
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.USER_MESSAGE,
      data: { content: 'first', step: 1 },
    }));
    expect(s.turns).toHaveLength(1);
    // 此时无任何 active step（USER_MESSAGE 不设 active_step_id），无 step_id 的
    // MODEL_STARTED 应回退到 turns.length+1 = 2，而不是旧行为的 1。
    s = applyEvent(s, ev({
      type: EventType.MODEL_STARTED,
      // 故意不带 data.step 也不带 step_id
    }));
    expect(s.turns).toHaveLength(2);
    expect(s.turns[1].step_id).toBe(2);
    expect(s.active_step_id).toBe(2);
  });

  it('MODEL_DELTA 无 step_id 时跟随 active_step_id', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.MODEL_STARTED,
      data: { step: 4 },
    }));
    s = applyEvent(s, ev({
      type: EventType.MODEL_DELTA,
      data: { delta: 'x' },
      // 不带 step_id，应跟随 active_step_id=4
    }));
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].step_id).toBe(4);
    expect(s.turns[0].model.text).toBe('x');
  });

  // ── 回归：step_id 字段缺失（undefined）≠ null 的边界 ──
  // 真实后端 user/message 事件不带 step_id 字段（键完全缺失，JSON 解析为 undefined，
  // 不是 null）。resolveStep 用 !== null 判定会让 undefined 漏网返回 undefined，
  // 导致 user/message 与后续 model/completed(step_id=1) 落入不同 turn——模型文本丢失。
  it('user/message 无 step_id 字段（undefined）时与后续 model/completed(step_id=1) 入同一 turn', () => {
    // 模拟真实后端事件：step_id 值为 undefined（运行时等价于键完全缺失，
    // `!= null` 判定一致——strict 判定下 undefined 与 null 行为分叉正是本回归点）
    const userMsg = ev({ type: EventType.USER_MESSAGE, data: { content: '你是谁' }, seq: 1, step_id: undefined });
    const modelCompleted: AgentEvent = { type: EventType.MODEL_COMPLETED, data: { content: '我是 Qwen' }, seq: 3, run_id: null, step_id: 1 };
    let s = applyEvent(initConversation('s'), userMsg);
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, modelCompleted);
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].user_message).toBe('你是谁');
    expect(s.turns[0].model.text).toBe('我是 Qwen');
    expect(s.turns[0].step_id).toBe(1);
  });

  // ── 回归：分叉锚点 = user/message 的持久 seq（BUG-001） ──
  // 真实信封里 user/message 的 step_id 恒为 null，step 号由 resolveStep 合成。
  // 把合成的 step 号当 from_seq 发给后端会被 422 拒（只有 seq 是合法锚点）。
  it('user/message 的持久 seq 落到 turn.user_message_seq（不写合成 step 号）', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.USER_MESSAGE,
      data: { content: 'hi' },
      seq: 30,
      step_id: undefined,
    }));
    expect(s.turns[0].step_id).toBe(1); // resolveStep 合成值
    expect(s.turns[0].user_message_seq).toBe(30); // 真实锚点
  });

  it('seq 缺失（null）的 user/message 不写入 user_message_seq（不伪造锚点）', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.USER_MESSAGE,
      data: { content: 'hi' },
      seq: null,
    }));
    expect(s.turns[0].user_message_seq).toBeNull();
  });

  // ── 回归：MODEL_COMPLETED 无前置 MODEL_STARTED 时须补 model activity ──
  // 后端某些路径（无工具的纯对话）只发 model/completed 不发 model/started。
  // 此时 turn.activities 没有 model 节点 → Conversation 的 `activities.length > 0`
  // 渲染条件跳过整个 model 输出块 → 模型文本丢失（用户看不到回复）。
  // MODEL_COMPLETED 若发现 turn 还没有任何 model activity，补一个。
  it('MODEL_COMPLETED 无前置 MODEL_STARTED 时补 model segment + activity（渲染入口）', () => {
    const userMsg = ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, seq: 1, step_id: undefined });
    const modelCompleted: AgentEvent = { type: EventType.MODEL_COMPLETED, data: { content: 'hello' }, seq: 2, run_id: null, step_id: 1 };
    let s = applyEvent(initConversation('s'), userMsg);
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, modelCompleted);
    const turn = s.turns[0];
    expect(turn.segments).toHaveLength(1);
    expect(turn.segments[0].text).toBe('hello');
    expect(turn.segments[0].status).toBe('done');
    expect(turn.activities).toContainEqual({ kind: 'model', index: 0 });
    // turn.model 应与 segments[0] 是同一对象（MODEL_STARTED 的引用对齐不变量）
    expect(turn.model).toBe(turn.segments[0]);
  });
});

describe('applyEvent — Phase 5 新事件投影', () => {
  // 这组测试覆盖 Phase 5 新增的 3 个事件类型（ARTIFACT_CREATED /
  // CONTEXT_COMPACTED / OPERATION_RECONCILE_REQUIRED）。
  // MODEL_FAILED 是死常量（后端声明但无构造点），暂不投影（走 default 忽略）。

  it('ARTIFACT_CREATED 把 artifact ref 挂到产生它的 ToolCall 上', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.TOOL_CALL,
      data: { tool_call_id: 't1', tool_name: 'bash', args: { command: 'cat big.log' } },
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.ARTIFACT_CREATED,
      data: {
        artifact_id: 'art-abc123',
        session_id: 's',
        source_tool: 'bash',
        tool_call_id: 't1',
        size: 1048576,
        mime_type: 'text/plain',
      },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].artifact).toEqual({
      artifact_id: 'art-abc123',
      size: 1048576,
      mime_type: 'text/plain',
      source_tool: 'bash',
    });
  });

  it('ARTIFACT_CREATED 找不到对应 tool_call_id 时安全忽略（不崩溃）', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.ARTIFACT_CREATED,
      data: {
        artifact_id: 'art-x',
        session_id: 's',
        source_tool: 'bash',
        tool_call_id: 'nonexistent',
        size: 100,
        mime_type: 'text/plain',
      },
    }));
    expect(s.turns).toHaveLength(0);
  });

  it('CONTEXT_COMPACTED 记录到 conversation.compactions（Inspector 数据源）', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.CONTEXT_COMPACTED,
      data: {
        compacted_turn_count: 5,
        summary_message_count: 1,
        token_estimate: 2048,
        fallback_used: false,
      },
      time: '2026-09-04T10:00:00.000Z',
    }));
    expect(s.compactions).toHaveLength(1);
    expect(s.compactions[0]).toEqual({
      compacted_turn_count: 5,
      summary_message_count: 1,
      token_estimate: 2048,
      fallback_used: false,
      time: '2026-09-04T10:00:00.000Z',
    });
  });

  it('OPERATION_RECONCILE_REQUIRED 入队到 reconcile_queue', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.OPERATION_RECONCILE_REQUIRED,
      data: {
        tool_call_id: 't9',
        tool_name: 'bash',
        args_identity: 'rm -rf /tmp/x',
        state: 'NEED_RECONCILE',
      },
      time: '2026-09-04T11:00:00.000Z',
    }));
    expect(s.reconcile_queue).toHaveLength(1);
    expect(s.reconcile_queue[0]).toEqual({
      tool_call_id: 't9',
      tool_name: 'bash',
      args_identity: 'rm -rf /tmp/x',
      state: 'NEED_RECONCILE',
      time: '2026-09-04T11:00:00.000Z',
    });
  });

  it('多次 CONTEXT_COMPACTED 累积（不全量覆盖）', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev({
      type: EventType.CONTEXT_COMPACTED,
      data: { compacted_turn_count: 3, summary_message_count: 1, token_estimate: 1024, fallback_used: false },
    }));
    s = applyEvent(s, ev({
      type: EventType.CONTEXT_COMPACTED,
      data: { compacted_turn_count: 2, summary_message_count: 1, token_estimate: 2048, fallback_used: true },
    }));
    expect(s.compactions).toHaveLength(2);
    expect(s.compactions[1].fallback_used).toBe(true);
  });

  it('initConversation 新字段初始化为空数组', () => {
    const s = initConversation('s');
    expect(s.compactions).toEqual([]);
    expect(s.reconcile_queue).toEqual([]);
  });
});

describe('projectHistory — 从持久事件重建', () => {
  it('重建结果与逐事件 apply 一致，且不携带流式 delta', () => {
    const history: AgentEvent[] = [
      { type: EventType.SESSION_STARTED, data: {}, seq: 0, run_id: null, step_id: null },
      { type: EventType.USER_MESSAGE, data: { content: 'task' }, seq: 1, run_id: null, step_id: 1 },
      { type: EventType.MODEL_COMPLETED, data: { content: 'done' }, seq: 2, run_id: null, step_id: 1 },
      { type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash', args: {} }, seq: 3, run_id: null, step_id: 1 },
      { type: EventType.TOOL_RESULT, data: { tool_call_id: 't1', content: JSON.stringify({ ok: true }) }, seq: 4, run_id: null, step_id: 1 },
      { type: EventType.RUN_COMPLETED, data: {}, seq: 5, run_id: null, step_id: null },
    ];
    const s = projectHistory('abc', history);
    expect(s.session_id).toBe('abc');
    expect(s.run_status).toBe('completed');
    expect(s.turns[0].user_message).toBe('task');
    expect(s.turns[0].model.text).toBe('done');
    expect(s.turns[0].tools[0].status).toBe('success');
  });
});

describe('applyEvent — 执行链投影（Phase 3）', () => {
  it('同 step 多轮 model burst 各存一段，turn.model 指向最新段', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1, time: '2026-09-04T00:00:00.000Z' }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'first' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_COMPLETED, data: { content: 'first done' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1, time: '2026-09-04T00:00:05.000Z' }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'second' }, step_id: 1 }));
    expect(s.turns[0].segments).toHaveLength(2);
    expect(s.turns[0].segments[0]).toEqual({ text: 'first done', status: 'done' });
    expect(s.turns[0].segments[1]).toEqual({ text: 'second', status: 'streaming' });
    expect(s.turns[0].model).toEqual({ text: 'second', status: 'streaming' });
  });

  it('activities 记录事件真序：model → tool → model', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'a' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'b' }, step_id: 1 }));
    const t = s.turns[0];
    expect(t.activities).toEqual([
      { kind: 'model', index: 0 },
      { kind: 'tool', tool_call_id: 't1' },
      { kind: 'model', index: 1 },
    ]);
  });

  it('重复 MODEL_STARTED（无 delta）不追加空段；重复 TOOL_CALL 不重复记 activity', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    const call = { type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' }, step_id: 1 };
    s = applyEvent(s, ev(call));
    s = applyEvent(s, ev(call));
    expect(s.turns[0].segments).toHaveLength(1);
    expect(s.turns[0].activities.filter((a) => a.kind === 'tool')).toHaveLength(1);
  });

  it('turn 时间真值：started_at 来自首个触碰事件，completed_at 来自 finalizeRun', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1, time: '2026-09-04T00:00:01.000Z' }));
    expect(s.turns[0].started_at).toBe('2026-09-04T00:00:01.000Z');
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED, time: '2026-09-04T00:00:09.500Z' }));
    expect(s.turns[0].completed_at).toBe('2026-09-04T00:00:09.500Z');
  });

  it('deriveChain：activities 顺序展开为 model/tool 混合链', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'hi' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash', args: {} }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    const chain = deriveChain(s.turns[0]);
    expect(chain.map((n) => n.kind)).toEqual(['model', 'tool', 'model']);
    expect(chain[0].kind === 'model' && chain[0].segment.text).toBe('hi');
    expect(chain[1].kind === 'tool' && chain[1].tool.tool_call_id).toBe('t1');
  });

  it('clone 后 model↔segments 别名重新对齐：后续 delta 落在最新段且同步可见', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'a' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TOOL_RESULT, data: { tool_call_id: 'x', content: 'done' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    // 这次 applyEvent 的 clone 必须重新对齐 model 与 segments[last index]，
    // 否则此 delta 只改 turn.model，deriveChain 读到的 segment 仍是空串
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'b' }, step_id: 1 }));
    const t = s.turns[0];
    expect(t.segments[1].text).toBe('b');
    expect(t.model).toBe(t.segments[1]);
  });
});

describe('applyEvent — Inspector Timeline 事件日志（Phase 5）', () => {
  it('每个事件原样追加到 conversation.events（真相源，零过滤）', () => {
    const e1 = ev({ type: EventType.RUN_STARTED });
    const e2 = ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' } });
    const state = [e1, e2].reduce(applyEvent, initConversation('s1'));
    expect(state.events).toEqual([e1, e2]);
  });

  it('applyEvent 是 append-only：既有日志条目永不改写（共享数组只增长）', () => {
    // P0-1 新契约（HANDOFF §6 方案 b）：events 是引用稳定的共享数组，
    // 「不改变既有条目」指条目不 mutate、不重排——不再保证旧 state 的
    // events 长度冻结（旧语义靠每事件 O(N) 克隆换来，是 O(N²) 根因）。
    const e1 = ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' } });
    const e2 = ev({ type: EventType.TOOL_RESULT, data: { tool_call_id: 't1', content: '{"ok":true}' } });
    const afterFirst = applyEvent(initConversation('s1'), e1);
    applyEvent(afterFirst, e2);
    expect(afterFirst.events[0]).toBe(e1); // 既有条目引用不变、不被改写
    expect(afterFirst.events[1]).toBe(e2); // 新条目只追加在尾部
  });

  it('events 日志数组引用跨事件稳定（O(1) 追加契约，消灭 O(N²) 的前提）', () => {
    // 渲染层消费约定（useSession 管线）：只有最新 state 被提交给 React，
    // events 引用稳定不影响 memo 契约（无任何消费者把 events 放进依赖数组）。
    const s1 = applyEvent(initConversation('s1'), ev({ type: EventType.RUN_STARTED }));
    const s2 = applyEvent(s1, ev({ type: EventType.RUN_COMPLETED }));
    expect(s2.events).toBe(s1.events);
    expect(s2.events).toHaveLength(2);
  });

  it('projectHistory 重建的 events 与输入事件序列一致', () => {
    const events = [
      ev({ type: EventType.RUN_STARTED }),
      ev({ type: EventType.USER_MESSAGE, data: { content: 'hi', step: 1 } }),
      ev({ type: EventType.MODEL_COMPLETED, data: { content: 'ok', step: 1 } }),
      ev({ type: EventType.RUN_COMPLETED }),
    ];
    const state = projectHistory('s1', events);
    expect(state.events).toEqual(events);
    expect(state.events).toHaveLength(4);
  });

  it('stream-only 事件（model/delta）也进日志——Timeline 显示折叠后的计数视图', () => {
    const state = [
      ev({ type: EventType.MODEL_DELTA, data: { delta: 'a', step: 1 } }),
      ev({ type: EventType.MODEL_DELTA, data: { delta: 'b', step: 1 } }),
    ].reduce(applyEvent, initConversation('s1'));
    expect(state.events).toHaveLength(2);
  });
});

describe('applyEvent — Run 观测字段投影（后端 Gap 1/2）', () => {
  it('MODEL_COMPLETED 捕获 model 名与 usage（可选字段）', () => {
    const s = applyEvent(
      initConversation('s'),
      ev({
        type: EventType.MODEL_COMPLETED,
        data: { content: 'ok', model: 'qwen-plus-0911', usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 } },
        step_id: 1,
      }),
    );
    expect(s.model).toBe('qwen-plus-0911');
    expect(s.usage_total).toEqual({ prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 });
  });

  it('多次 MODEL_COMPLETED 的 usage 累加（run/completed 到达前的运行中视图）', () => {
    let s = initConversation('s');
    for (const total of [150, 200]) {
      s = applyEvent(s, ev({
        type: EventType.MODEL_COMPLETED,
        data: { content: 'x', model: 'm', usage: { prompt_tokens: total, completion_tokens: 0, total_tokens: total } },
        step_id: 1,
      }));
    }
    expect(s.usage_total).toEqual({ prompt_tokens: 350, completion_tokens: 0, total_tokens: 350 });
  });

  it('RUN_COMPLETED 的 usage_total 是权威聚合——覆盖前端累计值，并捕获 cost_usd / trace_id / trace_url', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.MODEL_COMPLETED,
      data: { content: 'x', usage: { prompt_tokens: 999, completion_tokens: 999, total_tokens: 1998 } },
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.RUN_COMPLETED,
      data: {
        usage_total: { prompt_tokens: 1234, completion_tokens: 567, total_tokens: 1801 },
        cost_usd: 0.0024,
        trace_id: 'lf-abc',
        trace_url: 'https://cloud.langfuse.com/project/p1/traces/lf-abc',
      },
    }));
    expect(s.usage_total).toEqual({ prompt_tokens: 1234, completion_tokens: 567, total_tokens: 1801 });
    expect(s.cost_usd).toBe(0.0024);
    expect(s.trace_id).toBe('lf-abc');
    expect(s.trace_url).toBe('https://cloud.langfuse.com/project/p1/traces/lf-abc');
  });

  it('RUN_FAILED 对称下发 trace_id / trace_url（契约 2d7f87a——失败 run 也有可见 trace）', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.RUN_STARTED,
      data: {},
      run_id: 'r1',
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.RUN_FAILED,
      data: {
        reason: 'identical_tool_failure_loop',
        trace_id: 'lf-fail',
        trace_url: 'https://cloud.langfuse.com/project/p1/traces/lf-fail',
      },
      run_id: 'r1',
      step_id: 2,
    }));
    expect(s.run_status).toBe('failed');
    expect(s.trace_id).toBe('lf-fail');
    expect(s.trace_url).toBe('https://cloud.langfuse.com/project/p1/traces/lf-fail');
  });

  it('RUN_CANCELLED（reason=cancelled）也对称下发 trace_id / trace_url', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.RUN_STARTED,
      data: {},
      run_id: 'r1',
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.RUN_FAILED,
      data: {
        reason: 'cancelled',
        trace_id: 'lf-cancel',
        trace_url: 'https://cloud.langfuse.com/project/p1/traces/lf-cancel',
      },
      run_id: 'r1',
      step_id: 2,
    }));
    expect(s.run_cancelled).toBe(true);
    expect(s.trace_id).toBe('lf-cancel');
    expect(s.trace_url).toBe('https://cloud.langfuse.com/project/p1/traces/lf-cancel');
  });

  it('RUN_COMPLETED 未携带观测字段 → 保留前端累计 usage，cost/trace/trace_url 保持 null（不伪造 0）', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.MODEL_COMPLETED,
      data: { content: 'x', usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 } },
      step_id: 1,
    }));
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED, data: {} }));
    expect(s.usage_total).toEqual({ prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 });
    expect(s.cost_usd).toBeNull();
    expect(s.trace_id).toBeNull();
    expect(s.trace_url).toBeNull();
  });

  it('RUN_COMPLETED 携带 trace 字段但值为 null（Langfuse 未启用）→ trace_id / trace_url 保持 null', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.RUN_COMPLETED,
      data: { trace_id: null, trace_url: null },
    }));
    expect(s.trace_id).toBeNull();
    expect(s.trace_url).toBeNull();
  });

  it('RUN_FAILED 携带 trace 字段但值为 null → trace_id / trace_url 保持 null', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.RUN_STARTED,
      data: {},
      run_id: 'r1',
      step_id: 1,
    }));
    const s2 = applyEvent(s, ev({
      type: EventType.RUN_FAILED,
      data: { reason: 'error', trace_id: null, trace_url: null },
      run_id: 'r1',
      step_id: 2,
    }));
    expect(s2.trace_id).toBeNull();
    expect(s2.trace_url).toBeNull();
  });

  it('畸形 usage（字段缺失/类型错误/非有限数）整体按 null 处理——绝不部分伪造', () => {
    for (const bad of [
      { prompt_tokens: 1 },                                  // 缺字段
      { prompt_tokens: '1', completion_tokens: 2, total_tokens: 3 }, // 类型错
      { prompt_tokens: 1, completion_tokens: 2, total_tokens: Number.NaN }, // 非有限
    ]) {
      const s = applyEvent(initConversation('s'), ev({
        type: EventType.MODEL_COMPLETED,
        data: { content: 'x', usage: bad },
        step_id: 1,
      }));
      expect(s.usage_total).toBeNull();
    }
  });

  it('cost_usd 为显式 null 或非有限数 → null（费率表未定义的预期降级）', () => {
    for (const cost of [null, Number.NaN]) {
      const s = applyEvent(initConversation('s'), ev({
        type: EventType.RUN_COMPLETED,
        data: { cost_usd: cost },
      }));
      expect(s.cost_usd).toBeNull();
    }
  });

  it('RUN_FAILED 不捕获 run 级观测字段（契约只定义在 run/completed），已累计 usage 保留', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.MODEL_COMPLETED,
      data: { content: 'x', usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 } },
      step_id: 1,
    }));
    s = applyEvent(s, ev({ type: EventType.RUN_FAILED, data: { usage_total: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }, cost_usd: 1 } }));
    expect(s.usage_total).toEqual({ prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 });
    expect(s.cost_usd).toBeNull();
  });

  it('无观测字段的 MODEL_COMPLETED 不改动 model/usage（保持 null）', () => {
    const s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_COMPLETED, data: { content: 'x' }, step_id: 1 }));
    expect(s.model).toBeNull();
    expect(s.usage_total).toBeNull();
  });
});

describe('summarizeEvent — 事件单行摘要（观测字段 + UnknownSurface 边界）', () => {
  it('MODEL_COMPLETED：观测字段存在 → 「模型 · N tok」；缺失 → 回退内容长度', () => {
    expect(summarizeEvent(ev({
      type: EventType.MODEL_COMPLETED,
      data: { content: 'hello', model: 'qwen-plus-0911', usage: { prompt_tokens: 1, completion_tokens: 2, total_tokens: 1801 } },
    }))).toBe('qwen-plus-0911 · 1801 tok');
    expect(summarizeEvent(ev({ type: EventType.MODEL_COMPLETED, data: { content: 'hello' } }))).toBe('5 字符');
  });

  it('RUN_COMPLETED：聚合用量/成本摘要；全缺失 → 空摘要', () => {
    expect(summarizeEvent(ev({
      type: EventType.RUN_COMPLETED,
      data: { usage_total: { prompt_tokens: 1, completion_tokens: 2, total_tokens: 1801 }, cost_usd: 0.0024 },
    }))).toBe('1801 tok · $0.0024');
    expect(summarizeEvent(ev({ type: EventType.RUN_COMPLETED, data: {} }))).toBe('');
  });

  it('已知生命周期事件返回空摘要——「未知事件」兜底只留给真正未知的类型', () => {
    for (const type of [
      EventType.RUN_STARTED, EventType.RUN_FAILED, EventType.SESSION_STARTED,
      EventType.SESSION_RESUMED, EventType.MODEL_STARTED, EventType.MODEL_FAILED,
    ]) {
      expect(summarizeEvent(ev({ type }))).toBe('');
    }
  });
});

describe('applyEvent — 引用稳定性（流式渲染 memo 契约）', () => {
  /** 构造两个已完成的 turn（step 1 / step 2），返回其状态。 */
  function twoDoneTurns() {
    let s = initConversation('s');
    for (const step of [1, 2]) {
      s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
      s = applyEvent(s, ev({ type: EventType.USER_MESSAGE, data: { content: `q${step}` }, step_id: step }));
      s = applyEvent(s, ev({ type: EventType.MODEL_COMPLETED, data: { content: `a${step}` }, step_id: step }));
    }
    return s;
  }

  it('MODEL_DELTA 只克隆目标 turn——未触及 turn 保持引用', () => {
    const prev = twoDoneTurns();
    const next = applyEvent(prev, ev({ type: EventType.MODEL_DELTA, data: { delta: 'x' }, step_id: 2 }));
    expect(next.turns[0]).toBe(prev.turns[0]);
    expect(next.turns[1]).not.toBe(prev.turns[1]);
    expect(next.turns[1].model.text).toBe('a2x');
  });

  it('不触及 turn 的事件（run/started）保持全部 turn 引用与 turns 数组引用', () => {
    const prev = twoDoneTurns();
    const next = applyEvent(prev, ev({ type: EventType.RUN_STARTED }));
    expect(next.turns).toBe(prev.turns);
    expect(next.turns[0]).toBe(prev.turns[0]);
    expect(next.turns[1]).toBe(prev.turns[1]);
    expect(next.run_status).toBe('running');
  });

  it('RUN_COMPLETED 已 settle 的 turn 保持引用；streaming turn 被替换', () => {
    // run 1 先完成，turn 1/2 拿到 completed_at（settle 完成）
    let s = twoDoneTurns();
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED }));
    // run 2：新 streaming turn
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 3 }));
    const settledTurn = s.turns[1];
    const streamingTurn = s.turns[2];
    const next = applyEvent(s, ev({ type: EventType.RUN_COMPLETED }));
    expect(next.turns[1]).toBe(settledTurn);
    expect(next.turns[2]).not.toBe(streamingTurn);
    expect(next.turns[2].status).toBe('done');
    expect(next.turns[2].model.status).toBe('done');
  });

  it('TOOL_RESULT 只克隆宿主 turn；被更新的 tool 是新对象，其余 tool 引用不变', () => {
    // turn 1 两个工具，turn 2 一个工具
    let s = initConversation('s');
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
    for (const id of ['t1', 't2']) {
      s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: id, tool_name: 'bash', args: {} }, step_id: 1 }));
    }
    s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't3', tool_name: 'bash', args: {} }, step_id: 2 }));
    const otherTool = s.turns[0].tools[1]; // t2
    const otherTurn = s.turns[1];
    const next = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true, data: {} }) },
      step_id: 1,
    }));
    expect(next.turns[1]).toBe(otherTurn);
    expect(next.turns[0].tools[1]).toBe(otherTool);
    expect(next.turns[0].tools[0]).not.toBe(s.turns[0].tools[0]);
    expect(next.turns[0].tools[0].status).toBe('success');
  });

  it('ARTIFACT_CREATED 只替换挂载工具所在 turn 与该工具；同 turn 其它工具引用不变', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
    for (const id of ['t1', 't2']) {
      s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: id, tool_name: 'bash', args: {} }, step_id: 1 }));
    }
    const prev = s;
    const next = applyEvent(s, ev({
      type: EventType.ARTIFACT_CREATED,
      data: { tool_call_id: 't1', artifact_id: 'a1', size: 10, mime_type: 'text/plain', source_tool: 'bash' },
    }));
    expect(next.turns[0]).not.toBe(prev.turns[0]);
    expect(next.turns[0].tools[0]).not.toBe(prev.turns[0].tools[0]);
    expect(next.turns[0].tools[0].artifact?.artifact_id).toBe('a1');
    expect(next.turns[0].tools[1]).toBe(prev.turns[0].tools[1]);
  });

  it('克隆后 turn.model 与 segments[最新 model index] 仍同一对象（别名契约不回退）', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    const next = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'x' }, step_id: 1 }));
    const turn = next.turns[0];
    const lastModel = [...turn.activities].reverse().find((a) => a.kind === 'model');
    expect(lastModel && turn.segments[lastModel.index]).toBe(turn.model);
  });

  it('compactions / reconcile_queue 未被触及的轮次不重建数组（引用保持）', () => {
    const prev = twoDoneTurns();
    const next = applyEvent(prev, ev({ type: EventType.MODEL_DELTA, data: { delta: 'x' }, step_id: 1 }));
    expect(next.compactions).toBe(prev.compactions);
    expect(next.reconcile_queue).toBe(prev.reconcile_queue);
    expect(next.unknown_events).toBe(prev.unknown_events);
  });
});

// ── 后端 df4f7d8 同步批：工具结果新形状 / 收紧语义识别 ──

describe('applyEvent — df4f7d8 新形状', () => {
  it('bash data.cancelled=true → stopped（中断 ≠ 错误），而非 failed', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' }, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: false, message: 'cancelled', data: { cancelled: true } }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].status).toBe('stopped');
    // result 保留原始 data（渲染层读 cancelled 出"已取消"文案）
    expect((s.turns[0].tools[0].result as Record<string, unknown>).cancelled).toBe(true);
  });

  it('bash data.cancelled=false → 正常 ok 判定，不误伤', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' }, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: false, message: 'boom', data: { cancelled: false } }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].status).toBe('failed');
  });

  it('MODEL_FAILED 识别为已知终态事件——不落 unknown_events（零产出收紧语义）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_FAILED, data: { error: 'content filtered' }, step_id: 1 }));
    expect(s.unknown_events).toHaveLength(0);
    expect(s.events).toHaveLength(3);
  });

  it('MEMORY_DEGRADED 识别为已知事件（新增 run_id 字段不破坏投影）', () => {
    const s = applyEvent(initConversation('s'), ev({ type: EventType.MEMORY_DEGRADED, data: { reason: 'store unavailable', run_id: 'r1' } }));
    expect(s.unknown_events).toHaveLength(0);
    expect(s.events).toHaveLength(1);
  });

  it('summarizeEvent：MEMORY_DEGRADED / MODEL_FAILED 空摘要（类型标签足够）', () => {
    expect(summarizeEvent(ev({ type: EventType.MEMORY_DEGRADED, data: { reason: 'x' } }))).toBe('');
    expect(summarizeEvent(ev({ type: EventType.MODEL_FAILED }))).toBe('');
  });

  // ── 事件语义注册表（架构深化 C2）：穷尽性由 tsc 强制
  //    （Record<EventTypeValue, EventSemantics> 缺键即编译失败）；这里锁定
  //    「词汇表内但前端未接线」那批类型的**既有兜底行为**，使未来接线成为
  //    一次显式决定，而不是悄悄改变。

  it('未接线类型仍进 unknown_events（显式登记，行为与重构前一致）', () => {
    for (const type of [
      EventType.COMPACTION_START,
      EventType.COMPACTION_END,
      EventType.MESSAGE_QUEUED,
      EventType.QUEUE_CANCELLED,
      EventType.STEER_REQUESTED,
      EventType.STEER_APPLIED,
    ]) {
      const s = applyEvent(initConversation('s'), ev({ type }));
      expect(s.unknown_events, `${type} 应落 unknown_events`).toHaveLength(1);
    }
  });

  // ART-01（第十一轮真机验收）：运行时只发 artifact/externalized，此前前端只接了
  // 规格里的 artifact/created → 有产物的会话里 Artifacts 页签恒空、还写"未产生 Artifact"。
  it('ARTIFACT_EXTERNALIZED：挂到产出它的 tool 上（与 created 同一投影）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_CALL,
      data: { tool_call_id: 'tc1', tool_name: 'bash', args: {} },
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.ARTIFACT_EXTERNALIZED,
      data: {
        artifact_id: '197e88d95cd917b9',
        session_id: 's',
        source_tool: 'bash',
        tool_call_id: 'tc1',
        size: 39600,
        mime_type: 'text/plain',
      },
    }));

    const tool = s.turns.flatMap((t) => t.tools).find((t) => t.tool_call_id === 'tc1');
    expect(tool?.artifact).toEqual({
      artifact_id: '197e88d95cd917b9',
      size: 39600,
      mime_type: 'text/plain',
      source_tool: 'bash',
    });
    expect(s.unknown_events).toHaveLength(0); // 已接线：不再算"未知事件"
  });

  it('元数据缺失 → null，**不**填默认值（AC5 / #185 AC4：MinIO 不持久化 source_tool）', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash', args: { command: 'x' } }, step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.ARTIFACT_CREATED,
      // 只给 id：这是 MinIO 那类"元数据不持久化"的 store 的真实形态
      data: { artifact_id: 'only-id', session_id: 's', tool_call_id: 't1' },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].artifact).toEqual({
      artifact_id: 'only-id',
      size: null,
      mime_type: null,
      source_tool: null,
    });
  });

  it('ARTIFACT_EXTERNALIZED：找不到宿主 tool_call 时不静默（落 unknown_events）', () => {
    // 与 created 的唯一差别：externalized 自带 artifact_id，是"确实有产物"的独立事实。
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.ARTIFACT_EXTERNALIZED,
      data: { artifact_id: 'orphan', tool_call_id: 'nope', size: 1, mime_type: 'text/plain' },
    }));

    expect(s.unknown_events).toHaveLength(1);
  });

  it('RUN_INTERRUPTED：终态 + run_interrupted 真值 + Timeline 摘要', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
    s = applyEvent(s, ev({
      type: EventType.RUN_INTERRUPTED,
      data: { interrupted_seq: 42, reason: 'process_restart' },
      step_id: 3,
    }));
    expect(s.unknown_events).toHaveLength(0);
    expect(s.run_status).toBe('completed');
    expect(s.run_interrupted).toEqual({ step_id: 3, interrupted_seq: 42, reason: 'process_restart' });
    expect(summarizeEvent(ev({ type: EventType.RUN_INTERRUPTED, data: {}, step_id: 3 }))).toBe('第 3 步中断');
  });

  // APR-01（第十一轮真机）：`approval_queues` 纯内存、run 终结即 GC，而
  // `tool/approval-requested` 永留 JSONL → 孤儿审批每次刷新都重演，点了只有 404。
  // 判据完全来自事件流（运行先于审批结束 ⇒ 这条审批不可能再被 resolve）。
  describe('APR-01 孤儿审批在 run 终结时标 stale', () => {
    const requested = (approvalId = 'ap-1') =>
      ev({
        type: EventType.TOOL_APPROVAL_REQUESTED,
        data: {
          approval_id: approvalId, tool_name: 'bash', tool_call_id: 'tc-1',
          action_type: 'danger', title: 't', description: 'd', arguments_preview: {},
          permission: 'p', policy: 'pol', reason: 'r', allowed_decisions: [],
        },
        step_id: 2,
      });

    it('run/interrupted 后仍 pending 的审批 → stale', () => {
      let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
      s = applyEvent(s, requested());
      expect(s.pending_approvals[0].stale).toBeUndefined(); // 中断前：正常待决

      s = applyEvent(s, ev({
        type: EventType.RUN_INTERRUPTED,
        data: { interrupted_seq: 9, reason: 'process_restart' },
        step_id: 2,
      }));
      expect(s.pending_approvals).toHaveLength(1); // 卡还在（事件不可删）
      expect(s.pending_approvals[0].stale).toBe(true); // 但已不可提交
    });

    it('run 还活着时审批保持可提交（不误伤正常流程）', () => {
      let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
      s = applyEvent(s, requested());
      s = applyEvent(s, ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } })); // 后续事件
      expect(s.pending_approvals[0].stale).toBeUndefined();
    });

    it('正常已决的审批不会被后续 run 终结牵连（已从队列移除）', () => {
      let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
      s = applyEvent(s, requested());
      s = applyEvent(s, ev({
        type: EventType.PERMISSION_RESOLVED,
        data: { approval_id: 'ap-1', decision: 'approve_once', reason: '' },
      }));
      s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED, data: {} }));
      expect(s.pending_approvals).toHaveLength(0);
    });

    it('run/completed 与 run/failed 同样终结孤儿审批（后端同一处 GC）', () => {
      for (const type of [EventType.RUN_COMPLETED, EventType.RUN_FAILED]) {
        let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
        s = applyEvent(s, requested());
        s = applyEvent(s, ev({ type, data: {} }));
        expect(s.pending_approvals[0].stale, `${type} 应标 stale`).toBe(true);
      }
    });

    /** 死锁回归锁：失效审批若继续算作「欠决策」，会话就永久发不出消息
     *  （卡片只读 + composer 禁用，两条路都堵死）。 */
    it('awaitingApproval：失效审批不锁 composer，未失效的才锁', () => {
      let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
      s = applyEvent(s, requested());
      expect(awaitingApproval(s.pending_approvals)).toBe(true); // run 活着 → 真的欠一个决策

      s = applyEvent(s, ev({
        type: EventType.RUN_INTERRUPTED,
        data: { interrupted_seq: 9, reason: 'process_restart' },
      }));
      expect(awaitingApproval(s.pending_approvals)).toBe(false); // 孤儿 → 不锁死会话
      expect(awaitingApproval([])).toBe(false);
    });
  });

  it('OBS-007 RUN_STARTED 清空中断标记：提示不跨 run 存活', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
    s = applyEvent(s, ev({
      type: EventType.RUN_INTERRUPTED,
      data: { interrupted_seq: 42, reason: 'process_restart' },
      step_id: 3,
    }));
    expect(s.run_interrupted).not.toBeNull();
    // 用户接着往下跑：新 run 一开始，「上次运行…中断」这条提示就过期了
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED, data: { turn_index: 2 } }));
    expect(s.run_interrupted).toBeNull();
    expect(s.run_status).toBe('running');
  });

  it('T9 #139 RUN_STARTED：turn_index 落到当轮 turn（per-turn 事实）', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.USER_MESSAGE,
      data: { content: 'hi', step: 1 },
    }));
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].turn_index).toBe(1);
    expect(s.turn_index).toBe(1); // 会话级镜像
  });

  it('T9 #139 多轮：每轮各自保留自己的 turn_index（不被最新 run 覆盖）', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev({ type: EventType.USER_MESSAGE, data: { content: 'a', step: 1 } }));
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED, data: { turn_index: 1 } }));
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED, data: {} }));
    s = applyEvent(s, ev({ type: EventType.USER_MESSAGE, data: { content: 'b', step: 2 } }));
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED, data: { turn_index: 2 } }));
    expect(s.turns.map((t) => t.turn_index)).toEqual([1, 2]);
  });

  it('T9 #139 RUN_STARTED 无前驱轮次：不新建孤立 turn', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.RUN_STARTED,
      data: { turn_index: 4 },
    }));
    expect(s.turns).toHaveLength(0);
    expect(s.run_status).toBe('running');
    expect(s.turn_index).toBe(4); // 会话级仍记录，但无轮可挂
  });

  it('T9 #139 RUN_STARTED 缺 turn_index：字段保持 null（旧版后端）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'x', step: 1 } }));
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED, data: {} }));
    expect(s.turns[0].turn_index).toBeNull();
    expect(s.turn_index).toBeNull();
  });

  it('MODEL_CHANGED：更新 conversation.model + Timeline 摘要', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.MODEL_CHANGED,
      data: { from_provider: 'openai', from_model_id: 'gpt-4o', to_provider: 'deepseek', to_model_id: 'deepseek-chat' },
    }));
    expect(s.unknown_events).toHaveLength(0);
    expect(s.model).toBe('deepseek-chat');
    expect(summarizeEvent(ev({
      type: EventType.MODEL_CHANGED,
      data: { to_model_id: 'deepseek-chat' },
    }))).toBe('模型 → deepseek-chat');
  });

  it('MODEL_CHANGED 缺 to_model_id → 不伪造模型（保持原值 null）', () => {
    const s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_CHANGED, data: {} }));
    expect(s.model).toBeNull();
    expect(summarizeEvent(ev({ type: EventType.MODEL_CHANGED, data: {} }))).toBe('模型已切换');
  });

  it('空文件 read 成功语义：content:"" + total_lines:0 → success 且 result 保留真值', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'read' }, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true, message: 'read', data: { content: '', total_lines: 0 } }) },
      step_id: 1,
    }));
    const tool = s.turns[0].tools[0];
    expect(tool.status).toBe('success');
    expect((tool.result as Record<string, unknown>).total_lines).toBe(0);
  });
});

describe('applyEvent — recover 合成 tool/result 配对（df4f7d8 无 step_id 形状）', () => {
  it('无 step_id 的 tool/result 按 tool_call_id 全局配对，不造幽灵轮次', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, ev({ type: EventType.MODEL_COMPLETED, data: { content: 'x' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 'c1', tool_name: 'bash', args: { command: 'echo' } }, step_id: 1 }));
    // 恢复合成形状：step_id 缺失 + 纯文本 content（非 JSON ToolResult）
    s = applyEvent(s, ev({ type: EventType.TOOL_RESULT, data: { tool_call_id: 'c1', content: '工具执行被中断，结果未知' } }));
    expect(s.turns).toHaveLength(1); // 不造幽灵轮次
    expect(s.turns[0].tools[0].status).toBe('failed'); // 非 JSON content → 失败而非 running
  });

  it('TOOL_RESULT 的 step 与 tool/call 落点不一致时回退全局配对（不丢结果）', () => {
    // 条件配对锁定：step 可解析时走快路径（step 定位宿主轮），但快路径
    // 在目标轮找不到该 tool_call_id 时必须回退按 tool_call_id 全局配对——
    // 否则后端 step 不一致形状下结果会被静默丢弃、工具永远停在 running。
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.TOOL_CALL,
      data: { tool_call_id: 't1', tool_name: 'bash', args: {} },
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true }) },
      step_id: 2, // 与 tool/call 落点（step 1）不一致
    }));
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].tools[0].status).toBe('success');
  });

  it('TOOL_RESULT 正常同 step 快路径配对（step_id 定位，不依赖全局扫描）', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.TOOL_CALL,
      data: { tool_call_id: 't1', tool_name: 'bash', args: {} },
      step_id: 1,
    }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true, data: {} }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].status).toBe('success');
  });
});

// ── da394a9 同步批：取消态 / diff 归档 marker ──

describe('applyEvent — da394a9 新语义', () => {
  it('run/failed.reason=cancelled → run_cancelled=true（取消 ≠ 失败）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, ev({ type: EventType.RUN_FAILED, data: { reason: 'cancelled' } }));
    expect(s.run_cancelled).toBe(true);
    expect(s.run_status).toBe('failed'); // 生命周期仍是 failed 终态
  });

  it('run/failed 无 reason（真实失败）→ run_cancelled=false', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED }));
    s = applyEvent(s, ev({ type: EventType.RUN_FAILED }));
    expect(s.run_cancelled).toBe(false);
  });

  it('取消后再 completed → run_cancelled 复位（rebuild 不残留旧态）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_FAILED, data: { reason: 'cancelled' } }));
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED }));
    expect(s.run_cancelled).toBe(false);
  });

  it('diff before 内嵌 marker → archived=true + artifactId + artifactTool', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'write' }, step_id: 1 }));
    const summary = '文件过大已归档。use inspect_artifact(abc-123) 查看全文';
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true, data: { before: '', after: summary, truncated: true } }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].diff).toEqual({
      before: '', after: summary, truncated: true, archived: true, artifactId: 'abc-123',
      artifactTool: 'inspect_artifact',
    });
  });

  /* 默认部署（Local / MinIO）发的 marker 用 `read_artifact`。此前正则只认
     inspect_artifact ⇒ 默认部署上 diff.archived 永远不成立（#186 AC4）。 */
  it('diff 内嵌 read_artifact marker（默认部署）也认，并原样带下工具名', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'write' }, step_id: 1 }));
    const summary = '文件过大已归档。use read_artifact(0123456789abcdef) to view]';
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true, data: { before: summary, after: '', truncated: true } }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].diff).toEqual({
      before: summary, after: '', truncated: true, archived: true,
      artifactId: '0123456789abcdef', artifactTool: 'read_artifact',
    });
  });

  it('diff 无 marker → 无 archived 字段（形状不变，零伪造）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'write' }, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_RESULT,
      data: { tool_call_id: 't1', content: JSON.stringify({ ok: true, data: { before: 'a', after: 'b' } }) },
      step_id: 1,
    }));
    expect(s.turns[0].tools[0].diff).toEqual({ before: 'a', after: 'b', truncated: false });
  });
});

// ── Phase 12 白盒透明：tool/failure-guard + model/fallback（ADR-0014）──
describe('Phase 12 — failure-guard / fallback 投影', () => {
  it('TOOL_FAILURE_GUARD soft → 落所在轮 notices，不进 unknown_events', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_FAILURE_GUARD,
      data: { level: 'soft', tool_name: 'bash', fingerprint: 'fp-1', consecutive_failures: 3 },
      step_id: 1,
    }));
    expect(s.turns[0].notices).toEqual([
      { level: 'soft', tool_name: 'bash', consecutive_failures: 3 },
    ]);
    expect(s.unknown_events).toHaveLength(0);
  });

  it('TOOL_FAILURE_GUARD hard → level hard（终止标记语义）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 2 }));
    s = applyEvent(s, ev({
      type: EventType.TOOL_FAILURE_GUARD,
      data: { level: 'hard', tool_name: 'bash', fingerprint: 'fp-2', consecutive_failures: 3 },
      step_id: 2,
    }));
    expect(s.turns[0].notices).toEqual([
      { level: 'hard', tool_name: 'bash', consecutive_failures: 3 },
    ]);
  });

  it('Harness 注入的纠正 user/message（injected_by）标记 turn——不冒充真人输入', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.USER_MESSAGE,
      data: { content: 'bash 连续失败，请改用 PowerShell 重试', injected_by: 'tool_failure_guard', step: 2 },
      step_id: 2,
    }));
    expect(s.turns).toHaveLength(2);
    expect(s.turns[1].injected_by).toBe('tool_failure_guard');
    expect(s.turns[1].user_message).toBe('bash 连续失败，请改用 PowerShell 重试');
  });

  it('真人 user/message 无 injected_by → turn 不带标记', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.USER_MESSAGE, data: { content: 'hi', step: 1 }, step_id: 1,
    }));
    expect(s.turns[0].injected_by).toBeUndefined();
  });

  it('MODEL_FALLBACK → 记录切换 + 后续 model 切到 to_model', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.MODEL_FALLBACK,
      data: { from_model: 'qwen-a', to_model: 'qwen-b', reason: 'ModelStallError' },
      step_id: 1,
    }));
    expect(s.model_fallback).toEqual({ from_model: 'qwen-a', to_model: 'qwen-b', reason: 'ModelStallError' });
    expect(s.model).toBe('qwen-b');
  });

  it('MODEL_FALLBACK 字段缺失不伪造（to_model 缺失 → 不记录切换）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({
      type: EventType.MODEL_FALLBACK,
      data: { from_model: 'qwen-a', reason: 'ModelStallError' },
      step_id: 1,
    }));
    expect(s.model_fallback).toBeNull();
    expect(s.unknown_events).toHaveLength(0); // 已知事件，只是形状不完整
  });

  it('summarizeEvent：guard 行（工具 ×次数 熔断 · 级别）+ fallback 行（from → to · 原因）', () => {
    expect(summarizeEvent(ev({
      type: EventType.TOOL_FAILURE_GUARD,
      data: { level: 'soft', tool_name: 'bash', consecutive_failures: 3 },
    }))).toBe('bash ×3 熔断 · soft');
    expect(summarizeEvent(ev({
      type: EventType.TOOL_FAILURE_GUARD,
      data: { level: 'hard', tool_name: 'bash', consecutive_failures: 3 },
    }))).toBe('bash ×3 熔断 · hard');
    expect(summarizeEvent(ev({
      type: EventType.MODEL_FALLBACK,
      data: { from_model: 'qwen-a', to_model: 'qwen-b', reason: 'ModelStallError' },
    }))).toBe('qwen-a → qwen-b · ModelStallError');
  });
});

describe('Phase 13 — delegation 投影（ADR-0015）', () => {
  const started = (child: string, target = 'research_review', step = 1) => ev({
    type: EventType.AGENT_DELEGATION_STARTED,
    data: { target, task: `为 ${target} 准备任务`, child_session_id: child },
    step_id: step,
  });
  const finished = (child: string, status: 'completed' | 'failed', summary: string, step = 1) => ev({
    type: EventType.AGENT_DELEGATION_FINISHED,
    data: { target: 'research_review', child_session_id: child, status, summary },
    step_id: step,
  });

  it('STARTED → turn.delegations 建节点 running + activities 追加编排项（true event order）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, started('child-1'));
    expect(s.turns[0].delegations).toEqual([
      {
        target: 'research_review',
        task: '为 research_review 准备任务',
        child_session_id: 'child-1',
        status: 'running',
        started_at: expect.any(String),
      },
    ]);
    expect(s.turns[0].activities).toEqual([
      { kind: 'model', index: 0 },
      { kind: 'delegation', child_session_id: 'child-1' },
    ]);
    expect(s.unknown_events).toHaveLength(0);
    // Trace Ladder 视图：deriveChain 吐出编排节点（真事件序）
    const chain = deriveChain(s.turns[0]);
    expect(chain[1]).toEqual({ kind: 'delegation', delegation: s.turns[0].delegations![0] });
  });

  it('FINISHED completed → 回填 status/summary/completed_at；failed → failed', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, started('child-1'));
    s = applyEvent(s, finished('child-1', 'completed', '调研完成：3 篇核心文献'));
    expect(s.turns[0].delegations![0].status).toBe('completed');
    expect(s.turns[0].delegations![0].summary).toBe('调研完成：3 篇核心文献');
    expect(s.turns[0].delegations![0].completed_at).toEqual(expect.any(String));
    s = applyEvent(s, started('child-2', 'coding'));
    s = applyEvent(s, finished('child-2', 'failed', '子代理执行出错'));
    expect(s.turns[0].delegations![1].status).toBe('failed');
  });

  it('并行双委派两对事件（完成顺序落盘）→ 按 child_session_id 各自回填，顺序无关', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, started('child-a', 'research_review'));
    s = applyEvent(s, started('child-b', 'coding'));
    s = applyEvent(s, finished('child-b', 'completed', '编码完成'));
    s = applyEvent(s, finished('child-a', 'failed', '调研超限'));
    const ds = s.turns[0].delegations!;
    expect(ds).toHaveLength(2);
    expect(ds.find((d) => d.child_session_id === 'child-a')).toMatchObject({
      status: 'failed',
      target: 'research_review',
    });
    expect(ds.find((d) => d.child_session_id === 'child-b')).toMatchObject({
      status: 'completed',
      target: 'coding',
    });
  });

  it('重复 STARTED（重放）→ 幂等不重复建节点', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, started('child-1'));
    s = applyEvent(s, started('child-1'));
    expect(s.turns[0].delegations).toHaveLength(1);
    expect(s.turns[0].activities.filter((a) => a.kind === 'delegation')).toHaveLength(1);
  });

  it('FINISHED 先于 STARTED（乱序持久化防御）→ 从 finish 真值建终态节点，不虚构 task', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, finished('child-1', 'completed', '直接到达的结果'));
    const d = s.turns[0].delegations![0];
    expect(d.status).toBe('completed');
    expect(d.summary).toBe('直接到达的结果');
    expect(d.task).toBe('');
    expect(d.started_at).toBeUndefined();
  });

  it('run 结束时仍在 running 的委派 → stopped（中断 ≠ 错误，与 tool 同语义域）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, started('child-1'));
    s = applyEvent(s, ev({ type: EventType.RUN_FAILED }));
    expect(s.turns[0].delegations![0].status).toBe('stopped');
  });

  it('child_session_id 缺失 → 不建节点（不虚构身份），事件仍在 events 日志', () => {
    const s = applyEvent(initConversation('s'), ev({
      type: EventType.AGENT_DELEGATION_STARTED,
      data: { target: 'coding', task: 't' },
      step_id: 1,
    }));
    expect(s.turns).toHaveLength(0);
    expect(s.events).toHaveLength(1);
    expect(s.unknown_events).toHaveLength(0);
  });

  it('summary 溢出指针后缀（后端 #86 冻结契约）→ hasSummaryOverflow 识别，summary 保真不剥离', () => {
    const overflowed = `${'x'.repeat(8192)} [summary 超限已截断至 8192 字符；完整输出见 child session child-1]`;
    expect(hasSummaryOverflow(overflowed)).toBe(true);
    expect(hasSummaryOverflow('正常长度的结果摘要')).toBe(false);
    let s = applyEvent(initConversation('s'), started('child-1'));
    s = applyEvent(s, finished('child-1', 'completed', overflowed));
    expect(s.turns[0].delegations![0].summary).toBe(overflowed);
  });

  it('summarizeEvent：started 行 `委派 → target`；finished 行 `target 完成/失败 · 摘要`', () => {
    expect(summarizeEvent(started('child-1', 'coding'))).toBe('委派 → coding');
    expect(summarizeEvent(finished('child-1', 'completed', '三篇文献综述'))).toBe(
      'research_review 完成 · 三篇文献综述',
    );
    expect(summarizeEvent(finished('child-1', 'failed', ''))).toBe('research_review 失败');
  });

  it('copy-on-write：委派回填只克隆宿主 turn；同会话其它 turn 引用不变', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, started('child-1'));
    s = applyEvent(s, ev({ type: EventType.MODEL_STARTED, step_id: 2 }));
    s = applyEvent(s, ev({ type: EventType.USER_MESSAGE, data: { content: '下一轮', step: 2 }, step_id: 2 }));
    const turn1Before = s.turns[0];
    const turn2Before = s.turns[1];
    s = applyEvent(s, finished('child-1', 'completed', 'done'));
    expect(s.turns[0]).not.toBe(turn1Before);
    expect(s.turns[1]).toBe(turn2Before);
  });
});

describe('T1 — seq 幂等去重 + 帧校验（#94，spec 02 §6/§14）', () => {
  it('重复 seq 的持久事件整帧丢弃（at-least-once 不重复投影）', () => {
    const first = ev({ type: EventType.USER_MESSAGE, data: { content: 'hi', step: 1 }, seq: 5 });
    const s1 = applyEvent(initConversation('s'), first);
    expect(s1.events).toHaveLength(1);
    const s2 = applyEvent(s1, { ...first });
    expect(s2.events).toHaveLength(1);
    expect(s2.turns).toHaveLength(1);
    expect(s2.turns[0].user_message).toBe('hi');
  });

  it('重复 seq 不重复进 events 日志，也不产生 unknown_events', () => {
    const e = ev({ type: EventType.MODEL_COMPLETED, data: { content: 'x', step: 1 }, seq: 2 });
    const s = applyEvent(applyEvent(initConversation('s'), e), { ...e });
    expect(s.events).toHaveLength(1);
    expect(s.unknown_events).toHaveLength(0);
  });

  it('null seq（model/delta 等流式帧）永不去重', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'a' }, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'b' }, step_id: 1 }));
    expect(s.turns[0].model.text).toBe('ab');
  });

  it('未见过的回跳 seq（乱序补达）不丢弃——精确重复才幂等，乱序小窗 DEFER', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, seq: 5 }));
    s = applyEvent(s, ev({ type: EventType.RUN_COMPLETED, seq: 3 }));
    expect(s.events).toHaveLength(2);
    expect(s.run_status).toBe('completed');
  });

  it('畸形帧（type 非字符串）隔离进 unknown_events——不崩、不投影、verbatim 留档', () => {
    const s = applyEvent(
      initConversation('s'),
      { data: {}, seq: 1, run_id: null, step_id: null, type: 123 } as unknown as AgentEvent,
    );
    expect(s.unknown_events).toHaveLength(1);
    expect(s.unknown_events[0].type).toBe('malformed/event');
    expect(s.turns).toHaveLength(0);
    expect(s.events).toHaveLength(1);
  });

  it('缺 data 的帧不崩溃：校验层归一化为 {}（原 data.content 直取的 TypeError 向量）', () => {
    const s = applyEvent(
      initConversation('s'),
      { type: EventType.USER_MESSAGE, seq: null, run_id: null, step_id: null } as unknown as AgentEvent,
    );
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].user_message).toBe('');
  });
});

describe('T2 — reasoning 事件投影（#95，契约 C1，spec 03 §5/§7）', () => {
  const rStarted = (step: number, blockId: string | undefined, extra: Partial<AgentEvent> = {}) =>
    ev({
      type: 'reasoning/started',
      data: blockId === undefined ? {} : { block_id: blockId },
      step_id: step,
      ...extra,
    });
  const rDelta = (step: number, blockId: string | undefined, delta: string, extra: Partial<AgentEvent> = {}) =>
    ev({
      type: 'reasoning/delta',
      data: { delta, ...(blockId === undefined ? {} : { block_id: blockId }) },
      step_id: step,
      ...extra,
    });
  const rTerminal = (type: string, step: number, blockId: string | undefined, extra: Partial<AgentEvent> = {}) =>
    ev({
      type,
      data: blockId === undefined ? {} : { block_id: blockId },
      step_id: step,
      ...extra,
    });

  it('started→delta→completed 聚合为一个 block，activities 记录真实顺序', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'b1'));
    s = applyEvent(s, rDelta(1, 'b1', '想'));
    s = applyEvent(s, rDelta(1, 'b1', '一下'));
    s = applyEvent(s, rTerminal('reasoning/completed', 1, 'b1'));
    const t = s.turns[0];
    expect(t.reasoningById?.['b1']).toMatchObject({ blockId: 'b1', text: '想一下', status: 'completed' });
    expect(t.activities).toContainEqual({ kind: 'reasoning', blockId: 'b1' });
  });

  it('S2 分段语义：reasoning → tool → reasoning 是兄弟节点，deriveChain 保序', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'b1'));
    s = applyEvent(s, rTerminal('reasoning/completed', 1, 'b1'));
    s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { name: 'bash', tool_call_id: 'tc1' }, step_id: 1 }));
    s = applyEvent(s, rStarted(1, 'b2'));
    s = applyEvent(s, rTerminal('reasoning/completed', 1, 'b2'));
    const kinds = deriveChain(s.turns[0]).map((n) => n.kind);
    expect(kinds).toEqual(['reasoning', 'tool', 'reasoning']);
  });

  it('completed 不可变：终态后的迟到 delta 不改文本（spec 02 §8.1）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'b1'));
    s = applyEvent(s, rTerminal('reasoning/completed', 1, 'b1'));
    s = applyEvent(s, rDelta(1, 'b1', '迟到'));
    expect(s.turns[0].reasoningById?.['b1']).toMatchObject({ text: '', status: 'completed' });
  });

  it('interrupted 保留已聚合文本并终结（PRD §16.4：部分内容不擦除）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'b1'));
    s = applyEvent(s, rDelta(1, 'b1', 'partial '));
    s = applyEvent(s, rDelta(1, 'b1', 'text'));
    s = applyEvent(s, rTerminal('reasoning/interrupted', 1, 'b1'));
    expect(s.turns[0].reasoningById?.['b1']).toMatchObject({ text: 'partial text', status: 'interrupted' });
  });

  it('visibility=internal 不建用户可见块（spec 02 §15 硬边界），events 日志仍 verbatim', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'x', { data: { block_id: 'x', visibility: 'internal' } }));
    s = applyEvent(s, rDelta(1, 'x', 'secret', { data: { delta: 'secret', block_id: 'x', visibility: 'internal' } }));
    s = applyEvent(s, rTerminal('reasoning/completed', 1, 'x', { data: { block_id: 'x', visibility: 'internal' } }));
    expect(s.turns[0].reasoningById?.['x']).toBeUndefined();
    expect(s.turns[0].activities.some((a) => a.kind === 'reasoning')).toBe(false);
    expect(s.events).toHaveLength(4);
  });

  it('缺 block_id 的 delta 落到本 turn 最近一个 streaming block（宽松契约降级）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'b1'));
    s = applyEvent(s, rDelta(1, undefined, 'fallthrough'));
    expect(s.turns[0].reasoningById?.['b1']).toMatchObject({ text: 'fallthrough', status: 'streaming' });
  });

  it('无 started 直接 delta：合成 key 建块（delta 是事实，零伪造建块）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rDelta(1, undefined, 'orphan'));
    const blocks = s.turns[0].reasoningById ?? {};
    const ids = Object.keys(blocks);
    expect(ids).toHaveLength(1);
    expect(Object.values(blocks)[0]).toMatchObject({ text: 'orphan', status: 'streaming' });
    expect(s.turns[0].activities.some((a) => a.kind === 'reasoning')).toBe(true);
  });

  it('source 缺省为 model；data.source=agent 显式可辨（S1 双来源）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, rStarted(1, 'b1'));
    s = applyEvent(s, rStarted(1, 'b2', { data: { block_id: 'b2', source: 'agent' } }));
    expect(s.turns[0].reasoningById?.['b1']).toMatchObject({ source: 'model' });
    expect(s.turns[0].reasoningById?.['b2']).toMatchObject({ source: 'agent' });
  });

  it('历史重放同构：projectHistory === 逐帧 applyEvent（持久事件恒带 time）', () => {
    const events = [
      ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 }, seq: 1, time: '2026-09-06T00:00:01Z' }),
      rStarted(1, 'b1', { seq: 2, time: '2026-09-06T00:00:02Z' }),
      rDelta(1, 'b1', 'a', { seq: 3, time: '2026-09-06T00:00:03Z' }),
      rTerminal('reasoning/completed', 1, 'b1', { seq: 4, time: '2026-09-06T00:00:04Z' }),
    ];
    let live = initConversation('s');
    for (const e of events) live = applyEvent(live, e);
    expect(projectHistory('s', events)).toEqual(live);
  });

  it('summarizeEvent：终态有摘要、delta 记字符数（同 model/delta 惯例）', () => {
    expect(summarizeEvent(rTerminal('reasoning/completed', 1, 'b1'))).toContain('思考');
    expect(summarizeEvent(rTerminal('reasoning/interrupted', 1, 'b1'))).toContain('中断');
    expect(summarizeEvent(rStarted(1, 'b1'))).toContain('思考');
    expect(summarizeEvent(rDelta(1, 'b1', 'xyz'))).toBe('+3 字符');
  });
});

describe('T3 — tool/output_delta 流式输出（#96，契约 C2，spec 03 §9.3）', () => {
  const callEvent = (id: string, step = 1) =>
    ev({ type: EventType.TOOL_CALL, data: { tool_call_id: id, tool_name: 'bash', args: { command: 'ls' } }, step_id: step });
  const outDelta = (id: string, channel: string, delta: string, extra: Partial<AgentEvent> = {}) =>
    ev({ type: 'tool/output_delta', data: { tool_call_id: id, channel, delta }, step_id: 1, ...extra });
  const resultEvent = (id: string, step = 1, extra: Partial<AgentEvent> = {}) =>
    ev({ type: EventType.TOOL_RESULT, data: { tool_call_id: id, content: JSON.stringify({ ok: true, data: { exit_code: 0 } }) }, step_id: step, ...extra });

  it('stdout delta 逐段累积到运行中工具的 output 缓冲', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, callEvent('tc1'));
    s = applyEvent(s, outDelta('tc1', 'stdout', 'RUN'));
    s = applyEvent(s, outDelta('tc1', 'stdout', ' tests\n'));
    expect(s.turns[0].tools[0].output).toEqual([{ channel: 'stdout', text: 'RUN tests\n' }]);
    expect(s.turns[0].tools[0].status).toBe('running');
  });

  it('stderr 独立通道保真——双通道不串（验收：channel 徽标/分色）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, callEvent('tc1'));
    s = applyEvent(s, outDelta('tc1', 'stdout', 'out\n'));
    s = applyEvent(s, outDelta('tc1', 'stderr', 'warn\n'));
    expect(s.turns[0].tools[0].output).toEqual([
      { channel: 'stdout', text: 'out\n' },
      { channel: 'stderr', text: 'warn\n' },
    ]);
  });

  it('result 到达：终态校准且流式 chunks 保留（流式内容不丢弃）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, callEvent('tc1'));
    s = applyEvent(s, outDelta('tc1', 'stdout', 'partial'));
    s = applyEvent(s, resultEvent('tc1'));
    const tool = s.turns[0].tools[0];
    expect(tool.status).toBe('success');
    expect(tool.output).toEqual([{ channel: 'stdout', text: 'partial' }]);
  });

  it('未知 tool_call_id 的 output_delta 不伪造工具，事件仍 verbatim 在 events', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, outDelta('ghost', 'stdout', 'x'));
    expect(s.turns[0].tools).toHaveLength(0);
    expect(s.events).toHaveLength(2);
    expect(s.unknown_events).toHaveLength(0);
  });

  it('channel 非 stdout/stderr 的帧丢弃（契约 C2 严格两通道，不误标）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, callEvent('tc1'));
    s = applyEvent(s, outDelta('tc1', 'bogus', 'x'));
    expect(s.turns[0].tools[0].output).toBeUndefined();
  });

  it('慢路径配对：delta 无 step_id 也能按 tool_call_id 全局定位宿主轮', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, callEvent('tc1'));
    s = applyEvent(s, ev({ type: 'tool/output_delta', data: { tool_call_id: 'tc1', channel: 'stdout', delta: 'x' }, step_id: null }));
    expect(s.turns[0].tools[0].output).toEqual([{ channel: 'stdout', text: 'x' }]);
  });

  it('历史重放同构：output_delta + result 重放与逐帧应用一致', () => {
    const events = [
      ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 }, seq: 1, time: '2026-09-06T00:00:01Z' }),
      { ...callEvent('tc1'), seq: 2, time: '2026-09-06T00:00:02Z' },
      { ...outDelta('tc1', 'stdout', 'a\n'), seq: 3, time: '2026-09-06T00:00:03Z' },
      { ...outDelta('tc1', 'stderr', 'b\n'), seq: 4, time: '2026-09-06T00:00:04Z' },
      { ...resultEvent('tc1'), seq: 5, time: '2026-09-06T00:00:05Z' },
    ];
    let live = initConversation('s');
    for (const e of events) live = applyEvent(live, e);
    expect(projectHistory('s', events)).toEqual(live);
  });

  it('summarizeEvent：output_delta 同 delta 惯例（+N 字符）', () => {
    expect(summarizeEvent(outDelta('tc1', 'stdout', 'xyz'))).toBe('+3 字符');
  });

  it('交替通道流有界收缩：chunk 数超上限触发前半合并，文本零丢失', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    s = applyEvent(s, callEvent('tc1'));
    for (let i = 0; i < 1200; i++) {
      s = applyEvent(s, outDelta('tc1', i % 2 ? 'stderr' : 'stdout', `L${i}\n`));
    }
    const chunks = s.turns[0].tools[0].output ?? [];
    expect(chunks.length).toBeLessThanOrEqual(512);
    const total = chunks.reduce((n, c) => n + c.text.length, 0);
    expect(total).toBeGreaterThan(0);
    expect(chunks[0].text).toContain('L0\n');
    expect(chunks[chunks.length - 1].text).toContain('L1199\n');
  });
});

describe('code-review 修复批回归', () => {
  it('run_id 捕获：事件携带 run_id 时记录（PRD §8.2 头部 Run ID），缺失不清除归属', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.RUN_STARTED, run_id: 'run-abc' }));
    expect(s.run_id).toBe('run-abc');
    // 无 run_id 的事件（null）保持原值——不回退 session_id、不清空
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'x' }, step_id: 1 }));
    expect(s.run_id).toBe('run-abc');
    // 无任何 run_id 事件 → null（UI 隐藏该位，零伪造）
    const empty = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'q', step: 1 } }));
    expect(empty.run_id).toBeNull();
  });

  it('cloneTurn 对 delegations 数组浅拷贝（与 tools/activities 同规则）；未触及元素引用保持', () => {
    let s = applyEvent(initConversation('s'), ev({
      type: EventType.AGENT_DELEGATION_STARTED,
      data: { target: 'coding', task: 't', child_session_id: 'c1' },
      step_id: 1,
    }));
    const arrBefore = s.turns[0].delegations;
    // TOOL_CALL 触发同轮 cloneTurn
    s = applyEvent(s, ev({ type: EventType.TOOL_CALL, data: { tool_call_id: 't1', tool_name: 'bash' }, step_id: 1 }));
    expect(s.turns[0].delegations).not.toBe(arrBefore); // 数组已拷贝——原地 push 不会再污染旧快照
    expect(s.turns[0].delegations![0]).toBe(arrBefore![0]); // 未触及的委派对象引用保持（memo 前提）
  });
});

// ── T-contract（#116）：text/delta 词汇 + envelope block_id（后端契约回执）──
describe('T-contract — text/delta 词汇 + envelope block_id（#116，后端契约回执）', () => {
  const T = '2026-09-07T00:00:00Z';

  it('text/delta 累积进 turn.model.text（durable，与 MODEL_DELTA 同构）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TEXT_DELTA, data: { delta: '你好' }, seq: 5, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TEXT_DELTA, data: { delta: '世界' }, seq: 6, step_id: 1 }));
    expect(s.turns[0].model.text).toBe('你好世界');
    expect(s.turns[0].model.status).toBe('streaming');
  });

  it('text/delta 是 durable：重复 seq 整帧去重，不重复追加、不入事件日志', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TEXT_DELTA, data: { delta: 'abc' }, seq: 7, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.TEXT_DELTA, data: { delta: 'abc' }, seq: 7, step_id: 1 }));
    expect(s.turns[0].model.text).toBe('abc');
    expect(s.seenSeqs.has(7)).toBe(true);
    // model/started(seq=null) + 首个 text/delta；重复帧整帧丢弃（不进日志）
    expect(s.events).toHaveLength(2);
  });

  it('text/delta 重放同构：无 model/started 的持久历史重建同一文本', () => {
    const events = [
      ev({ type: EventType.SESSION_STARTED, seq: 1, time: T }),
      ev({ type: EventType.RUN_STARTED, seq: 2, time: T }),
      ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, seq: 3, step_id: 1, time: T }),
      ev({ type: EventType.TEXT_DELTA, data: { delta: '你好' }, seq: 4, step_id: 1, time: T }),
      ev({ type: EventType.TEXT_DELTA, data: { delta: '世界' }, seq: 5, step_id: 1, time: T }),
      ev({ type: EventType.MODEL_COMPLETED, data: { content: '你好世界' }, seq: 6, step_id: 1, time: T }),
      ev({ type: EventType.RUN_COMPLETED, seq: 7, time: T }),
    ];
    const s = projectHistory('s', events);
    expect(s.turns[0].model.text).toBe('你好世界');
    expect(s.turns[0].model.status).toBe('done');
    expect(s.unknown_events).toHaveLength(0); // text/delta 是已知词汇，不落兜底
  });

  it('reasoning 按 envelope block_id 聚合（不再合成散键）', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/started', data: { source: 'model' }, block_id: 'rsn-3-1', seq: 10, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/delta', data: { delta: '想', source: 'model' }, block_id: 'rsn-3-1', seq: 11, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/delta', data: { delta: '考', source: 'model' }, block_id: 'rsn-3-1', seq: 12, step_id: 3 }));
    const blocks = s.turns[0].reasoningById!;
    expect(Object.keys(blocks)).toEqual(['rsn-3-1']);
    expect(blocks['rsn-3-1'].text).toBe('想考');
  });

  it('同 step 双块不串：post-tool 新块按 envelope block_id 分开聚合', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/started', data: { source: 'model' }, block_id: 'rsn-3-1', seq: 10, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/delta', data: { delta: '一段', source: 'model' }, block_id: 'rsn-3-1', seq: 11, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/completed', data: {}, block_id: 'rsn-3-1', seq: 12, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/started', data: { source: 'model' }, block_id: 'rsn-3-2', seq: 13, step_id: 3 }));
    s = applyEvent(s, ev({ type: 'reasoning/delta', data: { delta: '二段', source: 'model' }, block_id: 'rsn-3-2', seq: 14, step_id: 3 }));
    const blocks = s.turns[0].reasoningById!;
    expect(blocks['rsn-3-1']).toMatchObject({ text: '一段', status: 'completed' });
    expect(blocks['rsn-3-2']).toMatchObject({ text: '二段', status: 'streaming' });
    expect(s.turns[0].activities.filter((a) => a.kind === 'reasoning')).toHaveLength(2);
  });

  it('summarizeEvent(text/delta) 沿 +N 字符惯例', () => {
    expect(summarizeEvent(ev({ type: EventType.TEXT_DELTA, data: { delta: 'abcd' } }))).toBe('+4 字符');
  });

  it('T4 #97 重连重放无重复：live 已应用 [1..3]，从 seq2 重放 [2..4] —— 等价干净应用且日志无重复', () => {
    const mk = (seq: number, delta: string) =>
      ev({ type: EventType.TEXT_DELTA, data: { delta }, seq, step_id: 1, time: T });
    const clean = [ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, seq: 1, step_id: 1, time: T }), mk(2, 'A'), mk(3, 'B'), mk(4, 'C')];
    // 重连路径：conv 不重置——同一状态继续 applyEvent，重放帧经 seenSeqs 去重
    let resumed = applyEvent(initConversation('s'), clean[0]);
    resumed = applyEvent(resumed, clean[1]);
    resumed = applyEvent(resumed, clean[1]); // 重放重复帧（重连窗口重叠）
    resumed = applyEvent(resumed, clean[2]);
    resumed = applyEvent(resumed, clean[3]);
    expect(resumed.turns[0].model.text).toBe('ABC');
    expect(resumed.events).toHaveLength(4); // 重复帧整帧不入日志
    expect([...resumed.seenSeqs].sort((a, b) => a - b)).toEqual([1, 2, 3, 4]);
    // 与不重放的干净应用逐块等价
    const direct = projectHistory('s', clean);
    expect(resumed.turns[0].model).toEqual(direct.turns[0].model);
  });

  it('legacy 容错：model/delta 与 data.block_id 路径保持可用', () => {
    let s = applyEvent(initConversation('s'), ev({ type: EventType.MODEL_STARTED, step_id: 1 }));
    s = applyEvent(s, ev({ type: EventType.MODEL_DELTA, data: { delta: 'old' }, step_id: 1 }));
    expect(s.turns[0].model.text).toBe('old');
    s = applyEvent(s, ev({ type: 'reasoning/started', data: { source: 'model', block_id: 'legacy' }, seq: 20, step_id: 1 }));
    s = applyEvent(s, ev({ type: 'reasoning/delta', data: { delta: 'x', source: 'model', block_id: 'legacy' }, seq: 21, step_id: 1 }));
    expect(s.turns[0].reasoningById!['legacy'].text).toBe('x');
  });

  it('取消轮次重放：text/delta 已落盘但无 model/completed——文本保留且可渲染', () => {
    // T5 #98 使 run/failed(reason=cancelled) → onDone → viewing → projectHistory
    // 成为一级行为：model/started 是 stream-only 不入历史，delta 分支必须回填
    // model activity——否则 activities 为空，Conversation 渲染门跳过整个模型块。
    const events = [
      ev({ type: EventType.SESSION_STARTED, seq: 1, time: T }),
      ev({ type: EventType.RUN_STARTED, seq: 2, time: T }),
      ev({ type: EventType.USER_MESSAGE, data: { content: 'hi' }, seq: 3, step_id: 1, time: T }),
      ev({ type: EventType.TEXT_DELTA, data: { delta: '部分回答' }, seq: 4, step_id: 1, time: T }),
      ev({ type: EventType.RUN_FAILED, data: { reason: 'cancelled' }, seq: 5, time: T }),
    ];
    const s = projectHistory('s', events);
    expect(s.turns[0].model.text).toBe('部分回答');
    expect(s.turns[0].activities.some((a) => a.kind === 'model')).toBe(true);
    expect(s.run_cancelled).toBe(true);
  });
});

describe('firstForkableTurnIndex — 「最早可分叉的那一轮」锚点选择', () => {
  it('两个真实用户轮：返回第一轮（seq 最小）', () => {
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '一', step: 1 }, seq: 2 }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '二', step: 2 }, seq: 5 }),
    ]);
    expect(firstForkableTurnIndex(s.turns)).toBe(0);
  });

  it('空会话：返回 -1（没有可分叉的轮）', () => {
    expect(firstForkableTurnIndex([])).toBe(-1);
  });

  it('注入轮排在前面时跳过它，锚点落在第一个真人轮', () => {
    // 注入消息（failure-guard 纠正）虽在最前、且 seq 更小，但不是真人输入、
    // 不渲染分叉按钮——锚点必须是后面的真实用户轮。（结果与按数组顺序取第一个
    // 非空锚点相同，本用例是行为记录；区分两者的是下面的乱序用例。）
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '纠正', step: 1, injected_by: 'failure-guard' }, seq: 2 }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '真人', step: 2 }, seq: 5 }),
    ]);
    expect(s.turns[0].injected_by).toBe('failure-guard');
    expect(firstForkableTurnIndex(s.turns)).toBe(1);
  });

  it('首轮无锚点（旧版后端未带 seq）时跳过它，不在它上面标「空会话」', () => {
    // 行为记录（**不是**回归锁）：跳过后返回 1——与「按数组顺序取第一个非空锚点」
    // 的旧实现同结果，本用例区分不了两者。真正能区分的是下面的乱序用例。
    // 注意它记录的后果：`Conversation` 只在结果 === 0 时才挂「child 是空会话」
    // 提示，所以这里返回 1 意味着第 1 轮拿到的是普通「从此处分叉」——turn 0 的
    // 事件排在锚点之前，说「空会话」就是谎报。
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '旧帧', step: 1 }, seq: null }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '新帧', step: 2 }, seq: 5 }),
    ]);
    expect(s.turns[0].user_message_seq).toBeNull();
    expect(firstForkableTurnIndex(s.turns)).toBe(1);
  });

  it('全部轮都无锚点：返回 -1（一个分叉入口都不渲染）', () => {
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: 'a', step: 1 }, seq: null }),
      ev({ type: EventType.USER_MESSAGE, data: { content: 'b', step: 2 }, seq: null }),
    ]);
    expect(firstForkableTurnIndex(s.turns)).toBe(-1);
  });

  it('畸形日志 seq 乱序：取 seq 最小的轮，而非数组第一个', () => {
    // 投影按事件顺序建轮，理论上 seq 递增；乱序日志下必须仍指向最早的用户消息。
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '后到', step: 1 }, seq: 9 }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '先发', step: 2 }, seq: 3 }),
    ]);
    expect(firstForkableTurnIndex(s.turns)).toBe(1);
  });
});

describe('emptyChildTurnIndex — 「child 会话将是空会话」提示只给第 0 轮', () => {
  // 回归锁：修复前直接复用 firstForkableTurnIndex 当 isFirstUserTurn，于是
  // 「注入轮 / 无锚点轮排在最前」时把提示挪给了下一轮——而那一轮之前明明还有
  // 事件（它们会进 child），提示是谎报。这里锁「不是第 0 轮 ⇒ -1（不给提示）」。
  it('两个真实用户轮 → 0（第 0 轮可分叉，提示成立）', () => {
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '一', step: 1 }, seq: 2 }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '二', step: 2 }, seq: 5 }),
    ]);
    expect(emptyChildTurnIndex(s.turns)).toBe(0);
  });

  it('注入轮排在最前 → -1（提示不得挪给第 1 轮）', () => {
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '纠正', step: 1, injected_by: 'failure-guard' }, seq: 2 }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '真人', step: 2 }, seq: 5 }),
    ]);
    expect(emptyChildTurnIndex(s.turns)).toBe(-1);
  });

  it('第 0 轮无锚点（旧版后端）→ -1（不得挪给第 1 轮）', () => {
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '旧帧', step: 1 }, seq: null }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '新帧', step: 2 }, seq: 5 }),
    ]);
    expect(emptyChildTurnIndex(s.turns)).toBe(-1);
  });

  it('空会话 / 全部无锚点 → -1', () => {
    expect(emptyChildTurnIndex([])).toBe(-1);
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: 'a', step: 1 }, seq: null }),
    ]);
    expect(emptyChildTurnIndex(s.turns)).toBe(-1);
  });

  it('乱序 seq 且最小 seq 不在第 0 轮 → -1（保守不给提示）', () => {
    const s = projectHistory('s', [
      ev({ type: EventType.USER_MESSAGE, data: { content: '后到', step: 1 }, seq: 9 }),
      ev({ type: EventType.USER_MESSAGE, data: { content: '先发', step: 2 }, seq: 3 }),
    ]);
    expect(emptyChildTurnIndex(s.turns)).toBe(-1);
  });
});

describe('事件摘要的单行语义（UI-04 信任裂缝）', () => {
  const T = '2026-09-12T00:00:00Z';
  const base = { session_id: 's', time: T };

  it('session/forked → 「已分叉」（此前落「未知事件」泄漏原始 JSON，pre-existing 已定案）', () => {
    const s = applyEvent(initConversation('f'), {
      ...base, type: EventType.SESSION_FORKED, seq: 1, run_id: 'r',
      data: { from_seq: 3, child_session_id: 'child-1' },
    });
    expect(summarizeEvent(s.events[s.events.length - 1])).toBe('已分叉');
  });

  it('tool/approval-requested → 「等待审批 · {tool_name}」', () => {
    let s = initConversation('a');
    s = applyEvent(s, {
      ...base, type: EventType.TOOL_APPROVAL_REQUESTED, seq: 1, run_id: 'r', step_id: 1,
      data: { approval_id: 'ap-1', tool_name: 'write', tool_call_id: 'tc-1', action_type: 'workspace-write', title: 't', description: 'd', arguments_preview: {}, permission: 'p', policy: 'pol', reason: 'r', allowed_decisions: [] },
    });
    expect(summarizeEvent(s.events[s.events.length - 1])).toBe('等待审批 · write');
  });

  it('permission/resolved → 「审批已决（{decision}）」', () => {
    let s = initConversation('p');
    s = applyEvent(s, {
      ...base, type: EventType.TOOL_APPROVAL_REQUESTED, seq: 1, run_id: 'r', step_id: 1,
      data: { approval_id: 'ap-1', tool_name: 'write', tool_call_id: 'tc-1', action_type: 'w', title: 't', description: 'd', arguments_preview: {}, permission: 'p', policy: 'pol', reason: 'r', allowed_decisions: [] },
    });
    s = applyEvent(s, {
      ...base, type: EventType.PERMISSION_RESOLVED, seq: 2, run_id: 'r',
      data: { approval_id: 'ap-1', decision: 'approve_once', reason: '' },
    });
    expect(summarizeEvent(s.events[s.events.length - 1])).toBe('审批已决（approve_once）');
  });

  it('真正未接线的类型：摘要不含 JSON 片段（无 { 无 引号）', () => {
    const s = applyEvent(initConversation('u'), {
      ...base, type: EventType.OPERATION_RECONCILE_REQUIRED, seq: 1, run_id: 'r',
      data: { ledger_id: 'op-1', reason: 'x' },
    });
    const summary = summarizeEvent(s.events[s.events.length - 1]);
    expect(summary).not.toContain('{');
    expect(summary).not.toContain('"');
  });
});

// ── #184 Inspector PERMISSION 段：审批请求 → 队列，决议 → 留痕 + 权限档派生 ──

describe('审批投影 — 权限档（permission_policy）/ 待审批 / 裁决留痕（#184）', () => {
  const T = '2026-01-01T00:00:00Z';
  const base = { session_id: 's', time: T };

  const requested = (approvalId: string, seq: number, policy: string, toolName = 'write') =>
    ev({
      ...base, type: EventType.TOOL_APPROVAL_REQUESTED, seq, run_id: 'r', step_id: 1,
      data: {
        approval_id: approvalId, tool_name: toolName, tool_call_id: `tc-${approvalId}`,
        action_type: 'workspace-write', title: 't', description: 'd', arguments_preview: {},
        permission: 'workspace-write', policy, reason: 'r', allowed_decisions: ['deny', 'approve_once'],
      },
    });

  const resolved = (approvalId: string, seq: number, decision: string, reason = '') =>
    ev({
      ...base, type: EventType.PERMISSION_RESOLVED, seq, run_id: 'r',
      data: { approval_id: approvalId, decision, reason },
    });

  it('无审批事件：权限档 null（渲染层显示 —，不拿 composer 选择冒充会话事实）', () => {
    const s = applyEvent(initConversation('p'), ev({ ...base, type: EventType.RUN_STARTED, seq: 1, run_id: 'r' }));
    expect(s.permission_policy).toBeNull();
    expect(s.pending_approvals).toEqual([]);
    expect(s.approval_decisions).toEqual([]);
  });

  it('审批请求在队：权限档 = 该请求的生效阈值', () => {
    let s = initConversation('p');
    s = applyEvent(s, requested('ap-1', 1, 'read-only'));
    expect(s.permission_policy).toBe('read-only');
    expect(s.pending_approvals).toHaveLength(1);
    expect(s.approval_decisions).toEqual([]);
  });

  it('决议 → 出队 + 留痕（含工具名），权限档仍可得（不因出队而丢）', () => {
    let s = initConversation('p');
    s = applyEvent(s, requested('ap-1', 1, 'read-only'));
    s = applyEvent(s, resolved('ap-1', 2, 'approve_once', '用户批准'));
    expect(s.pending_approvals).toEqual([]);
    expect(s.approval_decisions).toEqual([
      { approval_id: 'ap-1', decision: 'approve_once', reason: '用户批准', tool_name: 'write', time: T },
    ]);
    // 关键：请求已出队，但权限档仍在（折叠在状态上，不是从队列临时读的）
    expect(s.permission_policy).toBe('read-only');
  });

  it('多次审批：权限档取**最近一次请求**（事件序，不是队列/裁决表的拼接顺序）', () => {
    let s = initConversation('p');
    s = applyEvent(s, requested('ap-1', 1, 'read-only'));
    s = applyEvent(s, resolved('ap-1', 2, 'deny'));
    s = applyEvent(s, requested('ap-2', 3, 'workspace-write', 'bash'));
    expect(s.permission_policy).toBe('workspace-write');
    expect(s.pending_approvals.map((a) => a.approval_id)).toEqual(['ap-2']);
    expect(s.approval_decisions.map((d) => d.approval_id)).toEqual(['ap-1']);
  });

  it('决议重放幂等：同一 approval_id 再来一次决议不重复留痕', () => {
    let s = initConversation('p');
    s = applyEvent(s, requested('ap-1', 1, 'read-only'));
    s = applyEvent(s, resolved('ap-1', 2, 'deny'));
    s = applyEvent(s, resolved('ap-1', 3, 'deny'));
    expect(s.approval_decisions).toHaveLength(1);
  });

  it('配不上对的决议（事件窗口从中间开始）：留痕但 tool_name 为空——不猜', () => {
    let s = initConversation('p');
    s = applyEvent(s, resolved('ap-orphan', 1, 'deny', '无对应请求'));
    expect(s.approval_decisions).toEqual([
      { approval_id: 'ap-orphan', decision: 'deny', reason: '无对应请求', tool_name: undefined, time: T },
    ]);
    // 没有请求事件 → 权限档无从得知（不是空串，是 null）
    expect(s.permission_policy).toBeNull();
  });

  it('缺 approval_id 的决议事件被忽略（契约必有该字段，不制造空 id 的假记录）', () => {
    let s = initConversation('p');
    s = applyEvent(s, ev({
      ...base, type: EventType.PERMISSION_RESOLVED, seq: 1, run_id: 'r',
      data: { decision: 'deny', reason: '缺 id' },
    }));
    expect(s.approval_decisions).toEqual([]);
  });
});
