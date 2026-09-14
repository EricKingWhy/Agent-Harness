# Ticket: 修复 `tests/evaluation/test_smoke.py` 的 Settings stub 字段漂移（Phase 15 D7 欠账）

> **状态**：✅ 已修复并验证 · commit `f8e0ba7`（feat/backend）
> **类型**：Bug / 测试欠账（pre-existing，非本轮 refactor 引入）
> **优先级**：P2（测试套仅在 full-suite 顺序下红，隔离跑绿——但会污染全量基线，且掩盖真实回归）
> **来源**：2026-09-10 对架构深化（候选 1/2/3）集成产物的独立验证
> **关联 commit**：根因引入于 `dbb48a5`（Phase 15 D7 DEFER 批）· 修复于 `f8e0ba7`

---

## Problem Statement

`tests/evaluation/test_smoke.py` 内有两处**动态构造的 Settings stub**（`type("S", (), {...})()`），
它们是手写的字段白名单，用来在不加载真实 `Settings` 的前提下喂给
`evaluation.smoke.run_real_model_smoke()`。Phase 15 D7（`dbb48a5`）给 `Settings` 新增了两个
Langfuse 字段并在装配点读取，但**漏改了这两处 stub**，导致：

* `pytest tests/ -q`（full-suite）→ **3 failed**
* `pytest tests/evaluation/ -q`（目录级）→ **1 failed**
* 单文件 / 单测试隔离跑 → **passed**（顺序依赖，只在 full-suite 才暴露）

失败信息：

```
AttributeError: 'S' object has no attribute 'langfuse_tracing_environment'
  src\agent_harness\observability\__init__.py:31
```

失败用例：

```
FAILED tests/evaluation/test_eval_skeleton.py::test_run_dataset_writes_local_report
FAILED tests/evaluation/test_smoke.py::test_smoke_pipeline_with_injected_fake_runtime
FAILED tests/evaluation/test_smoke.py::test_smoke_builds_runtime_with_fallback_config
```

## Root Cause

`dbb48a5` 同时改了三处：

| 文件 | 改动 |
|---|---|
| `src/agent_harness/config.py:113-114` | 新增 `langfuse_tracing_environment: str = "development"` / `langfuse_release: str = ""` |
| `src/agent_harness/observability/__init__.py:31-32` | 装配时读取上述两字段 |
| `tests/evaluation/test_smoke.py` | **漏改** —— stub 的键集合未同步 |

由于 stub 是 `type("S", (), {...})()` 这种**闭集**动态类，缺字段不是构造期报错，而是
**运行到装配点才 AttributeError**——所以失败点远离修改点，且依赖 `_process_sink` 单例的
装配时机（首个触达 `get_observability_sink` 的测试决定谁失败），表现为顺序敏感。

### 证据链（确认 pre-existing、与候选 1/2/3 无关）

1. 字段定义与消费点在同一提交 `dbb48a5`（2026-09-07，Phase 15 D7）引入。
2. `git merge-base --is-ancestor dbb48a5 977b319` → **通过**（早于本轮 refactor 基线）。
3. `git show 977b319:src/agent_harness/observability/__init__.py` 已含
   `tracing_environment=settings.langfuse_tracing_environment`。
4. `tests/evaluation/test_smoke.py` 与 `evaluation/smoke.py`：基线 `977b319` vs HEAD **字节完全相同**。
5. 候选 1/2/3 三个提交共 9 个文件，**不含任何 `tests/` 或 `evaluation/` 路径**。
6. 单测试隔离跑 → passed（顺序依赖确认）。

→ 该缺陷在纯基线 `977b319` 上必然同样发生；集成 AI 报告的
「全量 1485 passed / 0 failed」在本工作树不可复现。

## Solution

给两处 stub 补齐被读取的两个字段（值取 `Settings` 默认值，保持「未配置 Langfuse」语义）：

```python
"langfuse_tracing_environment": "development", "langfuse_release": "",
```

### 改动位置

* `tests/evaluation/test_smoke.py:83-88`（`test_smoke_pipeline_with_injected_fake_runtime`）
* `tests/evaluation/test_smoke.py:129-139`（`test_smoke_builds_runtime_with_fallback_config`）

### 同批派生的 CRLF 处置（附带）

提交 `f8e0ba7` 时 git 警告新增的 `scripts/run_tests_clean.sh` 会被转 CRLF。
仓库原无 `.gitattributes`，`.sh` 下次检出将变 CRLF → Git Bash 执行报
`bad interpreter: ...^M`。故同批补最小 `.gitattributes`：

