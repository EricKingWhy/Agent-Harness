# ADR-0025 — Workspace 实体：任意已存在目录的显式授权 + 有序账本 + 意图日志原子性

**Status**: Accepted
**Date**: 2026-09-12
**Related**: ticket #152（WS-2）、#151（WS-1 会话侧 cwd 锚）、#153/#154/#155（列表 / CRUD / 前端）、
`docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md` §2.3（DSH 是唯一显式建模
"项目—会话"的上游）、ADR-0001（沙箱路径边界）、ADR-0004（harness.db 布局）、ADR-0017（fork 的
copy-on-fork 目录）
**Supersedes**: 无。**Refines**: ADR-0001 的**路径校验层**——沙箱边界本身（工具只能在
workspace root 内活动）不变，变的是"workspace root 从哪来、谁授权"；以及
`web/app.py:_validate_workspace_name` 所代表的"单段名 + 强制落在 `workspaces_root` 内"契约
（下文 D8 给出演进路径，实施在 #154）。

---

## Context

### 今天的模型：名字，不是路径

`POST /api/sessions` 接受 `workspace: str | None`，服务端把它当**单个目录名**校验
（`session/service.py:_validate_workspace_name`：禁空白 / `.` / `..` / 盘符 / 绝对路径 / 任何
分隔符，并要求解析后仍 `is_relative_to(workspaces_root)`），再拼成
`workspaces_root/<name>`。所以用户能"选"的目录只有 `workspaces_root` 下面一层，而且必须
用名字引用。同一份规则在 `web/app.py` 里还有一份**无人调用的副本**（死代码）。

### 用户决策：改成 DSH 模型（任意已存在目录）

DSH 注册的是**任意已存在目录**的 `realpath`。用户 2026-09-11 拍板采用该模型。这直接
推翻了"必须落在 `workspaces_root` 内"这条约束，因此**必须重新论证安全边界**：一条
`is_relative_to` 检查被拿掉之后，凭什么说这不再是路径穿越？

### 缺的东西（本票要补）

- 没有 Workspace 实体、没有"某个项目下有哪些会话"的索引（`sandbox/registry.py` 的
  `WorkspaceRegistry` 是**会话→沙箱目录**映射，只有 `create/get/exists/stop/delete`，无枚举，
  且以 `session_id` 为键——要按项目列会话只能全量扫盘）。
- `session/started` 直到 #151 才有 cwd；成员资格的双重校验（账本 + header cwd）此前无从谈起。

---

## Decision

### D1 — 授权模型：**任意已存在目录 + 显式授权**，边界从"路径前缀"换成"用户动作 + 注册记录"

**允许什么**：`create(path)` 接受任意**已存在**的目录（`realpath` 规范化后）。不存在 /
不是目录 → 原样传出 `ENOENT` / 非目录错误（不创建目录、不猜测）。

**为什么这不是路径穿越**：路径穿越的前提是"输入由不受信方提供，而校验方本可拦住"。这里的
输入来自**本地单用户的操作界面**（"用我自己的项目"），用户对自己的磁盘目录本来就有读写权限；
把 `D:\code\myproj` 注册成项目**不会**让任何人获得他原本没有的权限。真正的边界仍然在**运行时**：

| 仍然是边界 | 在哪 | 本票是否改动 |
| --- | --- | --- |
| 工具只能在其 workspace root 内活动 | `LocalSubprocessSandbox` / `DockerSandbox`（ADR-0001） | **否** |
| 沙箱后端与容器边界 | `sandbox/backend` | **否** |
| 权限 / 审批阈值 | `ToolExecutor` + `PermissionPolicy`（不变量 #11：Prompt 不能替代 Runtime 权限） | **否** |
| 哪个目录算"项目" | **本注册记录**（id + 规范 path），由用户显式动作产生 | **是（本 ADR）** |

三条硬约束补偿被拿掉的路径前缀检查：

1. **必须已存在**：不创建目录 → 不能借"注册"在生产磁盘上造出任意路径。
2. **规范路径唯一 + 稳定 id**：同一物理目录只能有一个 workspace；引用锚是 uuid 而不是路径
   （路径可被规范化/移动，uuid 不会），所以"改一个路径字符串就换一个项目"做不到。
