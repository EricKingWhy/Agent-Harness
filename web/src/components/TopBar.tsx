/** TopBar — App Bar of the single-frame shell (Phase 2, Brief §5).
 *
 * Left: product identity. Center: current session title + Run Pulse
 * (signature #1 — icon + color + text, never color-only). Right:
 * trace density selector (four tiers, localStorage-persisted — frozen
 * decision), inspector collapse toggle + theme toggle.
 */

import { Activity, Brain, KeyRound, Moon, PanelRight, Sun } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { Theme } from '../lib/theme';
import { DENSITIES, type TraceDensity } from '../lib/density';
import { deriveRunPulse, shouldShowWaitHint, waitingHintText } from '../lib/runState';
import { decodeJwtClaims, getToken, onTokenChange, setToken } from '../lib/auth';
import type { ConversationState } from '../types';

interface Props {
  conversation: ConversationState | null;
  streaming: boolean;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  /** Trace Density 四档（冻结决策）——状态归 App，这里只渲染切换控件。 */
  density: TraceDensity;
  onDensityChange: (d: TraceDensity) => void;
  /** 主题状态归 App（Command Palette Toggle Theme 与本按钮共享同一状态源）。 */
  theme: Theme;
  onToggleTheme: () => void;
  /** 401 已发生（App 广播）——钥匙图标加提示点，引导配置 token。 */
  authRequired: boolean;
  /** 打开记忆管理浮层（MEM-5 / #160）。低频管理动作，放在 App Bar 右簇。 */
  onOpenMemories: () => void;
}

