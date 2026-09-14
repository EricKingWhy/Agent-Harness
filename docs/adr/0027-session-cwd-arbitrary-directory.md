# ADR-0027 — 会话工作目录开放为任意已存在目录（`cwd` 字段）：项目内会话的落地

**Status**: Accepted
**Date**: 2026-09-12
**Related**: ADR-0025（Workspace 实体 / D8 演进路径——本 ADR **实现并扩展**其第 2 步）、
#151（started.data.cwd）、#152/#153/#154/#155（项目实体 / 列表 / CRUD / 前端分组）、
issue #169（本决策的 ticket，WS-6）、grill 访谈 2026-09-12（用户逐项拍板，见"Decision"）
**Supersedes**: ADR-0025 **D8 第 2 步的 `workspace_id` 白名单方案**（该方案只允许引用已注册项目；
用户 2026-09-12 拍板走到更远的"任意已存在绝对路径"）。**Refines**: ADR-0001 的沙箱路径边界语义
（见 Security：边界本来就是"软"的，本 ADR 把这一事实显式化）。

---

## Context

### 实测的功能断裂（2026-09-12 真机取证）

从 Web UI 创建的会话**永远进不了任何项目**，证据链：

1. 顶部「新建会话」创建的会话，工作目录是 `workspaces_root/<session_id>`（`SessionService.start`：
   `workspace_name` 为 None 时用 `session_id` 兜底）。
2. 项目归属判定 = 会话 cwd 与项目路径一致（ADR-0025 的双重校验）。
3. 对该新会话执行「加入项目…」→ 后端 409：`会话 '<id>' 的目录不属于项目 '<path>'`。

也就是说：**项目分组对纯 UI 用户不可用**——只有 CLI / e2e 用"单段 workspace 名"创建、且注册项目
路径恰好等于 `workspaces_root/<name>` 的会话才能归组。用户反馈的原话："这个项目文件夹没办法开启
一个新任务"。

### 根因：两条契约对不上

- **项目**（ADR-0025）= 任意**已存在**目录，按绝对路径注册。
- **会话工作目录**（`POST /api/sessions.workspace`）= `workspaces_root` 下**新建**的单段目录名
  （`_validate_workspace_name`：绝对路径 / 盘符 / 分隔符一律拒绝）。

### 事实修正（grill 前置调查，本 ADR 的论证基础）

**权限档从来不是路径围墙。** `WORKSPACE_WRITE` policy 是**工具级**授权闸
（`tooling/approval.py`：READ_ONLY 工具放行 / WORKSPACE_WRITE 工具放行 / DANGER 工具审批），
**不做任何写路径校验**。目录的实际作用只有两个：bash 的**起始 cwd**（`sandbox/local.py`：
`cwd=self._workspace_root`）与文件工具**相对路径**的解析基准。bash 命令内的绝对路径写、`cd ..`
从来都能越出该目录。因此"会话指向用户真实目录"改变的是 **agent 的默认操作位置**（从 Harness
创建的 scratch 目录变成用户目录），而不是打开一道此前紧闭的墙——把这一事实显式化，是本决策
成立的前提。

---

## Decision（grill 2026-09-12，用户逐项拍板）

**D1 — 契约形态（Q1=B）**：`POST /api/sessions` 新增 **`cwd`** 字段（字符串，可选）：
一个**已存在的绝对目录路径**。服务端行为：

1. 校验：绝对路径、存在、是目录（否则 422，detail 说明是哪条不满足）；
2. 规范化（realpath / `Path.resolve()`）后作为该会话的 workspace root；
3. **自动入组**（沿用 ADR-0025 D8 第 1 步的既有方向）：该规范路径注册进项目账本
   （不存在则 `create`，title 取目录末段名；幂等）+ 会话 attach 到它。即"在任意目录开任务"
   与"在项目里开任务"是**同一条机制**，目录会话天然出现在侧栏分组里。
