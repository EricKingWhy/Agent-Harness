/** 项目分组 / 重排锚点的纯函数测试（WS-5 / #155）。
 *
 *  这一层是 UI 的"排序真相"——e2e 只覆盖主路径，脏数据与边界（重复 id、
 *  跨项目重复、锚点不在账本、等价落点）都在这里钉死。 */

import { describe, expect, it } from 'vitest';
import { buildRailModel, dropAnchor, moveAnchor } from './projects';
import type { Project, SessionSummary } from '../types';

function session(
  id: string,
  workspace: SessionSummary['workspace'] = null,
  archived = false,
): SessionSummary {
  return {
    session_id: id,
    event_count: 1,
    first_event_time: null,
    last_event_time: null,
    first_user_message: null,
    trace_id: null,
    trace_url: null,
    workspace,
    archived,
  };
}

function project(id: string, sessionIds: string[], over: Partial<Project> = {}): Project {
  return {
    id,
    path: `D:/repos/${id}`,
    title: `项目 ${id}`,
    status: 'ok',
    session_ids: sessionIds,
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
    ...over,
  };
}

describe('buildRailModel', () => {
  it('项目顺序 = 注册表顺序，项目内顺序 = 账本手工序（不按活动时间重排）', () => {
    // 活动时间序刻意与账本序相反：s2 最新，账本却把它排在最后。
    const sessions = [
      session('s2', { id: 'p1', title: '项目 p1' }),
      session('s1', { id: 'p1', title: '项目 p1' }),
      session('s3', { id: 'p2', title: '项目 p2' }),
    ];
    const model = buildRailModel(sessions, [project('p1', ['s1', 's2']), project('p2', ['s3'])]);

    expect(model.groups.map((g) => g.project.id)).toEqual(['p1', 'p2']);
    expect(model.groups[0].sessions.map((s) => s.session_id)).toEqual(['s1', 's2']);
    expect(model.groups[1].sessions.map((s) => s.session_id)).toEqual(['s3']);
    expect(model.ungrouped).toEqual([]);
  });

  it('未分组的会话一行不少，且保持后端给的活动时间序', () => {
    const sessions = [
      session('free-1'),
      session('s1', { id: 'p1', title: '项目 p1' }),
      session('free-2'),
    ];
    const model = buildRailModel(sessions, [project('p1', ['s1'])]);

    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['free-1', 'free-2']);
  });

  it('空账本项目照样渲染（刚注册还没会话）', () => {
    const model = buildRailModel([], [project('p1', [])]);
    expect(model.groups).toHaveLength(1);
    expect(model.groups[0].sessions).toEqual([]);
    expect(model.groups[0].missing).toBe(0);
  });

  it('没有项目时全部落到未分组（后端端点失败/未装配的降级路径）', () => {
    const sessions = [session('a'), session('b', { id: 'ghost', title: '已删除的项目' })];
    const model = buildRailModel(sessions, []);
    expect(model.groups).toEqual([]);
    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['a', 'b']);
  });

  it('账本里存在但列表里没有的 id 计为 missing，不伪造空行', () => {
    const model = buildRailModel([session('s1')], [project('p1', ['s1', 'gone'])]);
    expect(model.groups[0].sessions.map((s) => s.session_id)).toEqual(['s1']);
    expect(model.groups[0].missing).toBe(1);
  });

  it('同一会话被两个账本点到：只渲染在第一个项目，第二处计 missing（不重复行）', () => {
    const s = session('s1', { id: 'p1', title: '项目 p1' });
    const model = buildRailModel([s], [project('p1', ['s1']), project('p2', ['s1'])]);

    expect(model.groups[0].sessions.map((x) => x.session_id)).toEqual(['s1']);
    expect(model.groups[1].sessions).toEqual([]);
    expect(model.groups[1].missing).toBe(1);
    expect(model.ungrouped).toEqual([]);
  });

  it('账本内重复 id 只渲染一次', () => {
    const model = buildRailModel([session('s1')], [project('p1', ['s1', 's1'])]);
    expect(model.groups[0].sessions).toHaveLength(1);
  });

  it('workspace 引用已失效项目（孤儿行）仍落未分组——绝不丢行', () => {
    const sessions = [session('gone', { id: 'deleted-project', title: '刚被软删除的项目' })];
    const model = buildRailModel(sessions, [project('other', [])]);
    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['gone']);
  });

  // ── SessionSummary.workspace 的**唯一**运行时用途：解释孤儿行（AC6）──

  it('项目不在列表里（列表为空/请求失败）→ 行带 staleProject 注解', () => {
    const sessions = [
      session('s1', { id: 'p1', title: '项目 p1' }),
      session('free-1'),
    ];
    const model = buildRailModel(sessions, []);

    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['s1', 'free-1']);
    expect(model.ungrouped[0].staleProject).toEqual({ id: 'p1', title: '项目 p1' });
    // workspace = null 的行**不带**注解：未分组就是未分组，不该被标成"孤儿"
    expect(model.ungrouped[1].staleProject).toBeUndefined();
  });

  it('项目在列表里但账本没点到（成员资格被过滤）→ 不注解：列表已经回答了归属', () => {
    const sessions = [session('s1', { id: 'p1', title: '项目 p1' })];
    const model = buildRailModel(sessions, [project('p1', [])]);

    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['s1']);
    expect(model.ungrouped[0].staleProject).toBeUndefined();
  });

  it('注解不改变归属判定：workspace 指向的项目存在时，行仍由账本决定去处', () => {
    // s1 的 workspace 说它在 p1，但 p1 的账本没点它 → 落未分组，且**不**因为
    // workspace 而"自动归位"（那是第二套真相）。staleProject 只在项目不可见时出现。
    const sessions = [session('s1', { id: 'p1', title: '项目 p1' })];
    const model = buildRailModel(sessions, [project('p1', ['s2'])]);
    expect(model.groups[0].sessions).toEqual([]);
    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['s1']);
  });
});

