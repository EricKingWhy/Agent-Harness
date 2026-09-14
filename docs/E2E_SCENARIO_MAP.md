# E2E 场景↔测试映射（T8 #101）

> 车道：`cd web && pnpm exec playwright test`（`npm run test:e2e`）。Chromium 单引擎
> （grill Q5 批准范围），1280/1920 两档宽度 project。webServer = vite dev（5173），
> API 由 `e2e/fixtures.ts` 的 page.route 拦截（mock SSE，帧形状 =
> docs/BACKEND_CONTRACT_STREAMING_UI.md）——**核心矩阵不依赖真后端**。

## 车道分层（spec 03 §22 尾注）

| 车道 | 内容 | 触发 |
| --- | --- | --- |
| vitest 默认 | 纯函数/投影/SSR 契约（827 用例 / 49 文件） | 每次提交；e2e/** 已排除 |
| Playwright 本骨架 | mock SSE 终态矩阵（322 用例 = 161×2 档，37 个 spec） | `pnpm exec playwright test --workers=2`（手动/夜间） |
| 联调车道 | 真模型、鉴权、流式中间态、长稳 | 后端集成后（spec 03 §21 完整矩阵） |

> 计数随测试增删同步更新——漂过六次（351→430→443→472→813→827 / 12→80→86→310→322，最近一次是 #171 顺手校准），改测试时顺手改这里。
> 口径以命令输出为准：`npx vitest run` 的 `Tests` 行与 `npx playwright test --list` 的条数。

## 场景映射（spec 01 §22 A-I）

| 场景 | 文件 | 覆盖 | 备注 |
| --- | --- | --- | --- |
| A reasoning 流 | `e2e/a-reasoning.spec.ts` | 思考块聚合（envelope block_id）、完成态、最终文本唯一（无重复块） | 零伪造：fixture 有思考才有块 |
| C 工具输出 | `e2e/c-tool-output.spec.ts` | tool/call 先于执行落盘、终态由 tool/result 校准、折叠行渲染 | 流式分块中间态见下 |
| E 断连重连 | `e2e/e-reconnect.spec.ts` | 流异常收尾→断线条（800ms 阈值）→`after_seq=lastApplied` 续传（重放零重叠）→终态清条；重放无重复 | T4 #97 契约 §3 |
| F 历史重放 | `e2e/f-history.spec.ts` | 会话行首条 user/message 标题 → projectHistory 重建 | 不变量 #22 同一管线 |
| H 密度四档 | `e2e/h-density.spec.ts` | data-density 即时生效 + localStorage（ahi.traceDensity）刷新持久 | 冻结决策 |
| I 键盘可达 | `e2e/i-keyboard.spec.ts` | Ctrl+K palette 唤起/焦点/Esc 关闭；Composer Ctrl+Enter 提交 | |
| 分叉（T7 #137） | `e2e/b-fork.spec.ts` | from_seq = user/message 的 **seq**（非 turn 序号）、422 detail 可见、第 1 轮「空会话」提示、注入消息无入口 | BUG-001 回归锁；夹具 `user/message` 不写 step_id（真实信封形状） |
| 恢复 + 中断横幅（T8 #138） | `e2e/d-recover.spec.ts` | 成功反馈不被 `canRecover` 门回收、`repaired=0` 两义区分、409 需人工裁决、中断横幅 null/非 null 文案 | 恢复成功是**门外的**提示——挂门内会被入口卸载一并带走 |
| 滚动跟随（#95） | `e2e/j-scroll.spec.ts` | `overflow-anchor: none`、空闲态无「↓ 最新」浮标、**真实滚轮**上滚后浮现浮标且位置不被拽回、点浮标回底并恢复跟随 | 末条用真实 `page.mouse.wheel`（浏览器事件）驱动，覆盖「上滚脱离」路径；「每个 delta 到达时是否拽回」依赖帧到达时序，仍按 HANDOFF §C.5 在真机验证 |
| 窄屏触摸可达（#181） | `e2e/touch-rail.spec.ts` | `(hover: none)` 档：会话行与项目行的 ⋯ 在**空闲态**即 `opacity:1` 且 `tap()` 能开菜单（两层同款）；槽位让给 ⋯ 后「在跑」与「目录缺失」两个状态信号仍挂在 ⋯ 上 | 触摸上下文 = `hasTouch + isMobile`（桌面输入的窄屏用例 `w-session-delete` / `r-project-groups` 覆盖不到这一档） |
| 会话归档（#171） | `e2e/archived.spec.ts` | 归档行默认收起、开关打开重现且带真徽标、跨刷新保留开关；归档/取消归档可逆且无确认面（不带 danger 样式）；409（在途 run）留在原地贴后端 detail 且**取消归档永不被挡**；归档后**视野不被拽走**；"n 条会话日志缺失"**不把归档算进去**（被开关过滤 ≠ 日志丢了）；空态提示不说"0 条都已归档"；写成功但列表重拉失败时就地说明 | mock 的 `GET /api/sessions` 按真后端语义过滤 `include_archived`（fixtures 那一支），所以"前端总要全量、可见性交给投影层"这条设计漏参数就会红；两条 404/409 detail 由后端 `tests/web/test_session_archive_api.py` 逐字锁住 |
| B/D/G | 未建 | B（多轮上下文）/D（compact 降档）/G（长会话性能）——真模型/长跑场景 | 联调车道 |

> 命名注意：文件名前缀（`b-fork` / `d-recover` / `j-scroll`）是**增量序号**，与
> 本表第一列的 spec 场景字母（A–I）不是同一套词汇。`b-fork` 不是「场景 B 多轮
> 上下文」，`d-recover` 也不是「场景 D compact 降档」——看第二列的文件名。

## 骨架车道已知边界（联调车道补）

1. **帧一次性到达**：`route.fulfill` 字符串形态在 1.63 不保证逐帧流式（实测
   `response: new Response(ReadableStream)` 帧未送达）——投影瞬时完成，只断言
   终态。caret / reasoning 呼吸图标 / ReadLine 读视口 / 工具输出跟随浮标 /
   stdout/stderr 分色块（终态被 result 校准替换，T3 设计）等流式中间态，
   由联调车道（真后端）或本地 SSE fixture server 覆盖。
2. **Balanced 档工具卡是折叠行**（`.act-node`，name+args 摘要+状态 chip）；
   `.tool-card-body` 只在展开/detailed 档存在。
3. **终态后 viewing 迁移会重读 `GET /events`**（#22 后台对账）——mock 必须提供
   `events` fixture，否则历史重建清空现场（f/e/i 场景的教训）。

## 环境注意

- 本仓 node_modules 为 **pnpm 布局**：装依赖用 `pnpm add`，npm 会报
  `edgesOut` 错误；跑 playwright 用 `pnpm exec playwright test`（npx 会命中
  全局缓存里的旧版）。
