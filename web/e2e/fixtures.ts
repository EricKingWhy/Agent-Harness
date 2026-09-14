/** T8（#101）E2E fixture 助手——mock SSE 帧形状 = docs/BACKEND_CONTRACT_STREAMING_UI.md：
 *  text/delta durable 承接文本流、reasoning 族 envelope block_id、tool/output_delta
 *  按 channel、seq 每 session 单调。page.route 拦截 API，核心矩阵不依赖真后端。 */

import { expect, type Page, type Route } from '@playwright/test';

export const SID = 'e2e-session-0001';
export const RUN = 'e2e-run-0001';
export const T = '2026-09-07T00:00:00Z';

export interface FrameSpec {
  type: string;
  data?: Record<string, unknown>;
  seq?: number | null;
  run_id?: string | null;
  step_id?: number | null;
  session_id?: string | null;
  block_id?: string | null;
  time?: string;
}

export function sseFrame(f: FrameSpec): string {
  return `data: ${JSON.stringify(f)}\n\n`;
}

/** SSE 帧 → route.fulfill（字符串形态——Playwright fulfill({ response }) 的
 *  Response 包装在本环境不可靠（帧未送达），f-history 证明字符串形态可用）。
 *  帧一次性到达：投影瞬时完成，骨架只断言终态；流式中间态（caret/呼吸图标/
 *  跟随浮标）留待联调车道（真后端或本地 SSE fixture server，见 map 文档）。 */
export async function fulfillSse(route: Route, frames: FrameSpec[]): Promise<void> {
  await route.fulfill({ status: 200, contentType: 'text/event-stream', body: frames.map(sseFrame).join('') });
}

