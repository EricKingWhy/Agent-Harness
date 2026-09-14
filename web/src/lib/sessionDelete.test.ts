/** sessionDelete 回执文案（#172 / ADR-0029）——纯函数，与 recoverDoneMessage 同一车道。
 *
 * 这些断言锁的是**给用户看的那句话**：
 *  - `events` 必须出现（"删掉了多少"是本票 AC 要写进回执的两项之一）；
 *  - `detached_from_projects` 的两个取值必须说成两件不同的事——0 是"它本来就不在
 *    任何项目里"，不是"项目没删掉"，也不能说成"解除了 0 个项目"（那是把后端的一个
 *    正常计数值翻译成一句像故障的话）。 */

import { describe, expect, it } from 'vitest';
import { sessionDeletedMessage } from './sessionDelete';

describe('sessionDeletedMessage — 硬删回执（#172）', () => {
  it('在项目里（1）：说清事件数 + 从 1 个项目解除', () => {
    expect(sessionDeletedMessage({ events: 42, detached_from_projects: 1 })).toBe(
      '已永久删除 42 条事件记录（不可恢复），并从 1 个项目里解除。',
    );
  });

  it('不在任何项目里（0）：说"不在任何项目"，不说"解除了 0 个项目"', () => {
    const message = sessionDeletedMessage({ events: 7, detached_from_projects: 0 });
    expect(message).toBe('已永久删除 7 条事件记录（不可恢复）；它不在任何项目里。');
    // 计数 0 不许被翻译成"解除 0 个项目"式的故障腔——0 在这里是正常状态
    // （会话本来就没归入任何项目），不是"一个都没解除成功"。
    expect(message).not.toContain('从 0 个');
  });

  it('多项目（>1）按实报数：计数原样出现在句中，不被截断成单数说法', () => {
    expect(sessionDeletedMessage({ events: 3, detached_from_projects: 2 })).toBe(
      '已永久删除 3 条事件记录（不可恢复），并从 2 个项目里解除。',
    );
  });

  it('回执没给事件数（events=0）→ 不报数，绝不说"已删除 0 条事件记录"', () => {
    // 0 在这个字段上不可能是一个真实的计数（0 条事件的会话在后端就是 404），
    // 所以它只能表示"回执没带这个数"。缺数时少说一句是诚实，说成"0 条"则是
    // 一句可能为假的断言——尤其它还和"不可恢复"写在同一句里。
    expect(sessionDeletedMessage({ events: 0, detached_from_projects: 0 })).toBe(
      '已永久删除（不可恢复）；它不在任何项目里。',
    );
    expect(sessionDeletedMessage({ events: 0, detached_from_projects: 2 })).toBe(
      '已永久删除（不可恢复），并从 2 个项目里解除。',
    );
  });
});
