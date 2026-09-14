# Phase 5 Gate — Artifact + Context Compaction

验证日期：2026-09-04。分支：`feat/backend`。交付 commit：`c0a4b0f`（#50）。规格：#44、spec 06、ADR-0006 / ADR-0007。

全量回归：`python -X utf8 -m pytest tests/ -q --tb=short` → **424 passed, 8 skipped, 5 deselected in 42.39s**。真实七牛测试按 marker 独立执行（见下）。`ruff check .`、`uv lock --check` 通过。

## 真实对象存储证据

运行命令：

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/integration/test_qiniu_artifact.py tests/integration/test_phase5_qiniu.py -m qiniu -q --tb=short
```

结果：**2 passed in 9.73s**。使用真实七牛云 S3ArtifactStore；模型使用确定性 ScriptedModel，不消耗真实 LLM API。测试只清理各自随机 Session 命名空间中的测试对象。

| 验收项 | 证据 |
|---|---|
| 大输出完整保存，模型仅见摘要与引用 | 真实子进程 Bash 生成 5000 行；S3 load 与完整输出逐字一致；所有模型请求均不含完整输出；Ledger 记录摘要及相同 artifact_ref |
| inspect_artifact 找回局部细节 | 统一 Executor 调用 inspect_artifact，返回第 2501 行 `output 2500` |
| Provider 可替换 | 同一个 `run_phase5_scenario` 分别注入 FakeArtifactStore 和真实 S3ArtifactStore，Runtime 不变 |
| 自动 Compaction | 多 turn 历史超过 auto 阈值，模型后续请求包含 SystemMessage 摘要，context/compacted 进入事实流 |
| 历史不删除，刷新可重建 | 压缩前事件前缀不变；重新创建 JsonlSessionStore / Session 后事件与消息投影一致；HTTP 刷新结果与 SSE 的持久事件一致 |
| 新事件对账 | artifact/created、context/compacted 的 type / seq / data 与实时流相同；串行及并行批次部分存储失败也先发出已提交事件，再传播异常 |
| hard guard 停止运行 | run / run_stream 均记录 run/failed，状态 context_window_exceeded；不继续调用模型 |

## 装配与边界

- AgentRuntime 默认使用 ContextBuilder，也接受显式注入；它只依赖项目接口，不依赖 S3 SDK。
- Web 后端按 Settings 装配 ContextBuilder。对象存储五项配置全空时不启用 Artifact；配置后按 Session 绑定 S3 Provider、Overflow Handler、InspectArtifactTool。
- 配置示例在 `.env.example`；真实凭证只在 Git 忽略的本地 `.env`，不写入验收记录。
- Compaction 保留当前用户 turn、压缩早期完整 turns；机械降级按 hard guard 判定安全。具体边界沿用 #49 交接记录。
- 本 Gate 验证持久事件和历史投影重建；不引入摘要缓存、完整产品级 Replay/Fork 或 Phase 6 Memory。

## 审查

Standards 审查发现批次部分失败可能漏发 Artifact 事件。已补串行/并行回归，修复 Runtime 异常后的事件发送，并让并行 Executor 等待全部已启动调用结束再传播异常；复核通过。Spec 审查未发现新增代码问题；真实七牛凭证 Gate 已补验通过。
