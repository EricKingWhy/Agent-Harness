/** api.ts 契约测试——getModels 窄化解析（T10 #103，契约 C6）+ 续聊 amend 透传（Q2）。
 *  fetch 全局 mock；auth.getToken 在 node 下走 try/catch 兜底（无 localStorage）。 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  attachSessionToProject,
  createProject,
  deleteMemory,
  deleteProject,
  archiveSession,
  deleteSession,
  describeMemoryError,
  describeSessionError,
  detachSessionFromProject,
  getHostDirs,
  getModels,
  getSessionEvents,
  isMemoryDisabled,
  listMemories,
  listProjects,
  listSessions,
  unarchiveSession,
  MemoryError,
  NotFoundError,
  ProjectError,
  SessionError,
  UnauthorizedError,
  AlreadyResolvedError,
  ApprovalGoneError,
  getArtifactContent,
  postApproval,
  renameProject,
  reorderProjectSession,
  sendMessage,
  startSession,
} from './api';
import { onUnauthorized } from './auth';
import type { MemorySummary, Project, SessionSummary } from '../types';

/** 捕获 fetch 调用（url + 已解析 body）并返回可配置响应——请求体契约断言用。 */
function captureFetch(
  status = 200,
  body: unknown = {},
): {
  calls: { url: string; body: Record<string, unknown> }[];
} {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url: String(url),
        body:
          typeof init?.body === 'string'
            ? (JSON.parse(init.body) as Record<string, unknown>)
            : {},
      });
      return new Response(JSON.stringify(body), { status });
    }),
  );
  return { calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getModels — 模型目录窄化解析（#103，零伪造）', () => {
  it('200 合法 body：提取条目，name 为选择键', async () => {
    captureFetch(200, {
      models: [
        { name: 'deepseek-v4-flash-0731', provider: 'senseaudio', model: 'deepseek-v4-flash-0731', default: true },
        { name: 'qwen-max', provider: 'senseaudio', model: 'qwen3.8-max-0902', default: false },
      ],
    });
    const models = await getModels();
    expect(models).toHaveLength(2);
    expect(models[0]).toEqual({ name: 'deepseek-v4-flash-0731', provider: 'senseaudio', model: 'deepseek-v4-flash-0731', default: true });
    expect(models[1].model).toBe('qwen3.8-max-0902');
  });

  it('畸形条目剔除（name 缺失/非对象），零伪造；可选字段缺失记 null', async () => {
    captureFetch(200, {
      models: [
        { name: 'ok-model' },
        { provider: 'x', model: 'y', default: true }, // 无 name → 剔除
        'garbage', // 非对象 → 剔除
        null,
      ],
    });
    const models = await getModels();
    expect(models).toEqual([{ name: 'ok-model', provider: null, model: null, default: false }]);
  });

  it('models 数组缺失/形状不符 → 空数组（入口降级隐藏，不伪造列表）', async () => {
    captureFetch(200, {});
    expect(await getModels()).toEqual([]);
    captureFetch(200, { models: 'not-an-array' });
    expect(await getModels()).toEqual([]);
  });

  it('非 2xx → 抛错（调用方降级隐藏入口）', async () => {
    captureFetch(500, {});
    await expect(getModels()).rejects.toThrow('models 500');
  });
});

describe('sendMessage — 续聊 amend 透传（Q2：有值才带键）', () => {
  it('四项 amend 全有值 → payload 带全部键（端点路径不变）', async () => {
    const cap = captureFetch();
    await sendMessage('s1', {
      content: '继续',
      max_steps: 10,
      model: 'glm-4.5',
      agent_profile: 'coding',
      reasoning_effort: 'deep',
      context_providers: ['memory', 'skills'],
    });
    expect(cap.calls).toHaveLength(1);
    expect(cap.calls[0].url).toBe('/api/sessions/s1/messages');
    expect(cap.calls[0].body).toEqual({
      content: '继续',
      mode: 'queue',
      max_steps: 10,
      model: 'glm-4.5',
      agent_profile: 'coding',
      reasoning_effort: 'deep',
      context_providers: ['memory', 'skills'],
    });
  });

  it('全空 → payload 不含任何 amend 键（缺省不传键，保持干净）', async () => {
    const cap = captureFetch();
    await sendMessage('s1', { content: '继续' });
    const body = cap.calls[0].body;
    expect(body).toEqual({ content: '继续', mode: 'queue', max_steps: 10 });
    for (const key of ['model', 'agent_profile', 'reasoning_effort', 'context_providers']) {
      expect(body).not.toHaveProperty(key);
    }
  });

  it('context_providers 空数组 → 不发键（与 create 分支同模式：空 = 后端默认全集）', async () => {
    const cap = captureFetch();
    await sendMessage('s1', { content: '继续', context_providers: [] });
    expect(cap.calls[0].body).not.toHaveProperty('context_providers');
  });

  it('部分有值 → 只带该键，其余不发', async () => {
    const cap = captureFetch();
    await sendMessage('s1', { content: '继续', model: 'glm-4.5' });
    const body = cap.calls[0].body;
    expect(body.model).toBe('glm-4.5');
    expect(body).not.toHaveProperty('agent_profile');
    expect(body).not.toHaveProperty('reasoning_effort');
    expect(body).not.toHaveProperty('context_providers');
  });

  it('显式 mode / max_steps 覆盖缺省值', async () => {
    const cap = captureFetch();
    await sendMessage('s1', { content: '继续', mode: 'steer', max_steps: 3 });
    expect(cap.calls[0].body).toMatchObject({ mode: 'steer', max_steps: 3 });
  });
});

