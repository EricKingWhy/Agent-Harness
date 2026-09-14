/** Conversation.tsx 流式渲染策略测试（P0-2a：streaming 段纯文本零解析，
 *  done 段一次性 markdown——HANDOFF_PERF_FRONTEND §6 P0-2 方案 a）。 */
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ChainNodeView, TurnView } from './Conversation';
import type { ChainNode } from '../lib/projection';
import type { ReasoningBlock, ToolCall, Turn } from '../types';
import type { Disclosure } from '../lib/disclosure';

function modelNode(text: string, status: 'streaming' | 'done'): ChainNode {
  return { kind: 'model', segment: { text, status } };
}

describe('ChainNodeView — 流式 markdown 增量化（P0-2a）', () => {
  it('streaming 段渲染纯文本：不跑 markdown 解析（原始标记原样透传）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={modelNode('**加粗** 与 `code`', 'streaming')} density="balanced" />,
    );
    expect(html).toContain('**加粗**'); // 标记原样可见（打字机状态）
    expect(html).not.toContain('<strong>'); // 未解析
    expect(html).not.toContain('md-paragraph');
    expect(html).toContain('stream-caret');
  });

  it('done 段一次性 markdown 解析（model/completed 后）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={modelNode('**加粗**', 'done')} density="balanced" />,
    );
    expect(html).toContain('<strong>');
    expect(html).not.toContain('stream-caret');
  });

  it('streaming 段纯文本路径仍过不可信截断（20k 上限不旁路）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={modelNode('x'.repeat(25_000), 'streaming')} density="balanced" />,
    );
    expect(html.length).toBeLessThan(25_000);
  });
});

describe('ChainNodeView — 语义图标行（PRD §5.2/§10，ADR-0014 D1）', () => {
  it('streaming 段 = thinking 行（🧠 思考 + 流式正文共存）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={modelNode('分析中…', 'streaming')} density="balanced" />,
    );
    expect(html).toContain('model-kind-row-thinking');
    expect(html).toContain('思考');
    expect(html).toContain('stream-caret'); // 正文照常打字机
  });

  it('final-answer（isFinalModel=true）：无图标行，高对比正文', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={modelNode('**最终答案**', 'done')} density="balanced" isFinalModel />,
    );
    expect(html).not.toContain('model-kind-row');
    expect(html).toContain('<strong>');
    expect(html).not.toContain('model-output-intermediate');
  });

  it('中间 done 段（isFinalModel=false）：model 行 + 低对比正文', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={modelNode('阶段小结', 'done')} density="balanced" isFinalModel={false} />,
    );
    expect(html).toContain('model-kind-row'); // 有语义行（无 thinking 态）
    expect(html).not.toContain('model-kind-row-thinking');
    expect(html).toContain('model-output-intermediate');
    expect(html).toContain('阶段小结');
  });

  it('复制按钮按段角色分文案（终段=复制回答 / 中间段=复制输出）', () => {
    const finalHtml = renderToStaticMarkup(
      <ChainNodeView node={modelNode('答', 'done')} density="balanced" isFinalModel />,
    );
    expect(finalHtml).toContain('复制回答');
    const midHtml = renderToStaticMarkup(
      <ChainNodeView node={modelNode('段', 'done')} density="balanced" isFinalModel={false} />,
    );
    expect(midHtml).toContain('复制输出');
  });
});

describe('ChainNodeView — ToolCard L 级接线（ADR-0014 D2）', () => {
  const toolNode: ChainNode = {
    kind: 'tool',
    tool: {
      tool_call_id: 'c1', name: 'bash', args: { command: 'ls' }, status: 'success',
      result: { ok: true, data: { exit_code: 0 } },
    } as ToolCall,
  };

  it('disclosure.levelFor 决定 L 级（override L2 → 渲染完整内容面 + raw）', () => {
    const disclosure: Disclosure = {
      levelFor: (key, d) => (key === 'tool:c1' ? 2 : d === 'raw' ? 2 : 0),
      setLevel: () => {},
    };
    const html = renderToStaticMarkup(
      <ChainNodeView node={toolNode} density="balanced" disclosure={disclosure} />,
    );
    expect(html).toContain('tool-card-body');
  });

  it('无 override 时跟随 density 默认（balanced → 仅 L0 行）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={toolNode} density="balanced" />,
    );
    expect(html).not.toContain('act-detail-inline');
    expect(html).not.toContain('tool-card-body');
  });
});