export function TopBar({ conversation, streaming, inspectorOpen, onToggleInspector, density, onDensityChange, theme, onToggleTheme, authRequired, onOpenMemories }: Props) {

  // 身份 chip：订阅 token 变更（设置面板保存/清除即时反映），解码展示 claims。
  const [token, setTokenLive] = useState(getToken());
  useEffect(() => onTokenChange(() => setTokenLive(getToken())), []);
  const identity = useMemo(() => (token ? decodeJwtClaims(token) : null), [token]);

  // Auth 设置面板：token 是开发者设置项（localStorage ahi.apiToken）。
  // 输入框只在面板打开时同步真值——打开 = 读取当前存储，避免陈旧副本。
  const [authPanelOpen, setAuthPanelOpen] = useState(false);
  const [tokenDraft, setTokenDraft] = useState('');

  // 流式计时（借鉴 ZCode 的"工作中 N 秒"）：进行中状态用真实秒数表达，而非空泛 spinner。
  const [elapsedSec, setElapsedSec] = useState(0);
  useEffect(() => {
    if (!streaming) {
      setElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    const timer = setInterval(
      () => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [streaming]);

  const openAuthPanel = () => {
    setTokenDraft(getToken());
    setAuthPanelOpen((v) => !v);
  };

  const saveToken = () => {
    setToken(tokenDraft);
    setAuthPanelOpen(false);
  };

  const pulse = deriveRunPulse(conversation, streaming);
  const PulseIcon = pulse.Icon;
  const active = pulse.state === 'thinking' || pulse.state === 'tool';

  // 停顿提示（FE-01/#148）：锚**空闲**（距上次新事件），不是流龄——健康的长任务里
  // 流龄一路涨，用它当阈值会把正常慢任务报成停顿。events.length 是投影真值的进度
  // 信号；只在「流已挂上且模型正在思考」时计时：说明文字断言的是「等待模型」，所以在
  // 工具执行（pulse 'tool'，含审批等待）与 run 已收口时都不能出现——那样顶栏会一边写
  // 「执行工具」一边写「仍在等待模型」，自相矛盾。
  //
  // 进度信号走 ref 而不是 effect 依赖：依赖它会让**每个 delta** 都 teardown/重建一次
  // interval（快速流里每秒成百次）。这里 interval 只在 waiting 翻转时重建，每个事件只
  // 写一次 ref；同时把已显示的 idleSec 归零，免得新 chunk 到了还挂着上一轮的秒数。
  const progressKey = conversation?.events.length ?? 0;
  const progressAtRef = useRef(0);
  const [idleSec, setIdleSec] = useState(0);
  useEffect(() => {
    progressAtRef.current = Date.now();
    setIdleSec(0);
  }, [progressKey]);

  const waiting = shouldShowWaitHint(pulse.state, streaming);
  useEffect(() => {
    if (!waiting) {
      setIdleSec(0);
      return;
    }
    const timer = setInterval(
      () => setIdleSec(Math.floor((Date.now() - progressAtRef.current) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [waiting]);

  return (
    <header className="appbar">
      <div className="appbar-left">
        <Activity size={16} className="appbar-logo" />
        <span className="appbar-title">Agent Harness Inspector</span>
      </div>

      <div className="appbar-center">
        {conversation && (
          <span className="appbar-session mono">
            {conversation.session_id.slice(0, 8)}
          </span>
        )}
        <span className={`run-pulse ${pulse.className}`}>
          <PulseIcon size={14} aria-hidden="true" />
          {pulse.label}
          {active && elapsedSec > 0 && <span className="num"> · {elapsedSec}s</span>}
          {/* Claude Code "(13s · 28 tokens)" 语言：run 用量计数。usage_total 是
              投影从 model/completed 聚合的已有真相——工具型 run 流式期间逐步累加，
              纯文本 run 完成时一次到位；无数据不显示（零伪造）。 */}
          {conversation?.usage_total && (
            <span className="num"> · {conversation.usage_total.total_tokens.toLocaleString()} tok</span>
          )}
        </span>
        {waiting && <WaitingHint idleSec={idleSec} />}
      </div>

      <div className="appbar-right">
        <div className="density-picker" role="radiogroup" aria-label="Trace 密度">
          {DENSITIES.map((d) => (
            <button
              key={d}
              role="radio"
              aria-checked={density === d}
              className={`density-btn ${density === d ? 'sel' : ''}`}
              onClick={() => onDensityChange(d)}
              title={DENSITY_LABEL[d]}
            >
              {DENSITY_LABEL[d]}
            </button>
          ))}
        </div>
        {/* 身份 chip（da394a9 认证 UX）：token 已配置且可解码时展示 token 声称的身份。
            仅解码不验签——真伪由 401 拦截兜底；无 token / 畸形 token 不渲染。 */}
        {identity && (
          <span
            className="auth-chip"
            title={`tenant: ${identity.tenant_id ?? '—'} · user: ${identity.user_id ?? '—'}${
              identity.exp ? ` · 过期于 ${new Date(identity.exp * 1000).toLocaleString()}` : ''
            }`}
          >
            {identity.user_id ?? '已配置'}
          </span>
        )}
        <button
          className={`icon-btn icon-btn-auth${authRequired ? ' attention' : ''}`}
          onClick={openAuthPanel}
          aria-label="API 身份令牌设置"
          aria-expanded={authPanelOpen}
          title="API 身份令牌（Bearer）——仅配置了 JWT_SECRET 的后端需要"
        >
          <KeyRound size={16} />
        </button>
        <button
          className="icon-btn"
          onClick={onOpenMemories}
          aria-label="记忆管理"
          title="记忆管理——查看并删除系统记住的长期事实"
        >
          <Brain size={16} />
        </button>
        <button
          className="icon-btn"
          onClick={onToggleInspector}
          aria-label={inspectorOpen ? '收起 Inspector' : '展开 Inspector'}
          aria-pressed={inspectorOpen}
          title={inspectorOpen ? '收起 Inspector' : '展开 Inspector'}
        >
          <PanelRight size={16} className={inspectorOpen ? 'appbar-toggle-active' : undefined} />
        </button>
        <button className="icon-btn" onClick={onToggleTheme} aria-label="切换主题">
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>

      {authPanelOpen && (
        <div className="auth-panel" role="dialog" aria-label="API 身份令牌设置" onKeyDown={(e) => e.key === 'Escape' && setAuthPanelOpen(false)}>
          <div className="auth-panel-title">API 身份令牌（Bearer）</div>
          <input
            className="auth-panel-input"
            type="password"
            value={tokenDraft}
            placeholder="粘贴 HS256 token（eyJ…）"
            onChange={(e) => setTokenDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && saveToken()}
            autoFocus
          />
          <div className="auth-panel-hint">
            仅配置了 <code>JWT_SECRET</code> 的部署需要；本地开发留空即可。
            Token 保存在浏览器 localStorage（<code>ahi.apiToken</code>），claims 需含
            tenant_id / user_id / exp（未过期）。
          </div>
          <div className="auth-panel-actions">
            <button className="auth-panel-save" onClick={saveToken}>保存</button>
            <button
              className="auth-panel-clear"
              onClick={() => {
                setToken('');
                setAuthPanelOpen(false);
              }}
            >
              清除
            </button>
          </div>
        </div>
      )}
    </header>
  );
}

/** 生成态里「等太久了」的诚实说明（FE-01/#148）。
 *
 *  纯展示：只吃一个秒数入参（上游读的是投影真值 `events.length`），不发
 *  SessionEvent、不落库——刷新即消失，因此不构成第二套会话真相（不变量 #22）。
 *  判定用 `shouldShowWaitHint`、文案用 `waitingHintText`（两者的真相与依据都在
 *  `runState.ts`）；阈值以下的正常生成一个节点都不多渲染。 */
export function WaitingHint({ idleSec }: { idleSec: number }) {
  const text = waitingHintText(idleSec);
  if (text === null) return null;
  return <span className="wait-hint">{text}</span>;
}

const DENSITY_LABEL: Record<TraceDensity, string> = {
  compact: '紧凑',
  balanced: '均衡',
  detailed: '详细',
  raw: 'Raw',
};