describe('listSessions — SessionSummary 契约（ARCH-4b：trace_url / WS-3 #153：workspace）', () => {
  /** 后端 `GET /api/sessions` 一行的 canonical 形状，与
   *  `src/agent_harness/web/app.py::SessionSummary` 逐字段对齐。
   *
   *  两件事由**类型注解**在编译期锁住（无需运行时断言）：
   *  ① 类型新增必填字段 → 本 fixture 缺键 → `tsc -b` 红；
   *  ② fixture 多出类型没声明的键 → 对象字面量多余属性检查 → 红。
   *  后端侧权威锁（断言**值**，能抓住「键在但值是 null」的漏映射）：
   *  `tests/test_web_api.py::test_list_sessions_carries_terminal_trace_url`
   *  与 `tests/web/test_session_list_workspace.py::
   *  test_rows_carry_real_workspace_and_ungrouped_is_null`。
   */
  const CANONICAL_ROW: SessionSummary = {
    session_id: 's1',
    event_count: 6,
    first_event_time: '2026-09-07T00:00:00Z',
    last_event_time: '2026-09-07T00:00:00Z',
    first_user_message: '标题',
    trace_id: 'tr-1',
    trace_url: 'https://lf.example/trace/tr-1',
    workspace: { id: 'w1', title: '项目甲' },
    archived: false,
  };

  it('原样保留 trace_url（fetch 层不重排/不丢键/不重命名）', async () => {
    captureFetch(200, [CANONICAL_ROW]);
    const rows = await listSessions();
    expect(rows[0].trace_url).toBe('https://lf.example/trace/tr-1');
  });

  it('未追踪会话：trace_url 保持 null（不伪造占位串，不变量 #21）', async () => {
    captureFetch(200, [{ ...CANONICAL_ROW, trace_id: null, trace_url: null }]);
    const rows = await listSessions();
    expect(rows[0].trace_id).toBeNull();
    expect(rows[0].trace_url).toBeNull();
  });

  it('原样保留 workspace（嵌套对象不被 fetch 层拍平/改名）', async () => {
    captureFetch(200, [CANONICAL_ROW]);
    const rows = await listSessions();
    expect(rows[0].workspace).toEqual({ id: 'w1', title: '项目甲' });
  });

  it('未分组会话：workspace 保持 null（绝不伪造项目，不变量 #21）', async () => {
    captureFetch(200, [{ ...CANONICAL_ROW, workspace: null }]);
    const rows = await listSessions();
    expect(rows[0].workspace).toBeNull();
  });
});

describe('startSession — create 路径的有值才带（归一化单一执行点）', () => {  it('全空控制字段 → payload 只有 task + 显式传入的 max_steps/auto_approve', async () => {
    const cap = captureFetch();
    await startSession({ task: '干活', max_steps: 10, auto_approve: true });
    expect(cap.calls[0].url).toBe('/api/sessions');
    expect(cap.calls[0].body).toEqual({ task: '干活', max_steps: 10, auto_approve: true });
    for (const key of [
      'workspace',
      'model',
      'permission_mode',
      'agent_profile',
      'reasoning_effort',
      'context_providers',
    ]) {
      expect(cap.calls[0].body).not.toHaveProperty(key);
    }
  });

  it('context_providers 空数组 → 不发键（空 = 后端默认全集，不是显式零）', async () => {
    const cap = captureFetch();
    await startSession({ task: 't', context_providers: [] });
    expect(cap.calls[0].body).not.toHaveProperty('context_providers');
  });

  it('五项控制字段全有值 → 全部带键（含 permission_mode，create 路径独有）', async () => {
    const cap = captureFetch();
    await startSession({
      task: 't',
      model: 'glm-4.5',
      permission_mode: 'auto',
      agent_profile: 'coding',
      reasoning_effort: 'deep',
      context_providers: ['memory'],
    });
    expect(cap.calls[0].body).toMatchObject({
      model: 'glm-4.5',
      permission_mode: 'auto',
      agent_profile: 'coding',
      reasoning_effort: 'deep',
      context_providers: ['memory'],
    });
  });

  // ── WS-6 / #169：cwd 与「默认权限档不发键」的坑 ──

  it('cwd 有值 → 带键（目录根会话）；缺省 → 不发键（旧 workspace/default 语义不变）', async () => {
    const cap = captureFetch();
    await startSession({ task: 't', cwd: 'D:/repos/alpha' });
    expect(cap.calls[0].body.cwd).toBe('D:/repos/alpha');
    expect(cap.calls[0].body).not.toHaveProperty('workspace');

    await startSession({ task: 't' });
    expect(cap.calls[1].body).not.toHaveProperty('cwd');
  });

  it('「在此项目中新建任务」默认档：只发 cwd，**不发** permission_mode', async () => {
    // 后端语义：显式传了非 danger-full-access 的档 → 切交互式审批（每个工具调用
    // 都要人工批）。默认档必须靠"不发键"表达，否则这条路径会退化成"每步弹卡"。
    // 这条断言红了要改的是调用方（不要为了"显式"把默认档塞进 payload），不是这里。
    const cap = captureFetch();
    await startSession({ task: '读一下 README', cwd: 'D:/repos/alpha', max_steps: 10 });
    expect(cap.calls[0].body).toEqual({
      task: '读一下 README',
      cwd: 'D:/repos/alpha',
      max_steps: 10,
    });
    expect(cap.calls[0].body).not.toHaveProperty('permission_mode');
  });
});

