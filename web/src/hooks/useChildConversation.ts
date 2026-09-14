/** useChildConversation — Phase 13 委派钻取的 child 会话加载（v2 PRD §10.5）。
 *
 * `GET /api/sessions/{child_session_id}/events`（Phase 9 既有 API）→
 * projectHistory 同一投影管线（不变量 #22：不建第二套投影）。id 切换即
 * 重置重拉；竞态由 alive 守卫——旧请求不得覆盖新目标的加载结果。
 */

import { useEffect, useState } from 'react';
import type { ConversationState } from '../types';
import { getSessionEvents } from '../lib/api';
import { projectHistory } from '../lib/projection';

export interface ChildConversationState {
  conversation: ConversationState | null;
  error: string | null;
}

export function useChildConversation(childSessionId: string | null): ChildConversationState {
  const [conversation, setConversation] = useState<ConversationState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!childSessionId) {
      setConversation(null);
      setError(null);
      return;
    }
    let alive = true;
    setConversation(null);
    setError(null);
    getSessionEvents(childSessionId)
      .then((events) => {
        if (alive) setConversation(projectHistory(childSessionId, events));
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [childSessionId]);

  return { conversation, error };
}
