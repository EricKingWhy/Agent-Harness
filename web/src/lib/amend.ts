/** Composer 档位 → 提交契约字段的**单一映射点**。
 *
 * 背景：create（POST /api/sessions）与续聊（POST /api/sessions/{id}/messages）
 * 两条路径消费同一组 Composer 档位，但字段集不同——续聊的 amend 面不含
 * `permission_mode`（不在该端点的请求契约内）。此前 App.tsx 两处各写一遍
 * 「有值才带」展开，新增 amend 字段需要同时改两处（漂移风险）。
 *
 * 归一化归属（本模块的契约）：**丢弃空值是 api 层的事**。这里只做
 * camelCase → 契约字段名 的映射，不判断空值——`api.startSession` /
 * `api.sendMessage` 是「不传键 = 后端默认」这条语义的唯一执行点。
 * 这样「谁拥有契约」有唯一答案：api 层。 */

import type { SendMessagePayload, StartSessionPayload } from './api';

/** App 侧 Composer 档位（camelCase，与 React state 同名）。 */
export interface ComposerControls {
  model: string | null;
  permissionMode: string | null;
  agentProfile: string | null;
  reasoningEffort: string | null;
  contextProviders: string[];
}

/** 续聊 amend 面：四项，不含 `permission_mode`（不在 /messages 契约内）。
 *  字段集直接取自 `SendMessagePayload` 的 Omit——请求契约增删字段时
 *  这个返回类型会跟着变，不会静默漂移。 */
export function toAmendFields(
  c: ComposerControls,
): Omit<SendMessagePayload, 'content' | 'mode' | 'max_steps'> {
  return {
    model: c.model ?? undefined,
    agent_profile: c.agentProfile ?? undefined,
    reasoning_effort: c.reasoningEffort ?? undefined,
    context_providers: c.contextProviders,
  };
}

/** 创建会话控制面：amend 四项 + `permission_mode`（该端点独有）。 */
export function toCreateControls(
  c: ComposerControls,
): Pick<
  StartSessionPayload,
  'model' | 'permission_mode' | 'agent_profile' | 'reasoning_effort' | 'context_providers'
> {
  return {
    ...toAmendFields(c),
    permission_mode: c.permissionMode ?? undefined,
  };
}