describe('getHostDirs — WS-7 / #170 目录列举（ADR-0028）', () => {
  it('缺省 path → 请求不带查询串（列根）；有值时编码进查询串', async () => {
    const roots = captureFetch(200, { path: null, parent: null, truncated: false, entries: [] });
    await getHostDirs();
    expect(roots.calls[0].url).toBe('/api/host/dirs');

    const inDir = captureFetch(200, {
      path: 'D:\\repos',
      parent: 'D:\\',
      truncated: false,
      entries: [],
    });
    await getHostDirs('D:\\repos');
    expect(inDir.calls[0].url).toBe('/api/host/dirs?path=D%3A%5Crepos');
  });

  it('解析 path/parent/entries/truncated；path 为 null（根模式）原样保留', async () => {
    captureFetch(200, {
      path: 'D:\\data',
      parent: 'D:\\',
      truncated: true,
      entries: [
        { name: 'repos', path: 'D:\\data\\repos' },
        { name: 'bad' }, // 形状不符的单条丢弃，不牵连其余
      ],
    });
    await expect(getHostDirs('D:\\data')).resolves.toEqual({
      path: 'D:\\data',
      parent: 'D:\\',
      truncated: true,
      entries: [{ name: 'repos', path: 'D:\\data\\repos' }],
    });
  });

  it('403/404/422 → ProjectError 且 message = 后端 detail 原文（界面不翻译）', async () => {
    for (const [status, detail] of [
      [403, '无权限访问：D:\\secret'],
      [404, '目录不存在：D:\\nope'],
      [422, '不是目录：D:\\a-file.txt'],
    ] as const) {
      captureFetch(status, { detail });
      const err = await getHostDirs('D:\\x').catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ProjectError);
      expect((err as ProjectError).status).toBe(status);
      expect((err as Error).message).toBe(detail);
    }
  });
});

describe('getSessionEvents — 404 归类为 NotFoundError（BUG-005 陈旧会话自愈）', () => {
  it('404 → 抛 NotFoundError（调用方据此清持久化键 + 静默回空态，不弹错误）', async () => {
    captureFetch(404, { detail: 'session not found' });
    await expect(getSessionEvents('gone')).rejects.toBeInstanceOf(NotFoundError);
  });

  it('500 → 抛普通 Error（真正的故障仍要显示错误横幅，不能被当成「会话已删除」吞掉）', async () => {
    captureFetch(500, { detail: 'boom' });
    const err = await getSessionEvents('x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(NotFoundError);
  });

  it('200 → 原样返回事件数组', async () => {
    const events = [{ seq: 1, type: 'run/started' }];
    captureFetch(200, events);
    await expect(getSessionEvents('ok')).resolves.toEqual(events);
  });
});

/** auth_seam 的前端对侧（`lib/auth.ts` 文档：配了 JWT_SECRET 的部署匿名 → 401）。
 *  401 必须**同时**做两件事：分类成 UnauthorizedError（调用方据此走鉴权引导，
 *  而不是当成普通故障），并广播 detail（App 横幅据此显示）。两者此前都无单测；
 *  本组补齐——`e2e/l-auth-banner.spec.ts` 只覆盖广播之后的 UI，不覆盖这一层。 */
describe('401 → UnauthorizedError + onUnauthorized 广播', () => {
  it('401 → 抛 UnauthorizedError（既不是 NotFoundError，也不是普通 Error）', async () => {
    captureFetch(401, { detail: 'Missing identity token' });
    const err = await getSessionEvents('s').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UnauthorizedError);
    expect(err).not.toBeInstanceOf(NotFoundError);
  });

  it('401 → 广播后端 detail（App 订阅后据此显示引导横幅）', async () => {
    const seen: string[] = [];
    const off = onUnauthorized((d) => seen.push(d));
    captureFetch(401, { detail: 'Missing identity token' });
    await expect(getSessionEvents('s')).rejects.toBeInstanceOf(UnauthorizedError);
    off();
    expect(seen).toEqual(['Missing identity token']);
  });

  it('401 且 body 不是 JSON → 广播回退文案（readErrorDetail 失败不得吞掉广播）', async () => {
    const seen: string[] = [];
    const off = onUnauthorized((d) => seen.push(d));
    vi.stubGlobal('fetch', vi.fn(async () => new Response('not json', { status: 401 })));
    await expect(getSessionEvents('s')).rejects.toBeInstanceOf(UnauthorizedError);
    off();
    expect(seen).toEqual(['Missing identity token']);
  });
});

/** OBS-015：postApproval 必须区分幂等已决（409）与真失败（5xx/网络）。
 *  幂等 → AlreadyResolvedError（调用方翻卡片）；真失败 → 普通 Error（保持 pending）。 */
describe('postApproval — 409 幂等 vs 500 真失败（OBS-015）', () => {
  it('200 → 返回 resolved 结果', async () => {
    captureFetch(200, { status: 'resolved', approval_id: 'ap-1', decision: 'approve_once' });
    const result = await postApproval('s1', 'ap-1', true);
    expect(result).toEqual({ status: 'resolved', approval_id: 'ap-1', decision: 'approve_once' });
  });

  it('409 → 抛 AlreadyResolvedError（调用方据此翻卡片为幂等成功）', async () => {
    captureFetch(409, { detail: 'Approval already resolved' });
    const err = await postApproval('s1', 'ap-1', true).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AlreadyResolvedError);
  });

  it('500 → 抛普通 Error（不是 AlreadyResolvedError）', async () => {
    captureFetch(500, { detail: 'Internal Server Error' });
    const err = await postApproval('s1', 'ap-1', true).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(AlreadyResolvedError);
  });

  it('422 → 抛普通 Error（无效决策，不是幂等成功）', async () => {
    captureFetch(422, { detail: 'Invalid decision' });
    const err = await postApproval('s1', 'ap-1', true).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(AlreadyResolvedError);
  });
});

