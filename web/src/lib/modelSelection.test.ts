import { describe, expect, it } from 'vitest';
import type { ModelCatalogEntry } from './api';
import { modelChangeTarget } from './modelSelection';

const entry = (name: string, isDefault = false): ModelCatalogEntry => ({
  name,
  provider: 'p',
  model: name,
  default: isDefault,
});

const catalog = [
  entry('deepseek-v4-flash-0731', true),
  entry('glm-5.3-flash'),
  entry('qwen-plus'),
];

describe('modelChangeTarget（FE-R11-02：选「默认链」也要能清掉会话级覆盖）', () => {
  it('选具体模型 → 原样返回该模型名', () => {
    expect(modelChangeTarget('glm-5.3-flash', catalog)).toBe('glm-5.3-flash');
  });

  it('选「默认链」（null）→ 解析成 catalog 的 default 条目名（后端据此清覆盖）', () => {
    // 后端 is_default_selection() 命中该名字 → model/changed{to=None}
    expect(modelChangeTarget(null, catalog)).toBe('deepseek-v4-flash-0731');
  });

  it('catalog 里没有 default 条目 → null（调用方保持既有行为，不伪造目标）', () => {
    expect(modelChangeTarget(null, [entry('glm-5.3-flash')])).toBeNull();
  });

  it('catalog 为空 → null（端点缺席时选择器本就降级隐藏）', () => {
    expect(modelChangeTarget(null, [])).toBeNull();
  });

  it('第一个 default 条目胜出（后端只保证存在，不保证唯一）', () => {
    expect(modelChangeTarget(null, [entry('a', true), entry('b', true)])).toBe('a');
  });
});