3. **删除是软删除**：`delete(id)` 只摘掉注册记录与会话账本，**目录、用户文件、实时会话、
   已落盘日志一概不动**（AC11）→ 注册动作不可逆地破坏用户数据的能力被限制在"索引"这一层，
   而索引可由会话 header 重建（D3）。

**明确不做**：不做上传 / 导入（zip / git clone）、不做目录浏览器端点（非目标）。前端最小
形态是让用户**输入绝对路径**。

**这条论证依赖的前提（必须显式写下来）**：输入来自**受信的本地单用户界面**。当前默认部署
并不强制这一点——`AuthSeamMiddleware` 只在配置了 `jwt_secret` 时才 fail-closed，未配置时
匿名请求被当作受信的 `local`，且 CORS 是 `allow_origins=["*"]`（`web/app.py`）。也就是说，
在"本地信任模式 + CORS 全开"的组合下，任意网页都能调用 agent API（代码注释本身也这么写）。
本票**没有新增任何 HTTP 端点**，所以这个组合还没有被放大；但 #154 会把 `create(path)` 暴露成
`POST /api/projects`，届时**必须**满足下列之一：(a) 要求配置 `jwt_secret` 并对该端点做鉴权；
(b) 加同源/CSRF 防护；(c) 在部署上明确限定 localhost-only 且把该假设写成部署约束。
在那之前，"用户明确授权"这句话只在上述前提成立时才严格成立。