/** APR-01：404 = 后端审批队列里没有这条 approval_id（进程重启 / run 终结已 GC）。
 *  它不是可重试错误——重试多少次都是 404——所以必须与 5xx 分开归类，
 *  卡片据此转只读失效态而不是提示「重试」。
 *  也不复用 NotFoundError（同 deleteSession 的 404 取舍，见 api.test.ts:804）。 */
describe('postApproval — 404 失效审批（APR-01）', () => {
  it('404 → 抛 ApprovalGoneError，且**不是** NotFoundError（变异路径不复用加载语义）', async () => {
    captureFetch(404, { detail: 'approval_id 不存在（该审批已随运行结束失效）' });
    const err = await postApproval('s1', 'ap-gone', false).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApprovalGoneError);
    expect(err).not.toBeInstanceOf(NotFoundError);
    expect(err).not.toBeInstanceOf(AlreadyResolvedError);
  });

  it('404 的文案说「已失效」，不暗示重试', async () => {
    captureFetch(404, { detail: 'approval_id 不存在' });
    const err = await postApproval('s1', 'ap-gone', false).catch((e: unknown) => e);
    expect((err as Error).message).toContain('已失效');
    expect((err as Error).message).not.toContain('重试');
  });
});


// ── Projects（WS-4 / #154 契约，WS-5 / #155 前端消费）──

/** 项目端点用：记录 method + url + body，并可回一个带 detail 的错误体。
 *  （与顶部 captureFetch 的区别：那个不带 method，而本组要断言动词与子路径。） */
function captureProjectFetch(
  status = 200,
  body: unknown = {},
): { calls: { method: string; url: string; body: Record<string, unknown> }[] } {
  const calls: { method: string; url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        method: init?.method ?? 'GET',
        url: String(url),
        body:
          typeof init?.body === 'string'
            ? (JSON.parse(init.body) as Record<string, unknown>)
            : {},
      });
      return new Response(JSON.stringify(body), { status });
    }),
  );
  return { calls };
}