export interface ApiMock {
  /** GET /api/sessions（会话列表） */
  sessions?: unknown[];
  /** GET /api/sessions/{id}/events（历史重放） */
  events?: FrameSpec[];
  /** 第 N 次之后的 `GET /api/sessions` 直接回 500（N 从 1 数）。
   *  用途：构造"归档写成功了、但随后的列表重拉失败"这个只在真机上偶发的窗口——
   *  界面此刻的行还是旧状态，必须**说出来**而不是沉默（#171 AC9 的就地报错）。
   *  不设 = 永远成功。 */
  sessionsListFailAfter?: number;
  /** GET /api/models（模型目录；缺省 = 空目录 → 选择器降级隐藏） */
  models?: unknown[];
  /** POST /api/sessions（live 流） */
  onSessionPost?: (route: Route) => Promise<void> | void;
  /** GET /api/sessions/{id}/stream?after_seq=N（重连续传） */
  onStreamGet?: (route: Route) => Promise<void> | void;
  // ── Phase 2b Composer control row（Ticket F1/B1）──
  /** GET /api/permission-modes（权限模式清单） */
  permissionModes?: unknown[];
  /** GET /api/agent-profiles（Agent Profile 清单） */
  agentProfiles?: unknown[];
  /** GET /api/reasoning-efforts（Reasoning Effort 档位清单） */
  reasoningEfforts?: unknown[];
  /** GET /api/context-providers（Context Provider 清单；当前诚实返空） */
  contextProviders?: unknown[];
  // ── #182 能力声明显隐 ──
  /** GET /api/capabilities 的条目（形状 = 后端 `capability/manifest.py::manifest_entry`；
   *  用 `capabilityFixture` 造插件条目）。
   *
   *  **缺省 = `[CORE_CAPABILITY]`**（#193）：真实后端在 `CAPABILITIES=""` 时返回的正是
   *  "只有 core 一条"——core 是**内置工具集**的声明，恒在，且声明
   *  `changes`/`terminal` 为 true（那两个面由 `write`/`edit`/`apply_patch`/`bash` 产出，
   *  不由任何插件产出）。此前缺省是空列表，那是 #193 修掉之前的事实；空列表那条路径
   *  仍有意义（老后端 / 显式 mock），所以想覆盖它就在用例里显式传 `capabilities: []`。
   *
   *  这里**不**给"默认全 true"的省事值：声明是能力的事，mock 给什么就渲染什么
   *  （否则绿灯只证明"前端与我的假后端一致"——本仓已栽过这个坑）。 */
  capabilities?: unknown[];
  /** capabilities 端点直接回错误（老后端 404 / 服务异常）→ 前端降级为缺省语义。 */
  capabilitiesError?: { status: number; detail: string };
  // ── #185 路由 / #186 消费：GET /api/sessions/{id}/artifacts/{aid} ──
  /** 内容切片（形状 = 后端 `ArtifactSlice.model_dump()`）。 */
  artifactContent?: unknown;
  /** 直接回错误（404 不在本会话 / 503 没配存储 / 422 形态非法）。 */
  artifactContentError?: { status: number; detail: string };
  /** 拦截口（计数 / 按 artifact_id 给不同内容）；返回 true = 已处理。 */
  onArtifactGet?: (route: Route, artifactId: string) => Promise<boolean> | boolean;
  /** GET /api/capabilities 的拦截口（计数 / 断言"端点真的被消费了"）；返回 true = 已处理。
   *  为什么要这个口子：**"端点没被调用"这类回归不会改变 tab 集**（缺省 payload 与
   *  "拿到真 payload" 都会渲染出面），所以只断言 tab 集会漏掉"前端压根没调这个端点"
   *  这种 bug——`onCapabilitiesGet` 计数把"端点确实被消费且没有请求循环"钉住。
   *  返回 false 走下面的默认分支。 */
  onCapabilitiesGet?: (route: Route) => Promise<boolean> | boolean;
  /** POST /api/sessions/{id}/messages（续聊入口；空闲会话 → 同形 SSE） */
  onMessagesPost?: (route: Route) => Promise<void> | void;
  /** POST /api/sessions/{id}/model（T7 #137 模型切换；缺省 200 → 回传请求的
   *  provider/model_id，即真实端点的「规范 model_id」形状）。
   *  注入此回调即可**计数**或延迟响应（BUG-011 回归锁：双击只允许一个请求；
   *  延迟响应用来撑开「首个请求还没回来就又点了一下」这个窗口）。 */
  onModelPost?: (route: Route) => Promise<void> | void;
  /** POST /api/sessions/{id}/forks（T7 #137 分叉；缺省 200 → 派生 child）。
   *  注入此回调即可断言请求体（BUG-001 回归锁：from_seq 必须是 user/message 的
   *  seq，不是 turn.step_id）或伪造 422。 */
  onForkPost?: (route: Route) => Promise<void> | void;
  /** POST /api/sessions/{id}/recover（T8 #138 恢复；缺省 200 → 返回 mock.events）。
   *  真实语义：响应是与 GET events 同构的全量事件数组。 */
  onRecoverPost?: (route: Route) => Promise<void> | void;
  /** POST /api/sessions/{id}/approve（#37 交互式审批决策；缺省 200 → {status,approval_id,decision}）。
   *  注入此回调即可断言请求体（回归锁：批准 → decision='approve_once'、拒绝 → 'deny'；
   *  形状与后端 `session/approval.py` 的 allowed_decisions 一致）。 */
  onApprovePost?: (route: Route) => Promise<void> | void;
  // ── #172 / ADR-0029 会话硬删 ──
  /** 指定 id 的 DELETE /api/sessions/{id} 直接回这个错误——用来构造只在真机上才会
   *  自然出现的拒绝：409（有在途 run / 有挂起审批 / 是 fork 父会话；**状态码相同**，
   *  只有 detail 原句不同）与 404（"这个会话本就不在了"，第二次删除）。
   *
   *  status 404 的条目会**同时**把它从会话状态里摘掉：真后端在那一刻它确实不在，
   *  留着会让重拉之后那一行又冒出来——mock 语义与真机相反（#155 轮栽过这个坑）。
   *
   *  不设 = 按真后端语义**成功**：真的从会话列表与项目账本里摘掉它，`events` 取行上
   *  的 `event_count`（真后端也是删之前取），`detached_from_projects` 数它进过几个
   *  账本。所以"删完行没了、项目计数也掉了"考的是界面跟着后端走，不是本地隐藏。 */
  sessionDeleteErrors?: Record<string, { status: number; detail: string }>;
  // ── #171 会话归档（可逆标记）──
  /** 指定 id 的 POST/DELETE `/api/sessions/{id}/archive` 直接回这个错误——用来构造
   *  真机上才有自然来源的拒绝：409（**只在归档方向上**：有在途 run / 挂起审批，
   *  见后端 `SessionService.set_archived`）与 404（元数据/日志都在的会话才会走到这里，
   *  所以 404 只能这么造）。
   *
   *  与硬删的同类字段一样：不设 = 按真后端语义**成功**（真的改行的 `archived` 字段）。 */
  sessionArchiveErrors?: Record<string, { status: number; detail: string }>;
  /** 这些 id 视为"忙"（有在途 run）→ 归档回 409，但 `sessionArchiveErrors` 优先。
   *  与硬删的差别是有意的：后端只在**归档**方向挡 409，取消归档永远允许
   *  （否则一个正在跑的会话一旦被归档就再也没法取消归档了）。 */
  sessionArchiveBusyIds?: string[];
  /** POST/DELETE `/api/sessions/{id}/archive` 的拦截口（计数 / 断言请求形状）；
   *  `archived` = 动作后的目标态（POST → true、DELETE → false）。返回 true = 已处理。 */
  onArchiveRequest?: (
    route: Route,
    sessionId: string,
    archived: boolean,
  ) => Promise<boolean> | boolean;
  // ── WS-5 / #155 项目分组 ──
  /** 项目 fixture（缺省 = 无项目 → 所有会话都在未分组区）。
   *
   *  **有状态**：fixtures 在内存里真的改这份状态并按后端语义回响应（见
   *  `routeApi` 里的 projects 分支）——create 前插注册表、rename 改标题、
   *  attach/detach 改账本**并同步改会话行的 workspace**、软删除摘记录**并把
   *  成员会话的 workspace 清成 null**、order 按 insertBefore 语义重排。
   *  这样 e2e 断言的是"界面真的跟着后端的语义走"，而不是"界面读了我们塞的假值"。 */
  projects?: ProjectFixture[];
  /** `POST /api/projects` 里**不存在**的路径集合 → 404（真实后端不 mkdir）。
   *  用来锁"路径不存在时有清晰错误"这条 AC。 */
  projectMissingPaths?: string[];
  /** POST /api/projects/{id}/sessions 的拦截口（伪造 409「会话 cwd 与项目路径
   *  不一致」等**只能在真机上才自然出现**的拒绝）；返回 true = 已处理。
   *  与 `projectMissingPaths` 的分工：那个改的是"哪些路径不存在"，这个改的是
   *  "attach 这条请求本身回什么"。 */
  onAttachPost?: (route: Route) => Promise<boolean> | boolean;
  // ── MEM-5 / #160 记忆管理 ──
  /** 记忆 fixture（缺省 = 空列表 → 面板显示"还没有记忆"）。
   *
   *  **有状态**：DELETE 真的从这份状态里摘掉条目（见 `routeApi` 的 memories 分支），
   *  所以"删掉后关掉面板再打开，该条不在"断言的是真语义，而不是界面自己的本地隐藏。
   *  分页也按真实端点走（`limit`/`offset` 切片），"加载更多"因此可被真的驱动。 */
  memories?: MemoryFixture[];
  /** 记忆能力未装配 → GET/DELETE 都回 503 + 该 detail（AC4 降级态）。
   *  刻意用真实后端那句话（`web/memory.py`）：前端把"未启用"与"没有记忆"分开显示。 */
  memoryDisabled?: string;
  /** 这些 id 的 DELETE 回 403（`web/memory.py` 的"不属于当前入口"）——AC3 的
   *  失败回滚路径（真机上要构造一条 SESSION 记忆才自然出现）。 */
  memoryDeniedIds?: string[];
  /** 这些 id 模拟「列表拉取之后、点删除之前被别处删掉」：DELETE 回 404（真后端那句
   *  `记忆不存在：<id>`）**并且**把它从状态里摘掉——于是随后的重拉里那一行不在，
   *  行内错误条无处渲染。真机上这是一个并发窗口，只能在 mock 里构造；
   *  它锁的是"失败被界面吞掉"这条缺陷（批次审查发现）。 */
  memoryVanishedIds?: string[];
  /** GET /api/memories 的拦截口（断言分页参数或伪造 500）；返回 true = 已处理。 */
  onMemoriesGet?: (route: Route) => Promise<boolean> | boolean;
  // ── WS-6 / #169 项目内新建任务 ──
  /** 带 `cwd` 建会话时伪造失败（AC12：422 留在确认面）。spec 可以先设它、断言错误
   *  在浮层里，再设回 undefined 并重试——同一条路径因此能覆盖"可重试"。
   *  不设 = 按真后端语义成功（见 routeApi 的 POST /api/sessions 分支）。 */
  cwdSessionError?: { status: number; detail: string };
  // ── WS-7 / #170 宿主目录列举 ──
  /** 假目录树（`GET /api/host/dirs`）。**不设 = 空的根列举**（不是错误）：浏览器是
   *  新建项目对话框的一部分，不关心它的 spec 不该因此多出一条红色错误盒。
   *  错误矩阵由 `hostDirsErrors`（403/404/422 + detail）或假树里没有的路径显式构造。
   *
   *  spec 只声明"每个目录下有哪些子目录名"，`path`/`parent` 由 fixture 按目录结构
   *  **拼**出来（与真后端 `host_dirs.py` 同一口径：条目的 path = 父路径 + 名字，
   *  不做 realpath 展开；排序按 name 大小写不敏感）。这样 mock 里不会出现第二套
   *  路径拼接逻辑被 spec 抄一遍而悄悄写歪（#155 轮栽过 mock 语义与真机相反）。 */
  hostDirs?: {
    /** 键 = 目录绝对路径（分隔符可 `\` 或 `/`，与请求参数逐字符相等才命中）；
     *  值 = 该目录下的子目录名（顺序不限，fixture 排序）。 */
    tree: Record<string, string[]>;
    /** 根模式（`path` 缺省）的盘符/根列表。 */
    roots?: string[];
    /** 单个目录最多列举多少条（缺省 500 = 后端 `MAX_ENTRIES`）；超出 → truncated。 */
    maxEntries?: number;
  };
  /** 这些路径的列举直接回错误（错误矩阵就地显示：403 无权限 / 404 / 422 不是目录）。 */
  hostDirsErrors?: Record<string, { status: number; detail: string }>;
}