describe('buildRailModel —— 归档可见性（#171）', () => {
  /* 这一组的关键不是"藏起来了"（那太容易实现），而是**藏起来的那些行不许被算成
     `missing`**：`missing` 的文案是「n 条会话日志缺失」，对一条已归档会话说这句话
     是假话——日志好端端在磁盘上，只是被开关收起来了。 */

  it('默认不渲染已归档行（项目内与未分组都算）', () => {
    const sessions = [
      session('s1', { id: 'p1', title: '项目 p1' }, true),
      session('s2', { id: 'p1', title: '项目 p1' }),
      session('free-1', null, true),
      session('free-2'),
    ];
    const model = buildRailModel(sessions, [project('p1', ['s1', 's2'])]);

    expect(model.groups[0].sessions.map((s) => s.session_id)).toEqual(['s2']);
    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['free-2']);
  });

  it('已归档行**不计入** missing——日志没丢，只是被开关收起来了', () => {
    const sessions = [
      session('s1', { id: 'p1', title: '项目 p1' }, true),
      session('s2', { id: 'p1', title: '项目 p1' }),
    ];
    const model = buildRailModel(sessions, [project('p1', ['s1', 's2'])]);

    expect(model.groups[0].missing).toBe(0);
    // 真·日志缺失仍如实计数（否则上面那条断言可能只是把计数关了）
    const withGone = buildRailModel(sessions, [project('p1', ['s1', 's2', 'gone'])]);
    expect(withGone.groups[0].missing).toBe(1);
  });

  it('includeArchived=true 时照常渲染，且行上带 archived 真值（徽标的数据源）', () => {
    const sessions = [
      session('s1', { id: 'p1', title: '项目 p1' }, true),
      session('s2', { id: 'p1', title: '项目 p1' }),
      session('free-1', null, true),
    ];
    const model = buildRailModel(sessions, [project('p1', ['s1', 's2'])], {
      includeArchived: true,
    });

    expect(model.groups[0].sessions.map((s) => s.session_id)).toEqual(['s1', 's2']);
    expect(model.groups[0].sessions[0].archived).toBe(true);
    expect(model.ungrouped.map((s) => s.session_id)).toEqual(['free-1']);
  });

  it('被账本认领但收起不渲染的行，不会再从「未分组」冒出来', () => {
    const sessions = [session('s1', { id: 'p1', title: '项目 p1' }, true)];
    const model = buildRailModel(sessions, [project('p1', ['s1'])]);

    expect(model.groups[0].sessions).toEqual([]);
    expect(model.ungrouped).toEqual([]);
  });
});

describe('moveAnchor', () => {
  const ids = ['a', 'b', 'c'];

  it('首条上移 / 末条下移 = 无需请求（UI 据此禁用按钮）', () => {
    expect(moveAnchor(ids, 'a', 'up')).toBeNull();
    expect(moveAnchor(ids, 'c', 'down')).toBeNull();
  });

  it('上移 = insertBefore(上一个兄弟)', () => {
    expect(moveAnchor(ids, 'b', 'up')).toEqual({ before: 'a' });
    expect(moveAnchor(ids, 'c', 'up')).toEqual({ before: 'b' });
  });

  it('下移一格的落点：跳过被换位的那一条，插到它的下一个兄弟前；没有则追加队尾', () => {
    // [a, b, c] 里 b 下移一格的正确锚点是「队尾」：insertBefore(c) 是**空操作**
    // （b 本来就在 c 前面），必须 insertBefore(null) 才能得到 [a, c, b]。
    expect(moveAnchor(ids, 'b', 'down')).toEqual({ before: null });
    // [a, b, c, d] 里 b 下移 → [a, c, b, d]：insertBefore(d)
    expect(moveAnchor(['a', 'b', 'c', 'd'], 'b', 'down')).toEqual({ before: 'd' });
    // [a, b, c, d] 里 c 下移 → [a, b, d, c]：队尾
    expect(moveAnchor(['a', 'b', 'c', 'd'], 'c', 'down')).toEqual({ before: null });
    expect(moveAnchor(['a', 'b'], 'a', 'down')).toEqual({ before: null });
  });

  it('不在账本里的会话 → 不猜（返回无需请求）', () => {
    expect(moveAnchor(ids, 'zzz', 'up')).toBeNull();
  });
});

describe('dropAnchor', () => {
  const ids = ['a', 'b', 'c'];

  it('放到自己身上 = 无需请求', () => {
    expect(dropAnchor(ids, 'b', 'b')).toBeNull();
  });

  it('放到下一个兄弟前面 = 现状等价，无需请求（避免白写一次账本）', () => {
    expect(dropAnchor(ids, 'b', 'c')).toBeNull();
  });

  it('往下拖到更远处：插到目标前面', () => {
    expect(dropAnchor(ids, 'a', 'c')).toEqual({ before: 'c' });
  });

  it('往上拖：插到目标前面', () => {
    expect(dropAnchor(ids, 'c', 'a')).toEqual({ before: 'a' });
  });

  it('放到队尾：已在队尾则无需请求', () => {
    expect(dropAnchor(ids, 'a', null)).toEqual({ before: null });
    expect(dropAnchor(ids, 'c', null)).toBeNull();
  });

  it('锚点不在本项目账本里 → 不猜、不发（后端会 409）', () => {
    expect(dropAnchor(ids, 'a', 'ghost')).toBeNull();
  });
});
