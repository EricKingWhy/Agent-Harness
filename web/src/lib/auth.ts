/** lib/auth — Bearer token 接缝（后端 auth_seam fail-closed 语义的前端对侧）。
 *
 * 后端契约（feat/backend df4f7d8 HANDOFF_FRONTEND_SYNC.md §1.2）：
 *   - 配置了 JWT_SECRET 的部署：所有 /api/* 必须带 `Authorization: Bearer <HS256>`，
 *     匿名 → 401 {"detail": "Missing identity token"}；
 *   - 未配置（本地开发）：无 token 照常可用。
 *
 * 前端策略：token 是开发者设置项（localStorage `ahi.apiToken`），api.ts 统一
 * 注入；401 通过 onUnauthorized 广播给 UI（App 横幅引导 + TopBar 钥匙图标提示）。
 * 不解析 token claims——前端不复制后端的验签职责，零伪造。
 */

const TOKEN_KEY = 'ahi.apiToken';

type TokenListener = () => void;
type UnauthorizedListener = (detail: string) => void;

const tokenListeners = new Set<TokenListener>();
const unauthorizedListeners = new Set<UnauthorizedListener>();

/** 当前 token（未配置返回空串——api.ts 空串不注入头，本地信任模式零影响）。 */
export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

/** 保存/清除 token。空串 = 清除。通知订阅者（App 收到后重试会话列表）。 */
export function setToken(token: string): void {
  const trimmed = token.trim();
  try {
    if (trimmed) localStorage.setItem(TOKEN_KEY, trimmed);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // localStorage 不可用（隐私模式等）：token 仅本次会话内存生效——
    // 静默降级，订阅者仍会收到变更通知。
  }
  tokenListeners.forEach((cb) => cb());
}

export function onTokenChange(cb: TokenListener): () => void {
  tokenListeners.add(cb);
  return () => tokenListeners.delete(cb);
}

/** api.ts 在收到 401 时广播。App 订阅后展示「配置 token」引导横幅。 */
export function onUnauthorized(cb: UnauthorizedListener): () => void {
  unauthorizedListeners.add(cb);
  return () => unauthorizedListeners.delete(cb);
}

export function emitUnauthorized(detail: string): void {
  unauthorizedListeners.forEach((cb) => cb(detail));
}

// ── 身份 chip（da394a9 批认证 UX）：客户端解码展示，不验签 ──

export interface IdentityClaims {
  tenant_id?: string;
  user_id?: string;
  /** 秒级 Unix 过期时间（claims.exp）。 */
  exp?: number;
}

/** 解码 JWT payload 的展示用 claims。仅解码不验签——验签是后端职责，
 *  前端显示的 tenant/user 只是"token 声称的身份"（UI 据此配置成功与否
 *  由 401 拦截兜底裁决）。畸形 token 返回 null，不抛错。 */
export function decodeJwtClaims(token: string): IdentityClaims | null {
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    // base64url → base64（atob 不认 - 和 _）
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const pad = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const json = decodeURIComponent(
      atob(pad)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(''),
    );
    const claims = JSON.parse(json) as Record<string, unknown>;
    return {
      tenant_id: typeof claims.tenant_id === 'string' ? claims.tenant_id : undefined,
      user_id: typeof claims.user_id === 'string' ? claims.user_id : undefined,
      exp: typeof claims.exp === 'number' ? claims.exp : undefined,
    };
  } catch {
    return null;
  }
}