describe('projects — WS-4 端点契约（#154；窄化解析 + 状态码归类）', () => {
  /** 后端 `web/projects.py::Project` 的 canonical 形状。
   *  类型注解在编译期锁一致性（与 SessionSummary 同一手法）：后端加必填字段、
   *  或此处多出类型未声明的键 → `tsc -b` 红。 */
  const CANONICAL_PROJECT: Project = {
    id: 'p1',
    path: 'D:/repos/alpha',
    title: 'alpha',
    status: 'ok',
    session_ids: ['s1', 's2'],
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
  };

  it('listProjects：解析全部字段，账本序原样保留（前端不重排）', async () => {
    captureProjectFetch(200, [
      CANONICAL_PROJECT,
      { ...CANONICAL_PROJECT, id: 'p2', session_ids: [] },
    ]);
    const projects = await listProjects();
    expect(projects.map((p) => p.id)).toEqual(['p1', 'p2']);
    expect(projects[0].session_ids).toEqual(['s1', 's2']);
    expect(projects[0].path).toBe('D:/repos/alpha');
  });

  it('listProjects：畸形条目剔除、其余保留（一条坏数据不得让整列表消失）', async () => {
    captureProjectFetch(200, [
      { id: 'ok', path: 'D:/x', title: 'x', session_ids: ['s1'], status: 'ok' },
      { path: 'D:/no-id', title: 'no id' }, // 缺 id → 剔除
      { id: 'no-path', title: 'no path' }, // 缺 path → 剔除
      { id: 'no-title', path: 'D:/y' }, // 缺 title → 剔除
      'garbage',
      null,
    ]);
    const projects = await listProjects();
    expect(projects.map((p) => p.id)).toEqual(['ok']);
  });

  it('listProjects：session_ids 非字符串元素过滤；缺失 → 空账本', async () => {
    captureProjectFetch(200, [
      { id: 'p1', path: 'D:/x', title: 'x', session_ids: ['a', 7, null, '', 'b'] },
      { id: 'p2', path: 'D:/y', title: 'y' },
    ]);
    const projects = await listProjects();
    expect(projects[0].session_ids).toEqual(['a', 'b']);
    expect(projects[1].session_ids).toEqual([]);
  });

  it('listProjects：status 只认 missing-dir，未知值按 ok（告警标志不得整条丢项目）', async () => {
    captureProjectFetch(200, [
      { ...CANONICAL_PROJECT, id: 'miss', status: 'missing-dir' },
      { ...CANONICAL_PROJECT, id: 'weird', status: 'something-else' },
      { ...CANONICAL_PROJECT, id: 'absent' },
    ]);
    const projects = await listProjects();
    expect(projects.map((p) => p.status)).toEqual(['missing-dir', 'ok', 'ok']);
  });

  it('listProjects：顶层不是数组 → 空数组（降级为"没有项目"，会话仍全部可见）', async () => {
    captureProjectFetch(200, { projects: [] });
    expect(await listProjects()).toEqual([]);
  });

  it('createProject：只带 path（无标题）→ body 不含 title 键', async () => {
    const { calls } = captureProjectFetch(200, CANONICAL_PROJECT);
    await createProject('D:/repos/alpha');
    expect(calls[0].method).toBe('POST');
    expect(calls[0].url).toBe('/api/projects');
    expect(calls[0].body).toEqual({ path: 'D:/repos/alpha' });
  });

  it('createProject：带标题 → body 含 title；返回实体原样解析', async () => {
    const { calls } = captureProjectFetch(200, { ...CANONICAL_PROJECT, title: '自定义' });
    const p = await createProject('D:/repos/alpha', '自定义');
    expect(calls[0].body).toEqual({ path: 'D:/repos/alpha', title: '自定义' });
    expect(p.title).toBe('自定义');
  });

  it('createProject：路径不存在（404）→ ProjectError(404) 且带后端 detail', async () => {
    captureProjectFetch(404, { detail: '目录不存在' });
    const err = await createProject('D:/nope').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProjectError);
    expect((err as ProjectError).status).toBe(404);
    expect((err as ProjectError).message).toBe('目录不存在');
  });

  it('createProject：非绝对路径（422）→ ProjectError(422)，不被当成"路径不存在"', async () => {
    captureProjectFetch(422, { detail: 'path must be an absolute path' });
    const err = await createProject('relative/dir').catch((e: unknown) => e);
    expect((err as ProjectError).status).toBe(422);
    expect((err as ProjectError).message).toBe('path must be an absolute path');
  });

  it('createProject：Pydantic 422（detail 是数组）→ 取出 msg 并剥掉 "Value error, " 前缀', async () => {
    // 真后端对非绝对路径走的是**请求体校验器**，FastAPI 回的 detail 不是字符串而是
    // 数组。只认字符串会把最该看懂的一条提示降级成"注册项目失败（422）"。
    captureProjectFetch(422, {
      detail: [
        {
          type: 'value_error',
          loc: ['body', 'path'],
          msg: "Value error, path must be an absolute path: 'relative/dir'",
        },
      ],
    });
    const err = await createProject('relative/dir').catch((e: unknown) => e);
    expect((err as ProjectError).status).toBe(422);
    expect((err as ProjectError).message).toBe(
      "path must be an absolute path: 'relative/dir'",
    );
  });

  it('deleteProject：200 但 body 是 null → 不抛 TypeError，按"没给回执"处理', async () => {
    captureProjectFetch(200, null);
    const result = await deleteProject('p1');
    expect(result.id).toBe('p1');
    expect(result.deleted).toBe(false);
    expect(result.sessions_detached).toBe(0);
    expect(result.detail).toBe('');
  });

  it('renameProject：PATCH /api/projects/{id} + body.title', async () => {
    const { calls } = captureProjectFetch(200, { ...CANONICAL_PROJECT, title: '改名' });
    const p = await renameProject('p1', '改名');
    expect(calls[0].method).toBe('PATCH');
    expect(calls[0].url).toBe('/api/projects/p1');
    expect(calls[0].body).toEqual({ title: '改名' });
    expect(p.title).toBe('改名');
  });

  it('deleteProject：DELETE + 逐字保留后端 detail（AC5 的那句"会话没被删"）', async () => {
    const detail = '项目「甲」已从注册表移除，2 个会话回到未分组。目录、用户文件与会话日志均未删除（软删除，可重新注册同一目录）。';
    const { calls } = captureProjectFetch(200, {
      id: 'p1',
      deleted: true,
      sessions_detached: 2,
      detail,
    });
    const result = await deleteProject('p1');
    expect(calls[0].method).toBe('DELETE');
    expect(calls[0].url).toBe('/api/projects/p1');
    expect(result.sessions_detached).toBe(2);
    expect(result.detail).toBe(detail);
  });

  it('deleteProject：detail 缺失 → 空串（调用方据此跳过提示，不编文案）', async () => {
    captureProjectFetch(200, { id: 'p1', deleted: true });
    const result = await deleteProject('p1');
    expect(result.detail).toBe('');
    expect(result.sessions_detached).toBe(0);
  });

  it('attach：POST /api/projects/{id}/sessions，body.session_id', async () => {
    const { calls } = captureProjectFetch(200, CANONICAL_PROJECT);
    await attachSessionToProject('p1', 's9');
    expect(calls[0].method).toBe('POST');
    expect(calls[0].url).toBe('/api/projects/p1/sessions');
    expect(calls[0].body).toEqual({ session_id: 's9' });
  });

  it('attach：cwd 不一致（409）→ ProjectError(409)，与"不存在"（404）分开', async () => {
    captureProjectFetch(409, { detail: '会话 cwd 与项目路径不一致' });
    const err = await attachSessionToProject('p1', 's9').catch((e: unknown) => e);
    expect((err as ProjectError).status).toBe(409);
    expect((err as ProjectError).message).toBe('会话 cwd 与项目路径不一致');
  });

  it('detach：DELETE 子路径（id / session_id 都编码）', async () => {
    const { calls } = captureProjectFetch(200, CANONICAL_PROJECT);
    await detachSessionFromProject('p 1', 's/9');
    expect(calls[0].method).toBe('DELETE');
    expect(calls[0].url).toBe('/api/projects/p%201/sessions/s%2F9');
  });

  it('reorder：POST .../order，before=null（追加队尾）与具体锚点都原样透传', async () => {
    const { calls } = captureProjectFetch(200, CANONICAL_PROJECT);
    await reorderProjectSession('p1', 's2', null);
    expect(calls[0].method).toBe('POST');
    expect(calls[0].url).toBe('/api/projects/p1/sessions/s2/order');
    expect(calls[0].body).toEqual({ before: null });

    const second = captureProjectFetch(200, CANONICAL_PROJECT);
    await reorderProjectSession('p1', 's2', 's1');
    expect(second.calls[0].body).toEqual({ before: 's1' });
  });

  it('错误体不是 JSON / 无 detail → 兜底文案带状态码（错误路径自身不再抛错）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('<html>502</html>', { status: 502 })),
    );
    const err = await listProjects().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProjectError);
    expect((err as ProjectError).status).toBe(502);
    expect((err as ProjectError).message).toContain('502');
  });
});