4. `workspace`（单段名）与 `cwd` **互斥**：两者同时出现 → 422（detail 指明二选一）。
   都缺省 → 现行为不变（`workspaces_root/<session_id>`）。

**字段命名为什么是 `cwd` 而不是 ADR-0025 计划的 `workspace_id` / `workspace_path`**：
本代码库里 "workspace" 一词已被项目实体占用（`SessionSummary.workspace`、`POST /api/projects`
= workspace registry，见 ADR-0025 正名）；会话事件里目录的既定名字是 `started.data.cwd`（#151）。
请求字段与事件字段同名，零翻译。

**D2 — 默认权限档（Q2=C）**：目录会话**沿用现状默认** `workspace-write + auto-approve`
（与现有会话一致，权限档 UI 本就可按会话切换）；但**创建入口必须显式确认**：前端「在此目录新建
任务」的确认面必须明示 **"Agent 将直接读写该目录：<路径>"**，并把权限档选择器放在同一确认面里。
不做新的权限档、不发明新的默认值。

**D3 — 旧契约并存（Q3）**：`workspace`（单段名）语义原样保留（CLI / e2e-live / 既有脚本依赖），
不迁移、不废弃。三态：`workspace` 名字 / `cwd` 路径 / 都缺省。

**D4 — 存量会话不迁移（Q7）**：现存 `workspaces_root/<uuid>` 会话保持 Ungrouped，不提供
"无视 cwd 强制归组"的越权操作。

## Considered Alternatives

- **`project_id` 白名单**（只认已注册项目）：面最小，但用户明确拒绝——诉求就是"任意目录"，
  且"开任务前必须先注册项目"多一步仪式。作为将来可选收紧方向记录。
- **Windows junction 挂载**（`workspaces_root/<name>` → 真实目录的链接，绕过校验）：被
  `_validate_workspace_name` 的 `resolve().is_relative_to()` 正确拒绝；放宽它会把**所有**会话的
  越界防护一起拆掉。否决。
- **虚拟归属**（会话留在 scratch 目录，账本挂到项目名下）：用户原始诉求是"agent 在我的项目目录
  里干活"，虚拟归属落不了地。否决。

## Security

补偿约束（ADR-0025 D1 的三条 + 本 ADR 新增两条）：

1. 入口闸：两字段都过 `require_trusted_origin`（本地信任模式 = 仅本机来源；JWT 模式 = 认证后可用）。
2. `cwd` 只接受**已存在**目录；不存在 / 是文件 → 422，**不代创建**。
3. 规范化后再入账本（realpath），杜绝 `..` / 大小写 / 短路径名变体绕过比对。
4. **创建面显式确认**（D2）：UI 层的明示是产品级补偿，API 层不依赖它。
5. 权限档阶梯（含 DANGER 审批）原样生效；目录会话不改变任何工具的 permission 分类。

明确**不**新增的防护：写路径白名单 / 目录级 deny 清单。理由：policy 从来不做路径校验
（见 Context 事实修正），新增"路径检查"会造出"两种 workspace-write"两种语义；路径级
授权若将来需要，应作为独立的 PermissionPolicy 演进另立 ADR。

## Consequences

- `workspaces_root` 从"唯一根"变成"默认根"；`SessionSummary.workspace` / 项目账本从此可能
  包含 `workspaces_root` 之外的目录。UI 与 fork 的 copy-on-Fork 目录（ADR-0017）按同一
  realpath 语义处理即可，无需特判。
- `create_project` 与"带 cwd 建会话"共用同一个注册/attach 机制（幂等），两条入口不会造出
  两个项目条目。
- 会话 side effect（文件读写）从此可能落在用户真实目录：**产品文档与 UI 都必须明示**
  （D2）。这是本 ADR 不可拆分的部分。
- 兼容性：不传新字段的调用方（CLI、既有前端、e2e）行为逐字节不变。
