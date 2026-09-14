# #60 — Phase 7 T3: SKILL.md 解析 + 目录发现

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T18:07:28Z
- **Closed**: —
- **Parent**: #57
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/60

---

## Parent

#57 — Phase 7 Spec: Capability / Plugin Foundation + Skills

## What to build

给定有序 skill 目录列表 + 手动指定路径，发现并解析 `skills/<name>/SKILL.md`（YAML frontmatter 必填 name/description + Markdown 正文），产出 SkillCatalog 与显式解析错误列表。路径越界拒绝；只扫一层；同名先到先得（spec 09 §2 V1 全部四条；ADR-0011 Q1/Q2/Q4）。

## Acceptance criteria

- [ ] frontmatter `---` 围栏切分 + `yaml.safe_load`；缺 name/description 记为解析错误（不中断发现）
- [ ] `SkillCatalogEntry`：name / description / source_path / body 延迟读取（发现阶段不读全文——渐进披露的物理前提）
- [ ] 全局目录（Settings `skill_global_dir`，默认 `~/.intelligence-agent/skills/`）+ 项目目录（workspace `skills/`）+ 手动路径三类来源
- [ ] 同名 skill 先到先得且冲突可见；解析失败列表可观察不静默
- [ ] 路径边界：解析出的路径必须落在声明目录内（resolve + 前缀校验），越界记错误
- [ ] 目录不存在 → 空 catalog，不是错误（OPTIONAL 语义）
- [ ] 测试用 tmp_path 构造 skill 目录，全量套不依赖真实 home

## Blocked by

None (can start immediately).