describe('ChainNodeView — ReasoningBlock（#95，规格 03 §7）', () => {
  const rNode = (over: Partial<ReasoningBlock>): ChainNode => ({
    kind: 'reasoning',
    block: { blockId: 'b1', source: 'model', text: '', status: 'streaming', ...over },
  });

  it('balanced streaming 自动展开（S6）：全文 + aria-expanded + 流式光标', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={rNode({ text: '完整推理文本' })} density="balanced" />,
    );
    expect(html).toContain('正在思考');
    expect(html).toContain('reasoning-expanded');
    expect(html).toContain('完整推理文本');
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('stream-caret');
  });

  it('compact streaming 默认收（PRD §9.1 一行实况）：前读视口在场、aria-hidden', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={rNode({ text: '逐步分析' })} density="compact" />,
    );
    expect(html).toContain('reasoning-readline');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('逐步分析');
    expect(html).not.toContain('reasoning-expanded');
  });

  it('手动 override 收起（S7 user_interacted）：balanced streaming 也保持收起', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView
        node={rNode({ text: 'thinking' })}
        density="balanced"
        reasoningDisclosure={{ isOpen: () => false, toggle: () => {} }}
      />,
    );
    expect(html).toContain('reasoning-readline');
    expect(html).toContain('aria-expanded="false"');
  });

  it('completed：header 切「思考 · 持续了」时长；收起态前读视口定格', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView
        node={rNode({
          status: 'completed',
          text: '已完成的思考',
          started_at: '2026-09-06T00:00:00Z',
          completed_at: '2026-09-06T00:00:36Z',
        })}
        density="balanced"
      />,
    );
    expect(html).toContain('思考');
    expect(html).toContain('持续了');
    expect(html).toContain('36 秒');
    expect(html).not.toContain('正在思考');
  });

  it('interrupted ≥1s：显「中断于 N 秒」（中断语义不塌缩）+ 已聚合文本保留（PRD §16.4 不擦除；UI-04 只修 N===0 的 0 秒）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView
        node={rNode({
          status: 'interrupted',
          text: '部分内容',
          started_at: '2026-09-06T00:00:00Z',
          completed_at: '2026-09-06T00:00:18Z',
        })}
        density="balanced"
      />,
    );
    expect(html).toContain('中断于');
    expect(html).toContain('18 秒');
    expect(html).toContain('部分内容');
  });

  it('agent 进度来源出「进度」徽标（S1 双来源可辨）', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={rNode({ source: 'agent' })} density="balanced" />,
    );
    expect(html).toContain('进度');
  });
});

describe('ChainNodeView — DelegationNode 委派节点（Phase 13，v2 PRD §10.5）', () => {
  const delegationNode: ChainNode = {
    kind: 'delegation',
    delegation: {
      target: 'research_review',
      task: '调研 python.org',
      child_session_id: 'child-abc',
      status: 'running',
    },
  };

  it('注册表分发：编排节点渲染 DSH 四态行 + 子会话身份行 + 复制', () => {
    const html = renderToStaticMarkup(
      <ChainNodeView node={delegationNode} density="balanced" />,
    );
    expect(html).toContain('委派 → research_review');
    expect(html).toContain('child-abc');
    expect(html).toContain('act-status-running');
    expect(html).toContain('deleg-child-row');
  });

  it('onInspectChild / onOpenSession 提供时渲染两个入口；缺省不造假链接', () => {
    const withEntries = renderToStaticMarkup(
      <ChainNodeView
        node={delegationNode}
        density="balanced"
        onInspectChild={() => undefined}
        onOpenSession={() => undefined}
      />,
    );
    expect(withEntries).toContain('Inspect 子会话');
    expect(withEntries).toContain('打开子会话');
    const without = renderToStaticMarkup(
      <ChainNodeView node={delegationNode} density="balanced" />,
    );
    expect(without).not.toContain('Inspect 子会话');
    expect(without).not.toContain('打开子会话');
  });
});

