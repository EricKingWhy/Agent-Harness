/** amend.ts 契约测试——Composer 档位 → 提交字段的单一映射点。
 *
 *  锁定两条边界：
 *  1. 字段集：续聊 amend 面不含 permission_mode（不在 /messages 契约内）；
 *     创建路径包含它。
 *  2. 归一化归属：本模块**不做**空值丢弃——`[]` 原样透传，丢弃由 api 层
 *     单一执行（见 amend.ts 顶部契约）。这条边界一旦模糊，就会回到
 *     「两层各判一次空、谁拥有契约说不清」的旧状态。 */

import { describe, expect, it } from 'vitest';
import { toAmendFields, toCreateControls, type ComposerControls } from './amend';

const EMPTY: ComposerControls = {
  model: null,
  permissionMode: null,
  agentProfile: null,
  reasoningEffort: null,
  contextProviders: [],
};

const FULL: ComposerControls = {
  model: 'glm-4.5',
  permissionMode: 'auto',
  agentProfile: 'coding',
  reasoningEffort: 'deep',
  contextProviders: ['memory', 'skills'],
};

describe('toAmendFields — 续聊 amend 面（四项，无 permission_mode）', () => {
  it('全有值 → camelCase 映射为契约字段名，不含 permission_mode', () => {
    const fields = toAmendFields(FULL);
    expect(fields).toEqual({
      model: 'glm-4.5',
      agent_profile: 'coding',
      reasoning_effort: 'deep',
      context_providers: ['memory', 'skills'],
    });
    expect(fields).not.toHaveProperty('permission_mode');
  });

  it('null 档位 → undefined（映射层不判空，交给 api 层丢弃）', () => {
    const fields = toAmendFields(EMPTY);
    expect(fields.model).toBeUndefined();
    expect(fields.agent_profile).toBeUndefined();
    expect(fields.reasoning_effort).toBeUndefined();
  });

  it('context_providers 空数组原样透传（归一化归属 api 层，本模块不丢）', () => {
    expect(toAmendFields(EMPTY).context_providers).toEqual([]);
  });
});

describe('toCreateControls — 创建路径控制面（amend 四项 + permission_mode）', () => {
  it('全有值 → 含 permission_mode', () => {
    expect(toCreateControls(FULL)).toEqual({
      model: 'glm-4.5',
      permission_mode: 'auto',
      agent_profile: 'coding',
      reasoning_effort: 'deep',
      context_providers: ['memory', 'skills'],
    });
  });

  it('空档位 → 各字段 undefined / 空数组（api 层丢弃后即「不传键」）', () => {
    const controls = toCreateControls(EMPTY);
    expect(controls.permission_mode).toBeUndefined();
    expect(controls.context_providers).toEqual([]);
  });
});