**WS-4 (#154) 的落实（D1 补充，2026-09-12）**：选了 **(b) 同源/CSRF 防护**，实现为
`web/projects.py::require_trusted_origin` —— 挂在**所有项目端点（读 + 写，9 条全挂）**上的
FastAPI 依赖。最初只挂写端点，review 指出**读端点也漏信息**（项目列表/详情里全是用户的
绝对路径，CORS `*` 下"能被读"就等于"能被任意网页枚举"），已改成全挂：

- 未配置 `jwt_secret`（本地信任模式）时，**带 `Origin` 且 hostname 不是本机**
  （`localhost` / `127.0.0.1` / `::1`）→ **403**，请求不落任何盘；`Origin: null`
  （sandboxed iframe / `file://`）没有 hostname → 同样 403；
- **无 `Origin`** 的请求放行：非浏览器发起（CLI / curl / 服务端）无法被第三方网页驱动，
  这是 Origin 校验的标准边界；
- 配置了 `jwt_secret` 时整体跳过：这时请求已过 `AuthSeamMiddleware`（fail-closed），
  跨源网页拿不到签名 token，认证层才是边界。

为什么不做 (a)：本地单用户默认不配密钥，要求配置密钥等于把默认部署变成"用不了"；为什么
不做 (c)：绑定 localhost **挡不住浏览器**（恶意网页的请求就是从用户的浏览器发往
127.0.0.1 的），它只是把假设写下来，而 (b) 直接掐掉那个向量。

**`path` 收的是绝对路径（新增校验）**：`web/projects.py::_require_absolute_path` 在
`canonical_workspace_path` **之前**拒绝空白 / `.` / `..` / 相对写法 / NUL。理由：
`realpath("")`、`realpath(".")` 返回**进程当前工作目录**、`realpath("..")` 返回**盘根**——
放行就等于让"注册我的项目"变成"把服务器碰巧启动的目录、甚至整块盘当成项目"（WS-1 已就
`realpath("")` 记过同一类静默锚定）。**盘根/家目录本身不额外拒绝**：它们确实是"已存在的
目录"（AC2 的字面要求），注册它们是用户的显式动作，且本票的 `DELETE` 是**软删除**
（不触碰 `WorkspaceRegistry.delete` 的 `rmtree` 路径），所以不构成新的破坏面；但沙箱根会
随之变成整块盘，这是用户可见的选择（UI 显示 path），不是提权。

**残留下来、本票未修（重要）**：这个闸只保护**本票新增的项目端点**。
`allow_origins=["*"]` 让**既有**端点（含 `POST /api/sessions` → 能起 agent 跑工具）
在今天就能被任意网页调用——那是 #154 之前就存在的洞，范围远超本票（`AGENTS.md §8`：
范围外只报告不顺手修）。要真正关掉它，正确做法是把 CORS 收紧到本机 origin（或默认
`jwt_secret` fail-closed），**这是独立的一张票**。

**放行 no-Origin 的前提（部署约束，必须写下来）**：Origin 校验只挡浏览器。若服务绑到
`0.0.0.0` 且未配 `jwt_secret`，任何能直连该端口的网络客户端都可以不带 `Origin` 调用项目
写端点。因此**本票的默认部署前提是"服务只绑 loopback"**（`dev.sh` / 验收文档都是
127.0.0.1）；对外暴露必须配 `jwt_secret`（走 (a) 的认证层）。

**一个被这次改动放大的既有能力（记录，不在本票修）**：`LocalSubprocessSandbox.delete` /
`WorkspaceRegistry.delete` 会 `shutil.rmtree(workspace_root)`。原来 root 必然是
`workspaces_root` 下的一层，所以 rmtree 的范围有界；换成"任意已存在目录"之后，如果这个
方法被接到用户目录上，就会删真实项目。它今天**没有生产调用方**（只有
`tests/sandbox/test_workspace_registry.py`），而 #154 明确不做会话硬删除；此处记录该后果，
#154 若要暴露任何 delete 语义必须先处理它。

### D2 — 身份：`id` 是 uuid，`path` 是规范路径且写入后不可改写

- `id`：生成的 uuid。**不是路径**——路径规范化会改写路径，引用锚必须稳定。
- `path`：`canonical_workspace_path`（`fs.realpath` 语义，与 WS-1 同一套规范化，AC5 同源）。
  **唯一性 = 规范路径字符串逐字符相等**（符号链接指向已被拥有的目录 → 冲突，幂等返回既有实体）。
  存储后**再不改写**；目录被移走/删除也**不改写**记录（AC2/AC8），只把
  `status()` 报成 `'missing-dir'`。
- `title`：显示名，缺省取末段路径（无末段用根路径拼写），**允许重名**，`setTitle` 持久化。
- `sessionIds`：**有序、手工拥有**——新会话 attach 时**前插**；显式
  `insertSessionBefore(sessionId, before?)` 重排（DOM insertBefore 语义：无 anchor 则追加尾部）；
  **活动时间永不重排**（AC5）。顺序用整数 position 表示，重排时对该 workspace 的账本整体重编号
  （列表天然很小；显式重排是低频用户动作）。

### D3 — 账本是**索引**，不是第二真相源（不变量 #22）

成员资格 = **账本里有该 id 且会话 header 的规范 cwd 等于 `workspace.path`**（AC6，
依赖 WS-1）。过滤是**同步**的：缺 header、cwd 非法、cwd 不匹配的候选**永不返回**；
下一次被接受的变更**持久修剪**这些候选。

账本因此是可重建的：会话 header 是真相，账本是查询加速 + 用户手工排序的表达。这保证
"索引损坏 ≠ 数据损坏"，也保证 bootstrap（D6）语义成立。

### D4 — 持久化：`harness.db` 的 5 张表 + 内存缓存（读同步 / 写异步）

作为 `RecoveryStores` 的第 4 个成员（同一 `harness.db`，ADR-0004 布局），模块放在新的
`src/agent_harness/workspace/` 包内（**与 `sandbox.WorkspaceRegistry` 同名不同物**，见 D7）：

```sql
workspaces(workspace_id PK, path UNIQUE, title, created_at, updated_at)
workspace_order(position PK, workspace_id UNIQUE)      -- 注册表顺序（新→旧）
workspace_sessions(workspace_id, session_id, position, PK(workspace_id, session_id))
workspace_changes(change_id PK, kind, workspace_id, ...)  -- 待定变更标记（D5）
workspace_meta(key PK, value)                          -- 例如 bootstrap 完成标记
```

连接纪律照 `knowledge/registry.py` / `memory/sqlite_record_store.py`：每操作新连接 +
`PRAGMA journal_mode=WAL`（initialize 一次）+ `busy_timeout=10_000`，写用 `BEGIN IMMEDIATE`。
**记录表走内存缓存**（AC10 "同步缓存读"）：`initialize()` 后全量载入 `workspaces` /
`workspace_order` / `workspace_sessions`，此后 `get` / `list` / `resolve_by_path` /
`workspace_of_session` 都是同步读、不 `await`。

**准确边界（避免过度宣称）**：缓存的是**记录与账本**，不是 `session_ids` 本身。
`session_ids` 每次都由 `_filter_visible` 按 AC6 重新校验——要读账本里每个会话的 header
（JSONL 首行），所以"某个项目的会话列表"是 O(账本长度) 次 header 读，而不是零磁盘。
`resolve_by_path` 每次做一次 `realpath`（`os.path.realpath`，跟随链接的 syscall），但**不**
枚举目录、不做全库扫描。列表页因此不再需要"全量扫 session root 逐个分组"，这是本票真正省掉
的开销。

### D4b — 写串行化：一把进程内的 `asyncio.Lock`（正确性前提，不是保险）

`create` / `attach_session` 等写方法都是"读缓存 → 判断 → 写库 → 改缓存"的复合操作，中间有
`await`。HTTP 端点在**同一个进程**里并发进入（双击提交、两个标签页用同一个 workspace 名），
而 `instance_lock.py` 只保证**跨进程**互斥。交错时的两种真实后果：

- 两个同路径 `create` 都认为"路径尚未被拥有" → 第二条记录把第一条整行换成新 id，却留着
  第一条在 `workspace_order` 里的行 → **悬空顺序行**，下次启动按 AC13 大声失败而拒绝启动；
- 两个 `attach_session` 各自基于同一份旧账本写库 → 其中一个会话从索引里**静默消失**。

所以 `WorkspaceIndex` 持有一把 `asyncio.Lock`，所有写方法（含 `initialize` /
`resolve_pending_change` / `bootstrap`）在锁下执行；`initialize` 通过 `*_locked` 内部实现
调用后两者以避免自锁。读方法**不加锁**：它们同步读缓存，而写方法一律"先提交数据库、再改
内存缓存"，所以读要么看到旧值要么看到新值，不会看到半个状态。

配套地，`write_record` 用**纯 `INSERT`** 而非 `INSERT OR REPLACE`：路径有唯一约束，正常路径
上调用方已在锁内确认"该路径尚未被拥有"；若仍撞上冲突，说明有另一份写者，此时静默替换别人
的记录比响亮报错危险得多。

### D5 — 原子性：**意图日志（待定变更标记）**，启动时恰好解决一个

`create` / `delete` 各有两次写入（**记录**与**顺序**）。两者之间崩溃会留下分叉，所以：

1. **先**持久写一条 `workspace_changes`（`kind='create'|'delete'`）；
2. 写**记录**；
3. 写**顺序**，并在**同一个事务里删掉标记**。

（3）与（2）同事务是关键：这样"标记仍在"⇔"变更未完成"，否则会出现"变更已完成但标记还在"
→ 回滚一个已完成的 create，把用户刚建的项目删掉。

启动时 `resolve_pending_change()`：
- **0 条标记** → 无需处理；
- **1 条 `delete`** → **补完**：确保记录行与顺序行都不存在（AC12"删表行即补完被中断的 delete"）；
- **1 条 `create`** → **回滚**：确保记录行与顺序行都不存在（注册可重建，回滚是安全方向）；
- **≥2 条** → **大声失败**：出现即说明不变量已被破坏，且无法推断意图顺序——正是 AC13 要防的
  "静默容忍"。（**为什么 ≥2 不该发生**：跨进程由 `instance_lock.py` 保证，同进程的请求并发由
  D4b 的写锁保证。少了 D4b 这一层，两个并发请求就能真的留下两条标记——这不是理论担忧，
  见 D4b。）

AC13 的另一半：**没有标记**却存在顺序/表不一致（记录无顺序行 / 顺序行无记录 / **有会话账本
行却无记录**）→ **大声失败**，不静默修补。这三种一一对应关系都是可检查的硬不变量。

### D6 — bootstrap：一次性、仅凭 header、完成标记最后写

首次成功启动（`workspace_meta` 无 `bootstrap_done`）时，**仅凭已持久化 header**
（`id` / `cwd` / `createdAt`，**绝不读事件正文**）把规范 cwd 有效的会话按目录分组为 workspace，
**最新的排在最前**（AC14）。完成标记**最后写**（AC15）→ 被中断的引导可安全续跑（重跑幂等：
按 path 复用既有记录，按 session_id 去重）。bootstrap **只发生一次**（AC16）：此后新建会话只能
通过 `attachSession` 加入。

`createdAt` 取 `session/started` 事件信封的 `time`（不解析事件正文）；`id` 取会话目录名。
为此给 `JsonlSessionStore` 增加一个**只读头部**的方法（流式读到第一条 `session/started` 即停，
正常情况下就是第一行）。

**对 AC14 的一处收窄（显式记录）**：把 cwd 等于"**默认每会话沙箱目录**"的会话排除在分组之外。
判据取 `Path(cwd).name == session_id`——未指定项目时 `service.py` 把目录建成
`workspaces_root/<session_id>`，"目录名 == 会话 id"正是它的结构特征，且不需要把
`workspaces_root` 灌进本模块。理由：那是"用户没选项目"的实现痕迹，不是用户选择的项目；
按字面分组会给每个未命名会话凭空造一个项目（标题还是 uuid），与 AC3"缺省取末段路径"的意图
相悖。反向开关很小（一个具名谓词），若产品要"每个会话都是一个项目"，改一行即可。

### D7 — 命名：新包 `workspace/`，类名 `WorkspaceIndex`

`agent_harness.sandbox.WorkspaceRegistry` 已占用 "WorkspaceRegistry" 这个名字，而它做的是
**会话→沙箱目录映射**（`<root>/workspaces/<session_id>.json`），与本票的"项目实体 + 有序账本"
是两件事；`assembly.build_runtime(..., workspace_registry=...)` 的参数也已经叫这个名字。
为避免同名不同物，本票的新类叫 **`WorkspaceIndex`**（它确实是会话的**索引**，D3），
包名 `agent_harness.workspace`。两个类的 docstring 互相指路，禁止混用。

### D8 — 路径校验的替换方案与迁移（AC18；实施在 #154）

现状：`service.py:_validate_workspace_name`（活）+ `web/app.py:_validate_workspace_name`（死代码）；
`POST /api/sessions.workspace` 是**名字**语义。

演进（**不破坏既有契约**，分两步）：

1. **#152（本票）**：注册表层已经接受任意已存在目录（`create(path)`）；`POST /api/sessions`
   的 `workspace` 仍按名字走（旧行为不变），只是创建会话后**多一步 attach**：把
   `<workspaces_root>/<name>` 的规范路径注册进账本（不存在则 `create`）+ 前插会话 id。
   即"同名 workspace = 同一个项目"从"能跑"升级为"可见"。
2. **#154（项目 CRUD API）**：新增 `POST /api/projects`（body 是绝对路径）等端点；`POST
   /api/sessions` 增加 `workspace_id` 字段；`workspace`（名字）保留为**兼容别名**
   （解析顺序：能对上既有项目的 title/末段名 → 用它；否则按旧规则建目录）。届时删除
   `web/app.py` 里的死副本，并把 `service.py` 的校验函数从"名字白名单"缩成"名字形状检查
   （不含分隔符）"——路径合法性由注册表的 `create` 负责（已存在 + 规范化 + 唯一）。
3. **迁移**：现存 `<workspaces_root>/<name>` 目录与已落盘会话由 D6 的 bootstrap 归组，
   无需用户动作；旧会话无 cwd → 保持 Ungrouped（AC16）。

**谁不再负责边界**：`_validate_workspace_name` 的 `is_relative_to(workspaces_root)` 这一条在
#154 随名字语义一起退役；替代它的是 D1 的三条补偿约束 + 运行时沙箱边界（不变）。

---

## Consequences

- 项目列表/账本可被重建（D3），因此索引损坏不是数据损坏；反过来，**手工改账本不会**
  改变会话归属（header 才是真相）——这正是 AC6 双向校验想要的。
- 记录与账本读是纯内存（AC10），列表页不再需要"全量扫 session root 再分组"；代价是进程启动时
  多一次全量载入 + 一个 bootstrap 扫描，以及每次计算 `session_ids` 仍要读账本成员的 header
  （D4 的准确边界）。写路径多了一把进程内锁（D4b），代价是同一进程内的写请求串行——这些写
  都是几毫秒级的 SQLite 事务 + JSONL 首行读，不构成吞吐问题。
- 一个"待定变更"会导致下次启动时**自动回滚一个创建**或**补完一个删除**（D5）。这是刻意的：
  宁可让用户重新注册一次项目，也不留一个半创建的项目在索引里。
- `harness.db` 多 5 张表（D4），`RecoveryStores` 多一个成员；无新依赖、无新进程、无新配置项。

## Non-Goals

上传 / 导入项目、目录浏览器端点、前端 UI、会话硬删除、把 workspace 概念渗进 Agent Loop
或事件流（模型不可见：没有工具、没有提示词、没有会话事件）。