/** 项目 fixture（形状 = 后端 `web/projects.py::Project`，时间戳由 fixtures 补）。 */
export interface ProjectFixture {
  id: string;
  path: string;
  title: string;
  /** 账本手工序。 */
  session_ids: string[];
  status?: 'ok' | 'missing-dir';
}

/** 记忆 fixture（形状 = 后端 `web/memory.py::MemorySummary`，时间戳由 fixtures 补）。 */
export interface MemoryFixture {
  id: string;
  content: string;
  scope?: 'user' | 'session';
  metadata?: Record<string, unknown>;
  created_at?: string;
}

/** 会话行 fixture：只带 WS-5 相关字段，其余由调用方按需补（旧 spec 的裸对象同样可用）。 */
export function sessionRow(
  sessionId: string,
  workspace: { id: string; title: string } | null = null,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    session_id: sessionId,
    event_count: 3,
    first_event_time: T,
    last_event_time: T,
    first_user_message: `任务 ${sessionId}`,
    trace_id: null,
    trace_url: null,
    workspace,
    // #171：后端 `SessionSummary.archived` 是**必填布尔**（没有 meta 行 = false），
    // 所以 mock 也给一个字面量默认值——前端类型把它声明成可选就会让"漏读"变成
    // `undefined`（静默假），这条默认值让 mock 与真后端的形状一致。
    archived: false,
    ...over,
  };
}

/** 按会话 id 定位侧栏里的一行（行内 id 文本是 `session_id.slice(0, 12)`，所以短 id
 *  才匹配得上）。放在这里而不是各 spec 各写一份：窄屏 / 删会话 / 触摸可达几个车道都
 *  用同一条定位（见本文件顶部"多个 spec 共用同一份，避免各自复制后静默漂移"）。 */
export const rowOf = (page: Page, sessionId: string) =>
  page
    .locator('.session-row')
    .filter({ has: page.locator('.session-item-id', { hasText: sessionId }) });

