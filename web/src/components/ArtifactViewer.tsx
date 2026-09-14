/** Artifact 内容查看器（#186 AC1/AC2/AC7）。
 *
 *  **一个渲染器，两个入口**（票面明令"与清单同一渲染器"）：
 *  - Artifacts 清单里点一行 → 就地展开内容；
 *  - 被截断/归档的那一处（`DiffBlock` 的归档占位）→ 就地展开同一份内容。
 *
 *  三条纪律：
 *  - **内容不是会话真相**（AC7 / 不变量 #22）：它按需从 `GET .../artifacts/{id}` 取，
 *    取到就渲染，**不写回** `ConversationState`——会话状态的唯一来源永远是事件流。
 *    这里只有组件内的"这次请求的三种状态"。
 *  - **三态如实**（AC1）：加载中 / 拿不到（分因）/ 拿到了。拿不到时显示**后端 detail
 *    原文**，不替它翻译，也不把"部署没配存储"糊成"产物不存在"。
 *  - **不完整要说**：`truncated` 是行数截断与字符截断的并集；单行超长另有行内标记。
 *    把半截内容当全文显示，比不显示更糟。
 *
 *  为什么拆成 `ArtifactContentView`（纯渲染）+ `ArtifactViewer`（取数）：
 *  本仓组件测试是 **SSR**（无 jsdom ⇒ 异步取数在测试里不会 resolve）。把"状态 → 视图"
 *  做成纯函数就能逐态断言，而取数那一层由 e2e 覆盖。
 */
import { AlertTriangle, ChevronDown, ChevronRight, Loader2, Package } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArtifactContentError, getArtifactContent } from '../lib/api';
import type { ArtifactSlice } from '../types';

/** 一次取数的三种状态（判别联合，避免"加载中也可以有错误"这种不存在的组合）。 */
export type ArtifactContentState =
  | { status: 'loading' }
  | { status: 'error'; kind: 'gone' | 'no-storage' | 'error'; detail: string }
  | { status: 'ready'; slice: ArtifactSlice };

/** 拿不到内容时该怎么跟用户说——**因**分开，不合并成一句万能的"加载失败"。 */
function failureText(state: Extract<ArtifactContentState, { status: 'error' }>): {
  title: string;
  hint: string;
} {
  switch (state.kind) {
    case 'gone':
      return {
        title: '这个 artifact 不在本会话里',
        hint: '它可能不存在，或属于另一个会话（artifact_id 是内容哈希，跨会话可能重名）。',
      };
    case 'no-storage':
      return {
        title: '本部署没有可读取的 artifact 存储',
        hint: '这是部署配置问题，不是这个产物丢了。',
      };
    default:
      return { title: '读取 artifact 内容失败', hint: '' };
  }
}

/** 纯渲染：`ArtifactContentState` → 界面。三态都有测试（SSR 可直接断言）。 */
export function ArtifactContentView({
  state,
  artifactId,
}: {
  state: ArtifactContentState;
  artifactId: string;
}) {
  if (state.status === 'loading') {
    return (
      <div className="artifact-content artifact-content-loading" aria-busy="true">
        <Loader2 size={14} className="artifact-spin" aria-hidden="true" />
        <span>正在读取内容…</span>
      </div>
    );
  }
  if (state.status === 'error') {
    const { title, hint } = failureText(state);
    return (
      <div className="artifact-content artifact-content-error" role="alert">
        <div className="artifact-content-error-title">
          <AlertTriangle size={14} aria-hidden="true" />
          {title}
        </div>
        {hint && <div className="artifact-content-error-hint">{hint}</div>}
        {/* 后端 detail 原文（读不到时为空串，不补一句自造的） */}
        {state.detail && <div className="artifact-content-detail">{state.detail}</div>}
        <div className="artifact-content-id mono">{artifactId.slice(0, 16)}…</div>
      </div>
    );
  }
  const { slice } = state;
  if (slice.lines.length === 0) {
    // 拿到了但一行都没有：如实说"没有内容"，不装成加载中
    return (
      <div className="artifact-content artifact-content-empty">
        <Package size={16} aria-hidden="true" />
        <span>这个 artifact 没有可显示的内容。</span>
      </div>
    );
  }
  return (
    <div className="artifact-content">
      <div className="artifact-content-bar">
        <span className="artifact-content-count">
          {slice.truncated
            ? `显示 ${slice.returned_lines} / 共 ${slice.total_lines} 行（已截断）`
            : `共 ${slice.total_lines} 行`}
        </span>
        <span className="artifact-content-id mono">{slice.artifact_id.slice(0, 16)}…</span>
      </div>
      <pre className="artifact-content-lines">
        {slice.lines.map((line) => (
          <span className="artifact-line" key={line.line_number}>
            <span className="artifact-line-no" aria-hidden="true">
              {line.line_number}
            </span>
            <span className="artifact-line-text">
              {line.text}
              {line.truncated && (
                <span
                  className="artifact-line-cut"
                  title={`该行因超长被截断（原长 ${line.full_length ?? '?'} 字符）`}
                >
                  …（此行已截断）
                </span>
              )}
            </span>
            {'\n'}
          </span>
        ))}
      </pre>
    </div>
  );
}