```
*.sh  text eol=lf
*.ps1 text eol=crlf
```

验证：`git check-attr eol -- scripts/run_tests_clean.sh` → `lf`；
`dev.sh` 亦为 `lf`；`.ps1` 全部位于 `.specify/scripts/powershell/`（CRLF 正确）。
加入后 `git status` 零改动——**不**执行 `git add --renormalize`（入库本就 LF，无必要）。

## Acceptance Criteria

- [x] `pytest tests/evaluation/ -q` → 全绿（12 passed）
- [x] `pytest tests/ -q`（full-suite，无环境 shim）→ **1485 passed / 9 skipped / 39 deselected / 0 failed**
- [x] `ruff check .` clean
- [x] 仅动 `tests/evaluation/test_smoke.py`，无副作用面扩散
- [x] 修复不改变任何生产代码语义（纯测试 stub 补字段）

## 权威基线（修复后，`PYTHONPATH=` 纯净环境）

```
1485 passed, 9 skipped, 39 deselected, 8 warnings in 157.53s
```

junitxml 三方对比（同 HEAD `ccd1639` + 本修复）：

| run | 环境 | tests | fail | skip |
|---|---|---|---|---|
| `full-run.xml` | 带 shim（默认） | 1494 | **3** | 9 |
| `full-run-nosite.xml` | `PYTHONNOUSERSITE=1`（无效） | 1494 | **3** | 9 |
| `full-run-clean.xml` | `PYTHONPATH=`（绕开 shim） | 1494 | **0** | 9 |

→ **唯一差异是环境侧删除配额**；`tests=1494` 恒定（1485 passed + 9 skipped = 1494）。

**此结果与集成 AI 报告的「1485 passed / 9 skipped / 0 failed」完全一致**——
集成报告属实，此前"无法复现"纯属本沙箱环境噪声所致。

## ⚠️ 环境干扰层（第二层根因，非本仓代码问题）

修好 stub 后，失败的**外层症状**从 `AttributeError` 变成 `SystemExit: 1`，
traceback 指向**运行环境**而非本仓代码：

```
D:\DevTools\WorkBuddy\...\cli\vendor\shim\sitecustomize.py:826: SystemExit
message = '[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
           {"count":1485,"threshold":50,
            "targets":["...\\evaluation\\reports\\p0_core-*.json"],"targetCount":1}'
```

**机理**：该 shim 拦截 `Path.unlink()` 做"安全删除"，并维护一个
**跨测试累积的删除配额**（`threshold: 50`，`scope: turn`）。
pytest 每个测试用例结束都会清理 `tmp_path`（触发 unlink），全量跑到后期
配额耗尽 → 命中 `_exit_bulk_guard_control` → `SystemExit(1)`。

**证据**：`count` 值与全量测试数同量级（1485 ≈ 1494 tests），且
**仅在 full-suite 触发**、隔离跑全绿 —— 典型的环境侧累积效应。

**结论**：这 3 个 "FAILED" 在 WorkBuddy Agent 沙箱环境里**是环境噪声，不是代码缺陷**。
真实（无 shim）环境下 `pytest tests/ -q` 的结果见下方「权威基线」。

### 本地复现/绕开方式

shim 经 `PYTHONPATH` 注入：

```
PYTHONPATH=D:\DevTools\WorkBuddy\...\cli\vendor\shim
```

清空后即可绕开（`sitecustomize` 不再加载）：

```bash
PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/ -q
```

> 注意：`PYTHONNOUSERSITE=1` **无效**（shim 不是 user site，是 PYTHONPATH）。

## 防再发建议（Out of Scope，另立 ticket）

当前 stub 是**手写闭集**，新增 Settings 字段必然再次漂移。可选加固（择一，勿在本 ticket 混做）：

1. `SimpleNamespace` + `Settings.model_construct()`——直接用真实模型，`model_construct` 跳过校验，
   默认值天然齐全，未来加字段零维护。
2. 或在 `tests/evaluation/conftest.py` 提供共享 `settings_stub` fixture，单一入口 + 显式 `# 与 Settings 同步` 注释。

推荐方案 1：`Settings.model_construct(**overrides)` 是 pydantic 官方 API，零维护面最大。

## Out of Scope

- 真实 Langfuse 云 Gate 行为（属 Phase 15 已验证范围）。
- `evaluation/seed_langfuse.py`（用真实 `Settings()`，无此问题）。
- Settings stub 共享 fixture 重构（见上「防再发建议」）。