export function routeApi(page: Page, mock: ApiMock): void {
  // ── WS-5 #155：可变状态（每测试一份，互不串味）──
  // 注意 sessions **持有调用方数组的引用**，不拷贝：既有 spec 的约定是"fork 成功后
  // 往自己的 sessions 数组里 push child，下一次 GET 就能看到"（b-fork.spec.ts 依赖
  // 这一点）。除 #172 的硬删分支外，本车道只在原地改行的 `workspace` 字段，既不新增
  // 也不删除行；硬删是**真的**删（`splice`）——那正是它的语义，调用方的数组也跟着变
  // （spec 据此断言"删完重拉就没有这一行了"）。
  const sessionState: unknown[] = mock.sessions ?? [];
  const projectState: ProjectFixture[] = (mock.projects ?? []).map((p) => ({
    ...p,
    session_ids: [...p.session_ids],
  }));
  /** 记忆状态：DELETE 真的摘条目（"删掉后再打开面板看不到"才是真语义）。 */
  const memoryState: MemoryFixture[] = (mock.memories ?? []).map((m) => ({ ...m }));
  /** 带 cwd 建会话时**真的发生过**的帧（供 GET /events 回读：见该分支注释）。 */
  const sessionEvents = new Map<string, FrameSpec[]>();
  /** `GET /api/sessions` 的次数（`sessionsListFailAfter` 用；见该分支注释）。 */
  let listCalls = 0;

  /** 后端 `web/projects.py::Project` 的响应形状（时间戳不是本车道断言的对象）。 */
  const projectView = (p: ProjectFixture) => ({
    id: p.id,
    path: p.path,
    title: p.title,
    status: p.status ?? 'ok',
    session_ids: p.session_ids,
    created_at: T,
    updated_at: T,
  });
  const findProject = (id: string) => projectState.find((p) => p.id === id);
  /** 从项目账本里摘掉这个会话，返回**实际摘掉几个账本**（真后端
   *  `WorkspaceIndex.detach_session` 的返回值就是它，`detached_from_projects` 用它）。
   *  硬删的成功分支与 404 分支共用——404 那条（"别处已经删了"）在真后端里账本也早
   *  就解除了，留着会让 rail 报一条"n 条会话日志缺失"的假缺失。 */
  const detachFromLedgers = (sessionId: string): number => {
    let detached = 0;
    for (const p of projectState) {
      const at = p.session_ids.indexOf(sessionId);
      if (at >= 0) {
        p.session_ids.splice(at, 1);
        detached += 1;
      }
    }
    return detached;
  };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, body: JSON.stringify(body), contentType: 'application/json' });
  /** 把某会话的 workspace 引用同步成"它现在属于谁"——与真实后端一致
   *  （attach/detach/软删除后 GET /api/sessions 的行立刻变）。
   *  替换而非改原对象：调用方的 fixture 行是**字面量常量**，就地改会污染同一文件里
   *  其它用例的期望（各 spec 之间共享模块级常量）。 */
  const setWorkspace = (sessionId: string, project: ProjectFixture | null) => {
    const at = sessionState.findIndex(
      (s) => (s as Record<string, unknown>)['session_id'] === sessionId,
    );
    if (at >= 0) {
      sessionState[at] = {
        ...(sessionState[at] as Record<string, unknown>),
        workspace: project ? { id: project.id, title: project.title } : null,
      };
    }
  };

  void page.route('**/api/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === '/api/health') {
      return route.fulfill({ status: 200, body: '{"status":"ok"}', contentType: 'application/json' });
    }
    if (path === '/api/sessions' && req.method() === 'GET') {
      // `sessionsListFailAfter`：先数够 N 次成功，之后一律 500（构造"归档后重拉失败"）。
      listCalls += 1;
      if (mock.sessionsListFailAfter !== undefined && listCalls > mock.sessionsListFailAfter) {
        return json(route, { detail: '会话列表暂时不可用' }, 500);
      }
      // #171 AC3：`include_archived` 是**后端**的契约（不带 = 不返回已归档行）。
      // mock 照真后端过滤，于是"UI 总是显式要全量"这条设计能被真的考到：漏掉那个
      // 参数时，开关打开也看不到归档行（前端本地过滤救不了它）。
      const includeArchived = new URL(req.url()).searchParams.get('include_archived') === 'true';
      const rows = includeArchived
        ? sessionState
        : sessionState.filter((s) => (s as Record<string, unknown>)['archived'] !== true);
      return json(route, rows);
    }
    if (path === '/api/sessions' && req.method() === 'POST') {
      if (mock.onSessionPost) return mock.onSessionPost(route);
      const body = (req.postDataJSON() ?? {}) as Record<string, unknown>;
      const cwd = typeof body.cwd === 'string' ? body.cwd : '';
      if (!cwd) return route.abort('aborted');
      // ── WS-6 / #169：带 cwd 建会话 —— 按真后端语义（ADR-0027 D2/D3）真的改状态：
      //  会话诞生在该目录、自动入组（未注册的 cwd 自动注册为项目，title = 目录末段名），
      //  于是"新会话落在该项目分组下"这条断言考的是界面跟着后端语义走，
      //  而不是"界面读了我们塞的假值"（fixture 的既有纪律）。
      if (mock.cwdSessionError) {
        return json(route, { detail: mock.cwdSessionError.detail }, mock.cwdSessionError.status);
      }
      const sid = `cwd-${sessionState.length + 1}`;
      let project = projectState.find((p) => p.path === cwd);
      if (!project) {
        project = {
          id: `p-${projectState.length + 1}`,
          path: cwd,
          title: cwd.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || cwd,
          session_ids: [],
        };
        projectState.unshift(project);
      }
      sessionState.unshift(
        sessionRow(sid, { id: project.id, title: project.title }, {
          first_user_message: typeof body.task === 'string' ? body.task : '新任务',
        }),
      );
      project.session_ids.unshift(sid); // 账本前插（与 attach 语义一致）
      const frames: FrameSpec[] = [
        // 帧序照真后端（#151 的机制）：session/started → run/started → user/message
        // → model/started → text/delta → model/completed → run/completed。
        // 缺 user/message 或 model/* 会让"回答真的渲染出来了"这条断言测不到东西。
        { type: 'session/started', data: { cwd }, seq: 1, session_id: sid, run_id: RUN, time: T },
        { type: 'run/started', seq: 2, session_id: sid, run_id: RUN, time: T },
        {
          type: 'user/message',
          data: { content: typeof body.task === 'string' ? body.task : '新任务' },
          seq: 3,
          session_id: sid,
          run_id: RUN,
          step_id: 1,
          time: T,
        },
        { type: 'model/started', data: { model: 'e2e-model' }, seq: 4, session_id: sid, run_id: RUN, step_id: 1, time: T },
        { type: 'text/delta', data: { delta: '好，我先看看这个目录。' }, seq: 5, session_id: sid, run_id: RUN, step_id: 1, time: T },
        { type: 'model/completed', data: { model: 'e2e-model' }, seq: 6, session_id: sid, run_id: RUN, step_id: 1, time: T },
        { type: 'run/completed', data: {}, seq: 7, session_id: sid, run_id: RUN, time: T },
      ];
      sessionEvents.set(sid, frames); // durable log = 刚才流的那些帧（见 /events 分支）
      return fulfillSse(route, frames);
    }
    // ── #185 / #186：artifact 内容读取（只读端点）──
    const artifactMatch = /^\/api\/sessions\/([^/]+)\/artifacts\/([^/]+)$/.exec(path);
    if (artifactMatch && req.method() === 'GET') {
      const aid = decodeURIComponent(artifactMatch[2]);
      if (mock.onArtifactGet) {
        const handled = await mock.onArtifactGet(route, aid);
        if (handled) return undefined;
      }
      const forced = mock.artifactContentError;
      if (forced) return json(route, { detail: forced.detail }, forced.status);
      return json(route, mock.artifactContent ?? { artifact_id: aid, lines: [], total_lines: 0, returned_lines: 0, truncated: false });
    }
    // ── #171 会话归档（有状态 mock：语义对齐 `web/app.py::archive_session`）──
    const sessionArchiveMatch = /^\/api\/sessions\/([^/]+)\/archive$/.exec(path);
    if (sessionArchiveMatch && (req.method() === 'POST' || req.method() === 'DELETE')) {
      const sid = decodeURIComponent(sessionArchiveMatch[1]);
      const target = req.method() === 'POST'; // POST = 归档 true；DELETE = 取消归档 false
      if (mock.onArchiveRequest && (await mock.onArchiveRequest(route, sid, target))) return undefined;
      const forced = mock.sessionArchiveErrors?.[sid];
      if (forced) return json(route, { detail: forced.detail }, forced.status);
      const at = sessionState.findIndex(
        (s) => (s as Record<string, unknown>)['session_id'] === sid,
      );
      // 404 的 detail 照抄后端 `SessionService._require_existing_session` 抛出的那句
      // （`session 'x' not found`）：自己编一句中文会让门槛内的绿灯只证明
      // "前端与我的假后端一致"。
      if (at < 0) return json(route, { detail: `session '${sid}' not found` }, 404);
      // 409 **只在归档方向**：后端 `set_archived` 的守卫顺序是「存在 → 在途 run」，
      // 而 `archived and run_manager.get_active(...)` 这个连词意味着取消归档永不 409。
      if (target && (mock.sessionArchiveBusyIds ?? []).includes(sid)) {
        // detail 逐字照抄后端 `service.py::set_archived` 抛的 `ActiveRunConflict` 原句。
        return json(
          route,
          { detail: `session '${sid}' has a run in flight; archive it after it finishes` },
          409,
        );
      }
      // 幂等：重复归档仍是 true（后端用 upsert/set_archived，不是"翻转"）。
      sessionState[at] = { ...(sessionState[at] as Record<string, unknown>), archived: target };
      return json(route, { id: sid, archived: target });
    }
    // ── #172 / ADR-0029 会话硬删（有状态 mock：语义对齐 `web/app.py::delete_session`）──
    const sessionDeleteMatch = /^\/api\/sessions\/([^/]+)$/.exec(path);
    if (sessionDeleteMatch && req.method() === 'DELETE') {
      const sid = decodeURIComponent(sessionDeleteMatch[1]);
      const forced = mock.sessionDeleteErrors?.[sid];
      if (forced) {
        // 404 的条目**同时**摘掉这一行与它在项目账本里的条目：真后端在那一刻它确实
        // 不在（第二次删除就是这个），而用户走完一次真删时账本也已经解除过了——
        // 留在状态里会让重拉之后那行又冒出来、还带一条"n 条会话日志缺失"的假缺失。
        if (forced.status === 404) {
          const at404 = sessionState.findIndex(
            (s) => (s as Record<string, unknown>)['session_id'] === sid,
          );
          if (at404 >= 0) sessionState.splice(at404, 1);
          detachFromLedgers(sid);
        }
        return json(route, { detail: forced.detail }, forced.status);
      }
      const at = sessionState.findIndex(
        (s) => (s as Record<string, unknown>)['session_id'] === sid,
      );
      if (at < 0) return json(route, { detail: `session '${sid}' not found` }, 404);
      const row = sessionState[at] as Record<string, unknown>;
      // 事件数在**删之前**取：删完只剩文件系统，无从统计（真后端同一顺序）。
      const events = typeof row['event_count'] === 'number' ? row['event_count'] : 0;
      // 真后端的第二条判据：日志为空（event_count == 0）也是 404——"删得掉"与"看得见"
      // 永远一致，不给出一个列表里没有内容的 id 的删除假回执。**什么都不删**。
      if (events === 0) return json(route, { detail: `session '${sid}' not found` }, 404);
      sessionState.splice(at, 1);
      // 项目账本真的摘掉它，并按实际摘掉的账本数报 `detached_from_projects`——
      // "删完项目计数也掉了"这条断言因此考的是界面跟着后端语义走，而不是本地把行藏起来。
      const detached = detachFromLedgers(sid);
      return json(route, { id: sid, deleted: true, events, detached_from_projects: detached });
    }
    if (/^\/api\/sessions\/[^/]+\/events$/.test(path)) {
      // 带 cwd 建的会话：它的 durable log **就是**刚才流出来的那些帧（真后端同理——
      // run 收尾后前端会回读日志对账）。不给这份日志，流的结论会被下一次回读清空，
      // "回答真的渲染出来了"就永远测不到（mock 语义与真机不一致的另一种形态）。
      const sid = decodeURIComponent(path.split('/')[3] ?? '');
      const streamed = sessionEvents.get(sid);
      return route.fulfill({
        status: 200,
        body: JSON.stringify(streamed ?? mock.events ?? []),
        contentType: 'application/json',
      });
    }
    if (/^\/api\/sessions\/[^/]+\/stream$/.test(path)) {
      if (mock.onStreamGet) return mock.onStreamGet(route);
      return route.abort('aborted');
    }
    if (path === '/api/models') {
      return route.fulfill({ status: 200, body: JSON.stringify({ models: mock.models ?? [] }), contentType: 'application/json' });
    }
    // ── Phase 2b Composer control row（Ticket F1/B1）──
    if (path === '/api/permission-modes') {
      return route.fulfill({ status: 200, body: JSON.stringify({ modes: mock.permissionModes ?? [] }), contentType: 'application/json' });
    }
    if (path === '/api/agent-profiles') {
      return route.fulfill({ status: 200, body: JSON.stringify({ profiles: mock.agentProfiles ?? [] }), contentType: 'application/json' });
    }
    if (path === '/api/reasoning-efforts') {
      return route.fulfill({ status: 200, body: JSON.stringify({ efforts: mock.reasoningEfforts ?? [] }), contentType: 'application/json' });
    }
    if (path === '/api/context-providers') {
      return route.fulfill({ status: 200, body: JSON.stringify({ providers: mock.contextProviders ?? [] }), contentType: 'application/json' });
    }
    if (path === '/api/capabilities') {
      if (mock.onCapabilitiesGet && (await mock.onCapabilitiesGet(route))) return;
      if (mock.capabilitiesError) {
        return json(route, { detail: mock.capabilitiesError.detail }, mock.capabilitiesError.status);
      }
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ capabilities: mock.capabilities ?? [CORE_CAPABILITY] }),
        contentType: 'application/json',
      });
    }
    if (/^\/api\/sessions\/[^/]+\/model$/.test(path) && req.method() === 'POST') {
      if (mock.onModelPost) return mock.onModelPost(route);
      const body = (req.postDataJSON() ?? {}) as { provider?: string; model_id?: string };
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          status: 'changed',
          provider: body.provider ?? '',
          model_id: body.model_id ?? '',
        }),
        contentType: 'application/json',
      });
    }
    if (/^\/api\/sessions\/[^/]+\/messages$/.test(path) && req.method() === 'POST') {
      if (mock.onMessagesPost) return mock.onMessagesPost(route);
      return route.abort('aborted');
    }
    if (/^\/api\/sessions\/[^/]+\/forks$/.test(path) && req.method() === 'POST') {
      if (mock.onForkPost) return mock.onForkPost(route);
      const body = (req.postDataJSON() ?? {}) as { from_seq?: number };
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ session_id: `${SID}-fork-${body.from_seq ?? 0}`, from_seq: body.from_seq ?? 0 }),
        contentType: 'application/json',
      });
    }
    if (/^\/api\/sessions\/[^/]+\/recover$/.test(path) && req.method() === 'POST') {
      if (mock.onRecoverPost) return mock.onRecoverPost(route);
      return route.fulfill({ status: 200, body: JSON.stringify(mock.events ?? []), contentType: 'application/json' });
    }
    if (/^\/api\/sessions\/[^/]+\/approve$/.test(path) && req.method() === 'POST') {
      if (mock.onApprovePost) return mock.onApprovePost(route);
      const body = (req.postDataJSON() ?? {}) as { approval_id?: string; decision?: string };
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          status: 'resolved',
          approval_id: body.approval_id ?? '',
          decision: body.decision ?? '',
        }),
        contentType: 'application/json',
      });
    }

    // ── MEM-5 / #160 记忆端点（有状态 mock：语义对齐后端 `web/memory.py`）──
    if (path === '/api/memories' && req.method() === 'GET') {
      if (mock.onMemoriesGet && (await mock.onMemoriesGet(route))) return;
      if (mock.memoryDisabled) return json(route, { detail: mock.memoryDisabled }, 503);
      const params = new URL(req.url()).searchParams;
      const limit = Number(params.get('limit') ?? '50');
      const offset = Number(params.get('offset') ?? '0');
      // 按后端语义切片（`web/memory.py` 的 limit/offset 分页）——"加载更多"因此
      // 真的会拿到下一页，而不是界面自己把一份全量数组切两半。
      const page = memoryState.slice(offset, offset + limit).map((m) => ({
        id: m.id,
        content: m.content,
        scope: m.scope ?? 'user',
        metadata: m.metadata ?? {},
        created_at: m.created_at ?? T,
      }));
      return json(route, page);
    }
    const memoryMatch = /^\/api\/memories\/([^/]+)$/.exec(path);
    if (memoryMatch && req.method() === 'DELETE') {
      if (mock.memoryDisabled) return json(route, { detail: mock.memoryDisabled }, 503);
      const memoryId = decodeURIComponent(memoryMatch[1]);
      // 403 = 领域层的归属校验（`MemoryRecordStore.delete` 的 namespace 匹配）：
      // 与 404「这条不在了」分开——AC3 的失败回滚就靠这条。
      //
      // detail **逐字照抄**真后端：`web/domain_errors.py::memory_http_error` 用
      // `str(exc)`，而 `sqlite_record_store.py:195` 抛的是
      // `PermissionError("Memory belongs to a different namespace")`（英文原句）。
      // 自己编一句中文会让门槛内的绿灯只证明"前端与我的假后端一致"（#155 轮已
      // 栽过同一个坑：mock 语义与真机相反）。
      if ((mock.memoryDeniedIds ?? []).includes(memoryId)) {
        return json(route, { detail: 'Memory belongs to a different namespace' }, 403);
      }
      const at = memoryState.findIndex((m) => m.id === memoryId);
      // 404 的 detail 同样照抄：`memory/errors.py::MemoryNotFound` → `记忆不存在：<id>`。
      if ((mock.memoryVanishedIds ?? []).includes(memoryId)) {
        if (at >= 0) memoryState.splice(at, 1); // "别处已删"：重拉时这一行没了
        return json(route, { detail: `记忆不存在：${memoryId}` }, 404);
      }
      if (at < 0) return json(route, { detail: `记忆不存在：${memoryId}` }, 404);
      memoryState.splice(at, 1); // 硬删：记录真的没了（不是软删/回收站）
      return json(route, { id: memoryId, deleted: true });
    }

    // ── WS-5 / #155 项目端点（有状态 mock：语义对齐后端 `web/projects.py`）──
    if (path === '/api/projects' && req.method() === 'GET') {
      return json(route, projectState.map(projectView));
    }
    if (path === '/api/projects' && req.method() === 'POST') {
      if (mock.onProjectPost && (await mock.onProjectPost(route))) return;
      const body = (req.postDataJSON() ?? {}) as { path?: string; title?: string };
      const target = body.path ?? '';
      if ((mock.projectMissingPaths ?? []).includes(target)) {
        // 逐字照抄真实后端在 Windows 上的 detail（`FileNotFoundError` 的
        // `str(exc)`）：**故意不做美化**——AC3 要证明的是"后端说了什么，界面就
        // 显示什么"，所以断言打在 `WinError 3` 与路径上；如果前端把它翻译成
        // 自己的话或吞掉原串，这条用例必须变红。
        return json(route, { detail: `[WinError 3] 系统找不到指定的路径。: '${target}'` }, 404);
      }
      const existing = projectState.find((p) => p.path === target);
      if (existing) return json(route, projectView(existing)); // 幂等：同规范路径
      const created: ProjectFixture = {
        id: `p-${projectState.length + 1}`,
        path: target,
        title: body.title || target.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '项目',
        session_ids: [],
      };
      projectState.unshift(created); // 注册表顺序：新建项目前插
      return json(route, projectView(created));
    }
    const projectMatch = /^\/api\/projects\/([^/]+)$/.exec(path);
    if (projectMatch) {
      const project = findProject(decodeURIComponent(projectMatch[1]));
      if (!project) return json(route, { detail: '项目不存在' }, 404);
      if (req.method() === 'PATCH') {
        const body = (req.postDataJSON() ?? {}) as { title?: string };
        project.title = body.title ?? project.title;
        for (const id of project.session_ids) setWorkspace(id, project);
        return json(route, projectView(project));
      }
      if (req.method() === 'DELETE') {
        // 软删除：只摘注册记录与账本；成员会话的 workspace 清成 null（会话本体不动）。
        const detached = project.session_ids.length;
        for (const id of project.session_ids) setWorkspace(id, null);
        projectState.splice(projectState.indexOf(project), 1);
        return json(route, {
          id: project.id,
          deleted: true,
          sessions_detached: detached,
          detail: `项目「${project.title}」已从注册表移除，${detached} 个会话回到未分组。目录、用户文件与会话日志均未删除（软删除，可重新注册同一目录）。`,
        });
      }
      return json(route, { detail: 'method not allowed' }, 405);
    }
    const attachMatch = /^\/api\/projects\/([^/]+)\/sessions$/.exec(path);
    if (attachMatch && req.method() === 'POST') {
      if (mock.onAttachPost && (await mock.onAttachPost(route))) return;
      const project = findProject(decodeURIComponent(attachMatch[1]));
      if (!project) return json(route, { detail: '项目不存在' }, 404);
      const body = (req.postDataJSON() ?? {}) as { session_id?: string };
      const sessionId = body.session_id ?? '';
      if (!sessionState.some((s) => s['session_id'] === sessionId)) {
        return json(route, { detail: `会话不存在：${sessionId}` }, 404);
      }
      if (!project.session_ids.includes(sessionId)) {
        // **前插**：真实后端 `workspace/index.py` 的 attach_session 写的是
        // `[session_id, *kept]`（`tests/web/test_projects_api.py` 锁住了这个顺序）。
        // 这里推队尾会让 e2e 在真机后端下必然失败——mock 的语义必须跟账本一致。
        project.session_ids.unshift(sessionId); // attach 幂等：已在账本里就不动
        setWorkspace(sessionId, project);
      }
      return json(route, projectView(project));
    }
    const detachMatch = /^\/api\/projects\/([^/]+)\/sessions\/([^/]+)$/.exec(path);
    if (detachMatch && req.method() === 'DELETE') {
      const project = findProject(decodeURIComponent(detachMatch[1]));
      if (!project) return json(route, { detail: '项目不存在' }, 404);
      const sessionId = decodeURIComponent(detachMatch[2]);
      const at = project.session_ids.indexOf(sessionId);
      if (at >= 0) project.session_ids.splice(at, 1); // 不在本项目 → 幂等 no-op
      setWorkspace(sessionId, null);
      return json(route, projectView(project));
    }
    const orderMatch = /^\/api\/projects\/([^/]+)\/sessions\/([^/]+)\/order$/.exec(path);
    if (orderMatch && req.method() === 'POST') {
      const project = findProject(decodeURIComponent(orderMatch[1]));
      if (!project) return json(route, { detail: '项目不存在' }, 404);
      const sessionId = decodeURIComponent(orderMatch[2]);
      const body = (req.postDataJSON() ?? {}) as { before?: string | null };
      const before = body.before ?? null;
      const from = project.session_ids.indexOf(sessionId);
      if (from < 0) return json(route, { detail: '会话不在该项目账本里' }, 409);
      // 自锚点是**无操作**（`ProjectService.reorder` 显式挡下：DOM 意义上"把
      // 自己插到自己前面"什么都没变）。不先判它，下面的"先删后按 indexOf 插"
      // 会因为锚点已被删掉而 indexOf = -1 → 插到倒数第二位，凭空改掉账本。
      if (before === sessionId) return json(route, projectView(project));
      if (before !== null && !project.session_ids.includes(before)) {
        return json(route, { detail: '锚点不在该项目账本里' }, 409);
      }
      project.session_ids.splice(from, 1); // insertBefore 语义
      if (before === null) project.session_ids.push(sessionId);
      else project.session_ids.splice(project.session_ids.indexOf(before), 0, sessionId);
      return json(route, projectView(project));
    }

    // ── WS-7 / #170：宿主目录列举（`path` 缺省 = 根模式）──
    if (path === '/api/host/dirs') {
      const tree = mock.hostDirs;
      // 缺省 = 空的**根**列举（不是 404）：浏览器是新项目对话框的一部分，
      // 不关心它的 spec（r-project-groups）不该因此多出一条红色错误盒。
      // 错误矩阵由 `hostDirsErrors` / 假树里没有的路径显式构造。
      if (!tree) {
        return json(route, { path: null, parent: null, truncated: false, entries: [] });
      }
      const target = new URL(req.url()).searchParams.get('path');
      if (target !== null && mock.hostDirsErrors?.[target]) {
        const err = mock.hostDirsErrors[target];
        return json(route, { detail: err.detail }, err.status);
      }
      const cap = tree.maxEntries ?? 500;
      if (target === null) {
        // 根模式：path/parent 都是 null（前端据此禁用「向上」「选择此目录」）。
        const roots = [...(tree.roots ?? [])].sort(compareNames);
        return json(route, {
          path: null,
          parent: null,
          truncated: false,
          entries: roots.map((r) => ({ name: r, path: r })),
        });
      }
      const names = tree.tree[target];
      if (!names) return json(route, { detail: `目录不存在：${target}` }, 404);
      const shown = [...names].sort(compareNames).slice(0, cap);
      return json(route, {
        path: target,
        parent: parentPath(target),
        truncated: names.length > cap,
        entries: shown.map((name) => ({ name, path: joinPath(target, name) })),
      });
    }

    return route.fulfill({ status: 404, body: '{"detail":"not mocked in e2e"}', contentType: 'application/json' });
  });
}