// ── Memories（MEM-4 / #159 契约，MEM-5 / #160 前端消费）──

describe('memories — 列表/硬删端点契约（#160；ARCH-4b 类型注解 + 状态码语义）', () => {
  /** 后端 `web/memory.py::MemorySummary` 的 canonical 形状。
   *  类型注解在编译期锁一致性（与 SessionSummary / Project 同一手法）：后端加必填
   *  字段、或此处多出类型未声明的键 → `tsc -b` 红。后端侧权威锁在
   *  `tests/web/test_memory_api.py`（断言值，能抓住"键在但值是 null"的漏映射）。 */
  const CANONICAL_MEMORY: MemorySummary = {
    id: 'm-1',
    content: '用户偏好简洁的中文回答，不要客套话。',
    scope: 'user',
    metadata: { source: 'conversation' },
    created_at: '2026-09-12T08:30:00Z',
  };

  it('listMemories：全字段解析（content/scope/created_at 原样，不解析时间）', async () => {
    captureProjectFetch(200, [CANONICAL_MEMORY]);
    const rows = await listMemories();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual(CANONICAL_MEMORY);
    // 时间不做 Date 解析（展示层才格式化）：字符串原样带回。
    expect(rows[0].created_at).toBe('2026-09-12T08:30:00Z');
  });

  it('listMemories：limit/offset 进查询串（分页由后端执行，前端不本地切片）', async () => {
    const { calls } = captureProjectFetch(200, []);
    await listMemories(20, 40);
    expect(calls[0].method).toBe('GET');
    expect(calls[0].url).toBe('/api/memories?limit=20&offset=40');
  });

  it('listMemories：畸形单条剔除、其余保留（一条坏行不得让整页变"加载失败"）', async () => {
    captureProjectFetch(200, [
      CANONICAL_MEMORY,
      { ...CANONICAL_MEMORY, id: 'no-content', content: undefined }, // 缺 content
      { ...CANONICAL_MEMORY, id: 'no-time', created_at: null }, // 缺创建时间
      { ...CANONICAL_MEMORY, id: 'weird-scope', scope: 'global' }, // 未知 scope
      { ...CANONICAL_MEMORY, id: '' }, // 空 id
      'garbage',
      null,
    ]);
    const rows = await listMemories();
    expect(rows.map((r) => r.id)).toEqual(['m-1']);
  });

  it('listMemories：metadata 非对象 → 空对象兜底（列表仍可见，AC1 只消费三个字段）', async () => {
    // metadata 不是 AC1 的展示字段，形状异常不值得把整条记忆藏起来——但也不伪造内容。
    captureProjectFetch(200, [{ ...CANONICAL_MEMORY, metadata: 'not-an-object' }]);
    const rows = await listMemories();
    expect(rows[0].metadata).toEqual({});
    expect(rows[0].content).toBe(CANONICAL_MEMORY.content);
  });

  it('listMemories：顶层不是数组 → 空数组（调用方显示"还没有记忆"，不是错误）', async () => {
    captureProjectFetch(200, { memories: [] });
    expect(await listMemories()).toEqual([]);
  });

  it('listMemories：503（能力未装配）→ MemoryError(503) + 后端 detail；isMemoryDisabled 为真', async () => {
    const detail = 'memory capability 未启用：请在 CAPABILITIES 中配置 memory。';
    captureProjectFetch(503, { detail });
    const err = await listMemories().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(MemoryError);
    expect((err as MemoryError).status).toBe(503);
    expect((err as MemoryError).message).toBe(detail);
    // 降级通道判定：面板据此显示"记忆未启用"而非"加载失败 + 重试"。
    expect(isMemoryDisabled(err)).toBe(true);
  });

  it('listMemories：500 → MemoryError(500)，但**不是**降级态（真故障要可重试）', async () => {
    captureProjectFetch(500, { detail: 'boom' });
    const err = await listMemories().catch((e: unknown) => e);
    expect((err as MemoryError).status).toBe(500);
    expect(isMemoryDisabled(err)).toBe(false);
  });

  it('deleteMemory：DELETE /api/memories/{id}（id 编码）+ 200 回执', async () => {
    const { calls } = captureProjectFetch(200, { id: 'm/1', deleted: true });
    const result = await deleteMemory('m/1');
    expect(calls[0].method).toBe('DELETE');
    expect(calls[0].url).toBe('/api/memories/m%2F1');
    expect(result).toEqual({ id: 'm/1', deleted: true });
  });

  it('deleteMemory：200 但 body 是 null → deleted=false（不抛 TypeError，不谎称删掉了）', async () => {
    captureProjectFetch(200, null);
    const result = await deleteMemory('m-1');
    expect(result).toEqual({ id: 'm-1', deleted: false });
  });

  it('deleteMemory：404（id 不存在）→ MemoryError(404)，不当成功', async () => {
    // detail 用真后端的原文（`MemoryNotFound` → `记忆不存在：<id>`）。
    captureProjectFetch(404, { detail: '记忆不存在：m-1' });
    const err = await deleteMemory('m-1').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(MemoryError);
    expect((err as MemoryError).status).toBe(404);
    expect((err as MemoryError).message).toBe('记忆不存在：m-1');
  });

  it('deleteMemory：403（不属于当前入口，含 SESSION 行）→ MemoryError(403)，与 404 分开', async () => {
    // detail 用真后端的原文（`PermissionError` → 英文原句，`str(exc)` 直通）。
    captureProjectFetch(403, { detail: 'Memory belongs to a different namespace' });
    const err = await deleteMemory('m-1').catch((e: unknown) => e);
    expect((err as MemoryError).status).toBe(403);
    expect((err as MemoryError).message).toBe('Memory belongs to a different namespace');
  });

  it('describeMemoryError：MemoryError 用后端 detail；非 MemoryError 用 message / fallback', () => {
    expect(describeMemoryError(new MemoryError(403, '不给删'), '删除记忆失败')).toBe('不给删');
    expect(describeMemoryError(new Error('网络断了'), '删除记忆失败')).toBe('网络断了');
    expect(describeMemoryError(new Error(''), '删除记忆失败')).toBe('删除记忆失败');
    expect(describeMemoryError(null, '删除记忆失败')).toBe('删除记忆失败');
  });
});