/** TurnView 的最小 Turn 夹具——两个 describe 共用（模块级，避免各自复制漂移）。 */
function turn(over: Partial<Turn> = {}): Turn {
  return {
    step_id: 1,
    user_message: 'hi',
    model: { text: 'ok', status: 'done' },
    segments: [],
    tools: [],
    activities: [{ kind: 'model', index: 0 }],
    status: 'done',
    turn_index: 1,
    user_message_seq: 1,
    ...over,
  };
}

describe('TurnView — T9 #139 轮次标签', () => {
  it('turnIndex 为正整数时渲染「第 N 轮」', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn()} turnIndex={3} model={null} density="balanced" />,
    );
    expect(html).toContain('turn-index-label');
    expect(html).toContain('第 3 轮');
  });

  it('turnIndex 为 null 时不渲染标签（旧版后端缺字段）', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn({ turn_index: null })} turnIndex={null} model={null} density="balanced" />,
    );
    expect(html).not.toContain('turn-index-label');
    expect(html).not.toContain('轮');
  });

  it('turnIndex ≤ 0 时不渲染标签（防御性）', () => {
    for (const bad of [0, -1]) {
      const html = renderToStaticMarkup(
        <TurnView turn={turn({ turn_index: bad })} turnIndex={bad} model={null} density="balanced" />,
      );
      expect(html, `turnIndex=${bad}`).not.toContain('turn-index-label');
    }
  });

  it('每轮标签取自自身 turn（两个 turn 显示不同轮次）', () => {
    const first = renderToStaticMarkup(
      <TurnView turn={turn({ step_id: 1, turn_index: 1 })} turnIndex={1} model={null} density="balanced" />,
    );
    const second = renderToStaticMarkup(
      <TurnView turn={turn({ step_id: 2, turn_index: 2 })} turnIndex={2} model={null} density="balanced" />,
    );
    expect(first).toContain('第 1 轮');
    expect(second).toContain('第 2 轮');
    expect(first).not.toContain('第 2 轮');
  });
});

// ── BUG-001：分叉入口的锚点与可见性 ──
// 交互断言（实际发出的 from_seq、422 的可见性）在 e2e/b-fork.spec.ts（真浏览器 +
// route 拦截）；这里锁 SSR 契约：什么时候该有按钮、文案说什么。

describe('TurnView — 分叉入口（BUG-001）', () => {
  const onFork = () => undefined;

  it('有 onFork 且该轮有 user_message_seq → 渲染分叉按钮', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn({ user_message_seq: 30 })} model={null} density="balanced" onFork={onFork} />,
    );
    expect(html).toContain('fork-btn');
    expect(html).toContain('分叉');
  });

  it('无锚点（user_message_seq 为 null）→ 不渲染按钮（不造假入口）', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn({ user_message_seq: null })} model={null} density="balanced" onFork={onFork} />,
    );
    expect(html).not.toContain('fork-btn');
  });

  it('未注入 onFork（只读场景）→ 不渲染按钮', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn()} model={null} density="balanced" />,
    );
    expect(html).not.toContain('fork-btn');
  });

  it('流式中的轮次不渲染按钮（历史未 settled，后端会 409）', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn({ status: 'streaming' })} model={null} density="balanced" onFork={onFork} />,
    );
    expect(html).not.toContain('fork-btn');
  });

  it('第 1 轮：提示 child 将是空会话（锚点消息不进 seed，之前无历史）', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn()} model={null} density="balanced" onFork={onFork} isFirstUserTurn />,
    );
    expect(html).toContain('fork-btn');
    expect(html).toContain('空会话');
  });

  it('非第 1 轮：沿用常规标题（不出现空会话提示）', () => {
    const html = renderToStaticMarkup(
      <TurnView turn={turn({ user_message_seq: 30 })} model={null} density="balanced" onFork={onFork} />,
    );
    expect(html).toContain('从此处分叉新会话');
    expect(html).not.toContain('空会话');
  });
});