/** 排序口径 = 后端 `host_dirs.py::_sorted`：name 大小写不敏感，同键按原名兜底。 */
function compareNames(a: string, b: string): number {
  const la = a.toLowerCase();
  const lb = b.toLowerCase();
  if (la !== lb) return la < lb ? -1 : 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** 子条目 path = 父路径 + 名字（**不**做 realpath 展开，ADR-0028 D3）。 */
function joinPath(base: string, name: string): string {
  const sep = base.includes('\\') ? '\\' : '/';
  return `${base.replace(/[\\/]+$/, '')}${sep}${name}`;
}

/** 上一级；盘根与无分隔符的路径没有上一级（后端 `parent in ("", canonical)` 同规则）。 */
function parentPath(target: string): string | null {
  const trimmed = target.replace(/[\\/]+$/, '');
  const at = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
  if (at < 0) return null;
  const sep = trimmed.includes('\\') ? '\\' : '/';
  let parent = trimmed.slice(0, at);
  if (parent.endsWith(':')) parent += sep; // 'D:' → 'D:\'（盘根照列）
  else if (parent === '') parent = sep; // '/home' → '/'
  return parent === trimmed ? null : parent;
}

/** 提交一个任务（Composer 填写 + 发送）。 */
export async function submitTask(page: Page, task: string): Promise<void> {
  await page.getByLabel('Agent 任务').fill(task);
  await page.getByLabel('发送').click();
}

// ── 控制目录 fixture（/api/models + 四个清单端点）──
// 多个 spec 共用同一份，避免各自复制后静默漂移（code-review：catalog drift）。

export const MODELS = [
  { name: 'deepseek-v4-flash-0731', provider: 'senseaudio', model: 'deepseek-v4-flash-0731', default: true },
  { name: 'qwen-max', provider: 'senseaudio', model: 'qwen3.8-max-0902', default: false },
  { name: 'claude-sonnet-4', provider: 'anthropic', model: 'claude-sonnet-4-20250514', default: false },
];

export const PERMISSION_MODES = [
  { id: 'auto', display_name: 'Auto Approve', description: '自动批准工具调用' },
  { id: 'ask', display_name: 'Ask Each Time', description: '每次工具调用都询问' },
  { id: 'deny', display_name: 'Deny All', description: '拒绝所有工具调用' },
];

export const AGENT_PROFILES = [
  { id: 'main', display_name: 'Main', description: '通用编排代理（默认）' },
  { id: 'coding', display_name: 'Coding', description: '代码编辑、调试和构建任务专用' },
  { id: 'research_review', display_name: 'Research & Review', description: '研究、检索和审查任务专用' },
];

export const REASONING_EFFORTS = [
  { id: 'minimal', display_name: 'Minimal', description: '最少推理开销；最快但最不彻底。' },
  { id: 'standard', display_name: 'Standard', description: '典型任务的平衡推理深度（默认）。' },
  { id: 'deep', display_name: 'Deep', description: '最多推理开销；较慢但最彻底。' },
];

export const CONTEXT_PROVIDERS = [
  { id: 'memory', display_name: 'Memory', description: 'Inject relevant recalled memories scoped to the user into the model context.' },
  { id: 'skills', display_name: 'Skills', description: 'Inject the catalog of available skills (name + description) into the model context.' },
];

/** 能力条目 fixture（形状 = 后端 `capability/manifest.py::manifest_entry`）。
 *
 *  `surfaces` **只写要断言的键**：省略的键前端按"未声明 → 保守取假"处理
 *  （与后端"未声明 surfaces 的 capability 只保证 chat/timeline"同方向）。
 *  传 `actions` 无意义（本批不消费），省略。 */
export function capabilityFixture(
  surfaces: Record<string, boolean>,
  id = 'coding',
): Record<string, unknown> {
  return {
    id,
    display_name: id,
    version: '1',
    provider_name: 'builtin',
    surfaces,
    actions: {},
  };
}

/** **core 条目**（后端恒发的那一条，#193）——`routeApi` 缺省 capabilities 用的就是它。
 *
 *  值必须与 `src/agent_harness/capability/manifest.py` 的 `CORE_SURFACES` /
 *  `CORE_ACTIONS` 一致：`changes`/`terminal` = true（内置工具产出的两个面）、
 *  `artifacts` = false（要部署配了 store 才读得到，不是无条件能力）、
 *  `retry` = false（后端没有该入口）。
 *
 *  漂移风险如实说明——**这是一份手工镜像，不是同源**：
 *  1. 后端改值 → 前端测试**不会**变红（这条链断在跨仓，本仓没有后端代码可读）；
 *  2. 只有"改这个 mock 且改错"才会红（`workspace-modes.spec.ts` 的"真实默认 → 三个面
 *     出现"＋`capabilities.test.ts` 的键集断言）。
 *  所以后端那一半必须由后端自己的测试锁（`tests/web/test_web_phase2_endpoints.py::
 *  TestCapabilities` 真走 HTTP 端点）。两侧一起改是唯一的同步手段；集成 AI 合并后请跑
 *  一次真实端点（`docs/ACCEPTANCE_LANE_ENV.md` §2）确认两侧同值。 */
export const CORE_CAPABILITY: Record<string, unknown> = {
  id: 'core',
  display_name: '内置工具',
  version: '1.0.0',
  provider_name: 'builtin',
  surfaces: {
    chat: true,
    timeline: true,
    changes: true,
    terminal: true,
    artifacts: false,
  },
  actions: { permissions: true, stop: true, retry: false, resume: true },
};

// ── 长目录 fixture（F-DEFER-1：搜索框显示阈值 >5 条）──
// 阈值速查（源码）：ModelPicker 用 `models.length + 1 > 5`（默认链算 1 条）；
// ControlPicker / ContextProviderPicker 用 `entries.length > 5`。
// 三处 spec 曾各自内联长目录 → 阈值/条数一改就静默漂移，故统一在此构造。

/** 造一个 id/display_name 结构的长目录（映射 ControlPicker / ContextProviderPicker 端点形状）。
 *
 * `highlight` 指定某一项的 display_name（供"键入过滤"类用例断言），默认 `前缀 N`。 */
export function longCatalog(prefix: string, n: number, highlight?: { index: number; label: string }) {
  return Array.from({ length: n }, (_, i) => ({
    id: `${prefix}-${i}`,
    display_name: highlight?.index === i ? highlight.label : `${prefix} ${i}`,
    description: `${prefix} 档位 ${i}`,
  }));
}

/** 长模型目录：MODELS（3）+ 2 条 = 5 条，+1 默认链 = 6 > 5 → 搜索框显示。 */
export const SEARCHABLE_MODELS = [
  ...MODELS,
  { name: 'gpt-5-mini', provider: 'openai', model: 'gpt-5-mini', default: false },
  { name: 'gemini-3-pro', provider: 'google', model: 'gemini-3-pro', default: false },
];

/** 长模型目录 PLUS：MODELS（3）+ 4 条 = 7 条，+1 = 8 > 5（更强的长目录信号，供可见性用例）。 */
export const LONG_MODELS = [
  ...SEARCHABLE_MODELS,
  { name: 'llama-5-70b', provider: 'meta', model: 'llama-5-70b', default: false },
  { name: 'mistral-large-3', provider: 'mistral', model: 'mistral-large-3', default: false },
];

// ── Composer 控制行交互 helper（跨 spec 共用）──

/** 键盘在 ControlPicker 里选第 N+1 项：打开 → ↓×N → Enter，断言 trigger 文本。
 *
 * F-DEFER-1（cmdk 焦点真相，2026-09-10 探针实测）：
 * - 「浮层已开」只看 `[role="listbox"]`（CommandList）。`role="combobox"`
 *   （CommandInput 本身）在短目录（≤5 条）时被 `.hidden` 的 wrap 包住，
 *   其 rect 为 0×0 → Playwright 判为不可见。
 * - **不要对搜索框调 fill()**：短目录下 rect 为 0，fill 会永久等待可交互
 *   状态直至超时；长目录下 aria-label 并不落在 input 上，
 *   `getByRole('combobox', { name })` 命中 0 个。
 * - 打开后焦点在 `DIV[role="dialog"]`（popover 容器），键盘事件需落到
 *   **listbox 自身**（`tabIndex=-1`，cmdk 在此承接方向键）才能驱动选中。
 *   故统一 `listbox.focus()`——长短目录同一路径，无分支。 */
export async function pickControl(
  page: Page,
  label: string,
  downPresses: number,
  expected: string,
): Promise<void> {
  const trigger = page.locator(`.composer-control[aria-label="${label}"]`);
  // `:visible` 限定当前打开的浮层：关闭动画期间上一层 listbox 仍是 DOM 节点，
  // 不加过滤会 strict mode violation（探针实测命中 2 个）。
  const listbox = page.locator('[role="listbox"]:visible').last();
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(listbox).toBeVisible();
  // 焦点落到 listbox（cmdk 的方向键承接者）；短目录搜索框 0×0，不能 fill。
  await listbox.focus();
  for (let i = 0; i < downPresses; i += 1) await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(trigger).toContainText(expected);
  await page.keyboard.press('Escape');
  // 退出动画期间 listbox 仍在 DOM 且可命中（与上方 `:visible` 注释同一成因）。
  // 不等它真正卸载，下一次 open 的 Enter 会撞在正在关闭的浮层上——表现为
  // 「浮层像是开了，选中却没生效」，且只在连续两次调用时复现（探针实测）。
  await expect(page.locator('[role="listbox"]')).toHaveCount(0);
}

/** 键盘在 ModelPicker 里选目录第一行（「默认链」之后第一项 = MODELS[0]），断言 trigger 文本。
 *
 * F-DEFER-1：同 pickControl——焦点显式落到 listbox，不碰 0×0 的搜索框。 */
export async function pickFirstModel(page: Page): Promise<void> {
  const trigger = page.locator('.composer-model[aria-label="模型选择"]');
  const listbox = page.locator('[role="listbox"]:visible').last();
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(listbox).toBeVisible();
  await listbox.focus();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(trigger).toContainText(MODELS[0].name);
  await page.keyboard.press('Escape');
}
