# #18 — Ticket 7: 全工具注册导出 + 集成 fixture + 批次调度验证

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:03:00Z
- **Closed**: 2026-09-03T13:27:00Z
- **Parent**: #11
- **Blocked by**: #13, #14, #15, #16, #17, #12
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/18

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

集成收尾 ticket：把 6 个新 Coding Tool（edit / glob / grep / apply_patch / git_status / git_diff）接入工具注册导出和集成测试 fixture，并验证批次调度在新工具上行为正确（纯 READ_ONLY 批可并发，含 MUTATING 的批串行）。这是把 Ticket 1-6 的孤立实现缝合进项目的 vertical 切片，确保它们和 read/write/bash 在 ToolExecutor 下表现一致。

## Acceptance criteria

- [ ] `tools/__init__.py` 导出全部 9 个 Coding Tool 类（read/write/bash + edit/glob/grep/apply_patch/git_status/git_diff）。
- [ ] `tests/agent/test_integration_coding.py` 的 `_make_runtime` fixture 注册全部 9 个 Coding Tools（之前只注册 3 个）。
- [ ] 批次调度验证测试（追加到 `tests/tools/test_coding_tools.py` 的 TestBatchScheduling 或新类）：
  - 纯 READ_ONLY 批（如多个 glob 调用）→ execute_batch 返回全部成功、tool_call_id 配对正确。
  - 混合批（如 git_status[READ_ONLY] + edit[MUTATING]）→ 整批串行执行、全部成功、结果顺序正确。
  - 全 MUTATING 批（如多个 edit）→ 串行、全部成功。
- [ ] 每个新工具的 side_effect 分类断言（edit=MUTATING, glob=READ_ONLY, grep=READ_ONLY, apply_patch=MUTATING, git_status=READ_ONLY, git_diff=READ_ONLY）至少在一个测试里显式断言过（可在各工具自己的测试里已有，本 ticket 汇总确认）。
- [ ] `pytest -q` 全绿（含原有测试 + Ticket 1-6 新增测试）。
- [ ] `ruff check .` 无新增告警。
- [ ] 所有现有测试仍通过。

## Blocked by

- #13（Ticket 2: edit）
- #14（Ticket 3: apply_patch）
- #15（Ticket 4: git_status + git_diff）
- #16（Ticket 5: glob）
- #17（Ticket 6: grep）

（#12 list_files 是 Ticket 5/6 的前置，间接被覆盖，不单独列。）

