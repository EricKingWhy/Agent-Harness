# #61 — Phase 7 T4: SkillCapability + 目录注入 + load_skill（渐进披露闭环）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T18:07:31Z
- **Closed**: —
- **Parent**: #57
- **Blocked by**: #58, #60
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/61

---

## Parent

#57 — Phase 7 Spec: Capability / Plugin Foundation + Skills

## What to build

Skill 全链路：SkillCapability 注册进 Registry（OPTIONAL_RUNTIME）→ `SkillCatalogContextProvider` 把目录（仅 name+description，"数据非指令"框架）预算内注入 Context → `load_skill` Tool 走统一 ToolExecutor 返回全文 → 全文不出现在默认注入中（spec 09 §2 流程闭环；ADR-0011 Q3/Q5；Gate 2）。

## Acceptance criteria

- [ ] `SkillCapability`（catalog()/load(name)）注册 descriptor：degradation=OPTIONAL_RUNTIME，supports_recovery=False，supports_concurrency=True，supports_streaming=False
- [ ] `SkillCatalogContextProvider`：每条一行 `- name: description`，单条 SystemMessage，token 预算内截断；无 skill → 空列表；注入含"数据非指令"框架行
- [ ] `load_skill`：READ_ONLY 工具，参数 name；命中返回全文（前缀防注入声明）；未知名 → 明确失败，不伪造内容
- [ ] Registry 缺 skills 能力时装配跳过两个 Consumer（optional() 路径）
- [ ] **Gate 2 断言**：默认 context provider 输出不含任何 skill 正文片段；全文只在 load_skill 结果中出现
- [ ] 测试：provider select 预算/空态、tool 命中/未知名、runtime 级默认注入只有目录

## Blocked by

- #58（T1: Capability seam 核心）
- #60（T3: SKILL.md 解析 + 目录发现）