/** 取数 + 折叠：**就地展开**的那一层（不带任何弹窗——票面 AC2 要求不新开导航面）。 */
export function ArtifactViewer({
  sessionId,
  artifactId,
  /** 展开后的标题（默认给"查看完整内容"的语义）。 */
  label = '完整内容',
  /** 一开始就展开（清单里点开的那一行用 true）。 */
  defaultOpen = false,
}: {
  sessionId: string;
  artifactId: string;
  label?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [state, setState] = useState<ArtifactContentState>({ status: 'loading' });

  /* 取数本身**不**同步改状态：初始态已是 loading，而在 effect 里同步 setState
     会多一次渲染（且被 react-hooks 的 set-state-in-effect 判为多余）。
     "重新变回 loading"只发生在用户点重试这个事件里。

     存活标记放在 ref 里而不是闭包局部变量：`retry()` 也发起请求，但它拿不到 `load()`
     的清理函数（事件处理器没有卸载钩子），闭包里的 `alive` 就永远为 true——重试在飞时
     组件卸载，回调仍会 setState 到已卸载实例上。ref 让两条路径共用同一个门。

     开关都在**同一个 effect** 里臂化/释放（不是单独一个"只在卸载时置 false"的 effect）：
     本应用是 `StrictMode`（`main.tsx:13`），开发期 effect 会被清理后重跑一次；若只有
     卸载置 false，模拟卸载会把它永久关掉，首次真实取数的结果就被丢掉（面板卡在
     "加载中"）。 */
  const aliveRef = useRef(true);

  const load = useCallback(() => {
    getArtifactContent(sessionId, artifactId)
      .then((slice) => {
        if (aliveRef.current) setState({ status: 'ready', slice });
      })
      .catch((err: unknown) => {
        if (!aliveRef.current) return;
        if (err instanceof ArtifactContentError) {
          setState({ status: 'error', kind: err.kind, detail: err.detail });
        } else {
          setState({
            status: 'error',
            kind: 'error',
            detail: err instanceof Error ? err.message : '',
          });
        }
      });
  }, [sessionId, artifactId]);

  // 只在**真的展开**时取数：没展开就请求等于替用户读了他没要的东西。
  // 换一个产物（`artifactId` 变）时 `load` 是新函数，effect 随之重跑。
  useEffect(() => {
    if (!open) return;
    aliveRef.current = true;
    load();
    return () => {
      aliveRef.current = false;
    };
  }, [open, load]);

  const retry = () => {
    setState({ status: 'loading' });
    load();
  };

  return (
    <div className="artifact-viewer">
      <button
        type="button"
        className="artifact-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
        {open ? '收起' : label}
      </button>
      {open && (
        <>
          <ArtifactContentView state={state} artifactId={artifactId} />
          {state.status === 'error' && (
            <button type="button" className="artifact-retry" onClick={retry}>
              重试
            </button>
          )}
        </>
      )}
    </div>
  );
}