describe('deleteSession — 会话硬删端点契约（#172 / ADR-0029；状态码语义 + 回执窄化）', () => {
  it('200：DELETE /api/sessions/{id}，回执两个计数原样透传（前端不自己数）', async () => {
    const { calls } = captureProjectFetch(200, {
      id: 's-1',
      deleted: true,
      events: 42,
      detached_from_projects: 1,
    });
    const result = await deleteSession('s-1');
    expect(calls[0].method).toBe('DELETE');
    expect(calls[0].url).toBe('/api/sessions/s-1');
    expect(result).toEqual({
      id: 's-1',
      deleted: true,
      events: 42,
      detached_from_projects: 1,
    });
  });

  it('id 走 encodeURIComponent（路径参数不是字符串拼接）', async () => {
    const { calls } = captureProjectFetch(200, { id: 'a b/c', deleted: true, events: 1, detached_from_projects: 0 });
    await deleteSession('a b/c');
    expect(calls[0].url).toBe('/api/sessions/a%20b%2Fc');
  });

  it('200 但 body 是 null → deleted 仍为 true、计数归 0（不抛 TypeError，也不谎报"没删"）', async () => {
    captureProjectFetch(200, null);
    const result = await deleteSession('s-1');
    // 与 deleteProject 的 null body（deleted:false）**刻意不同**：那边 200 只是"软删
    // 回执没给"，这边 200 就是东西没了（后端 schema `Literal[True]`）——报 false 会把
    // "已经删掉了"说成"没删成"，比少两个计数严重得多。
    expect(result.deleted).toBe(true);
    expect(result.id).toBe('s-1');
    expect(result.events).toBe(0);
    expect(result.detached_from_projects).toBe(0);
  });

  it('409 的三种原因（在途 run / 挂起审批 / fork 父会话）→ SessionError(409) + detail 原文', async () => {
    // 三种原因**状态码相同**，只有 detail 能区分——所以逐条用真后端的原句
    // （`session/service.py::delete_session` 的 f-string）锁"原样透传、不编文案"。
    const details = [
      "session 's-1' has a run in flight; cancel it first",
      "session 's-1' has a pending approval; resolve it first",
      "session 's-1' is the fork parent of 2 session(s): delete the child session(s) first",
    ];
    for (const detail of details) {
      captureProjectFetch(409, { detail });
      const err = await deleteSession('s-1').catch((e: unknown) => e);
      expect(err).toBeInstanceOf(SessionError);
      expect((err as SessionError).status).toBe(409);
      // fork 那条自带的子会话数量（2）必须还在——前端盖掉就是把它说糊了。
      expect((err as SessionError).message).toBe(detail);
    }
  });

  it('404（第二次删除）→ SessionError(404)，**不是** NotFoundError（调用方要按状态码收敛）', async () => {
    captureProjectFetch(404, { detail: "session 's-1' not found" });
    const err = await deleteSession('s-1').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(SessionError);
    expect((err as SessionError).status).toBe(404);
    expect((err as SessionError).message).toBe("session 's-1' not found");
    // 复用 NotFoundError 会让"用户想删的东西本就不在了"与"加载路径拿不到内容"
    // 混成一个信号（且它不带状态码，调用方没法只对 404 收敛）。
    expect(err).not.toBeInstanceOf(NotFoundError);
  });

  it('detail 缺失 → 兜底文案带状态码（不留一句没有下文的"删除会话失败"）', async () => {
    captureProjectFetch(502, {});
    const err = await deleteSession('s-1').catch((e: unknown) => e);
    expect((err as SessionError).status).toBe(502);
    expect((err as SessionError).message).toContain('502');
    expect((err as SessionError).message).toContain('删除会话失败');
  });

  it('describeSessionError：SessionError 用后端 detail；非 SessionError 用 message / fallback', () => {
    expect(describeSessionError(new SessionError(409, '有在途 run'), '删除会话失败')).toBe('有在途 run');
    expect(describeSessionError(new Error('网络断了'), '删除会话失败')).toBe('网络断了');
    expect(describeSessionError(new Error(''), '删除会话失败')).toBe('删除会话失败');
    expect(describeSessionError(null, '删除会话失败')).toBe('删除会话失败');
  });
});

describe('getArtifactContent — artifact 切片解析（#185/#186，缺字段必须报错而不是编）', () => {
  it('200 合法 body：逐字段解析，行内截断标记如实带上', async () => {
    captureFetch(200, {
      artifact_id: 'a1b2c3d4e5f60718',
      lines: [
        { line_number: 1, text: 'hello' },
        { line_number: 2, text: 'xxxx', truncated: true, full_length: 9000 },
      ],
      total_lines: 40,
      returned_lines: 2,
      truncated: true,
      query: { keyword: null, max_lines: 200 },
    });
    const slice = await getArtifactContent('s-1', 'a1b2c3d4e5f60718');
    expect(slice.total_lines).toBe(40);
    expect(slice.returned_lines).toBe(2);
    expect(slice.truncated).toBe(true);
    expect(slice.lines[1]).toEqual({ line_number: 2, text: 'xxxx', truncated: true, full_length: 9000 });
    // 行内不超长的行**不**带 truncated/full_length（缺失即不编）
    expect(slice.lines[0]).toEqual({ line_number: 1, text: 'hello' });
  });

  it('缺 total_lines / returned_lines → 抛错（此前静默填 0，界面会显示"共 0 行"的假空产物）', async () => {
    captureFetch(200, { artifact_id: 'a1b2c3d4e5f60718', lines: [] });
    await expect(getArtifactContent('s-1', 'a1b2c3d4e5f60718')).rejects.toThrow('响应形状不符');
  });

  it('缺 artifact_id 或 lines → 抛错（形状不符不走"空内容"）', async () => {
    captureFetch(200, { lines: [], total_lines: 0, returned_lines: 0 });
    await expect(getArtifactContent('s-1', 'a1b2c3d4e5f60718')).rejects.toThrow('响应形状不符');
    captureFetch(200, { artifact_id: 'a1b2c3d4e5f60718', total_lines: 0, returned_lines: 0 });
    await expect(getArtifactContent('s-1', 'a1b2c3d4e5f60718')).rejects.toThrow('响应形状不符');
  });
});

describe('会话归档（#171）—— 请求形状与错误文案', () => {
  /* 三条口径：
  1. 默认**不带** `include_archived`（后端默认 false 才是权威过滤；前端显式要求 true
     是另一个决定，见 `listSessions` 的注释）；
  2. 归档/取消归档的动词分开（POST / DELETE 同一路径），回执 `{id, archived}` 原样透传；
  3. 409 的 detail 是三种原因里**唯一可区分**的东西，必须原样上抛——编文案会把
     "运行中的会话不能归档"说成一个泛泛的失败。 */

  it('listSessions 默认不带 include_archived；显式 true 时带 ?include_archived=true', async () => {
    const { calls } = captureFetch(200, []);
    await listSessions();
    expect(calls[0].url).toBe('/api/sessions');

    const second = captureFetch(200, []);
    await listSessions({ includeArchived: true });
    expect(second.calls[0].url).toBe('/api/sessions?include_archived=true');
  });

  it('archiveSession → POST /api/sessions/{id}/archive，回执 archived:true', async () => {
    const { calls } = captureProjectFetch(200, { id: 's/1', archived: true });
    const result = await archiveSession('s/1');

    expect(calls[0].url).toBe('/api/sessions/s%2F1/archive');
    // 动词是契约的一部分，不是风格：后端**只在归档方向**挡 409 在途 run
    // （`service.py::set_archived` 的守卫是 `archived and get_active(...)`），
    // 所以"哪个动词走哪条路"必须被断言，而不是靠"两个函数名不同"推出来。
    expect(calls[0].method).toBe('POST');
    expect(result).toEqual({ id: 's/1', archived: true });
  });

  it('unarchiveSession → DELETE 同一路径，回执 archived:false', async () => {
    const { calls } = captureProjectFetch(200, { id: 's1', archived: false });
    const result = await unarchiveSession('s1');

    expect(calls[0].url).toBe('/api/sessions/s1/archive');
    expect(calls[0].method).toBe('DELETE');
    expect(result).toEqual({ id: 's1', archived: false });
  });

  it('回执的 archived 是权威：与请求意图相反时照抄回执，不"纠正"成意图', async () => {
    // 幂等重放 / 并发下后端可能回一个与请求方向不同的真值（别人已经归档过了）。
    // 这里锁的是「回执说了算」——前端若拿请求意图覆盖它，界面就会显示一个假状态。
    captureProjectFetch(200, { id: 's1', archived: false });
    await expect(archiveSession('s1')).resolves.toEqual({ id: 's1', archived: false });
  });

  it('回执缺 archived 布尔 → 抛（不拿请求意图补），并带上诊断信息', async () => {
    // "200 但形状不对"必须说话：用请求意图填进去会把"后端没确认"伪装成"确认了"。
    captureProjectFetch(200, { id: 's1' });
    await expect(archiveSession('s1')).rejects.toThrow(/归档回执缺少 archived 布尔/);
    await expect(archiveSession('s1')).rejects.toThrow('请求意图 true');
  });

  it('409（运行中）→ 抛 SessionError，message 是后端 detail 原文', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: '运行中的会话不能归档' }), { status: 409 }),
      ),
    );
    await expect(archiveSession('s1')).rejects.toThrow('运行中的会话不能归档');
    expect(describeSessionError(new Error('x'), '归档失败')).toBe('x');
  });
});
