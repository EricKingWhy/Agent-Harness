# Code Review — 架构深化 C1-C3 + D7 修复批次

> **审查范围**：`977b319...c7e0c16`（6 commits，13 files，+1007/−394）
> **审查日期**：2026-09-10
> **审查方式**：双轴（Standards / Spec）独立子代理 + 人工逐条核实
> **结论**：⚠️ **有 2 项须修后再 push**（1 硬 / 1 契约），其余为建议项
> **修复状态**：✅ **H1/H2/S1/S2 已全部修复**（见文末「修复记录」），门禁全绿，可 push

---

## 审查范围

| commit | 说明 |
|---|---|
| `21c9779` | refactor(agent): 提取 `_TerminalContext`（candidate 1） |
| `9489bb3` | refactor(session): 拆分 SessionService（candidate 2） |
| `ccd1639` | docs(arch): `StartupInterruptionScan` 条目（candidate 3） |
| `f8e0ba7` | fix(eval): D7 stub 字段漂移 |
| `1401ef6` | chore: `.gitattributes` |
| `c7e0c16` | docs(ticket): 补记 |

---

## ✅ 通过项（已人工复核）

| 检查 | 结果 |
|---|---|
| **`build_runtime` 仍在 `service.py` 模块级**（测试 monkeypatch 红线） | ✅ `service.py:36` |
| **测试文件零改动**（candidates 1/2/3） | ✅ 三提交无 `tests/` 路径 |
| **`_drive` 两臂 yield/discard 语义保住** | ✅ 异常臂 yield；取消臂丢弃 |
| **`scan.py` 未合并进 RecoveryCoordinator** | ✅ 仅 +5 行 docstring |
| **`close_observability` 三分支同层独立** | ✅ 与基线等价 |
| **CONTEXT.md 四要素齐全**（顺序/单进程/短命令禁令/多进程 lease） | ✅ |
| **D7 ticket 事实性声明**（`dbb48a5`、`observability:31`） | ✅ 逐项成立 |
| **commit 格式** | ✅ `type(scope): 描述` |

---

## ❌ 须修项

### H1 — `approval.py` 夹带新增 API（违反「纯结构重构」契约）

```python
# src/agent_harness/session/approval.py:104
def as_callback(self) -> ApprovalCallback:
    return self
```

**证据**：基线 `977b319` 的 `grep as_callback` 仅命中 **docstring 文字**（第 1163 行），
**方法定义不存在**。新版却真的定义了它 —— 属**新增 API**。

**且全仓零调用点**（`grep -rn as_callback` 排除自身 = 空）。

**影响**：本批次以「纯结构重构、行为不变」为契约交付。新增无调用点的公开方法是
**行为面的扩张**，破坏契约。子代理判为 **Speculative Generality**（无需求支撑的抽象）。

**修法**：删除该方法（docstring 中对该名的提及应同步修正为实际语义）。

---

### H2 — `model_switch` ↔ `service` 循环依赖

```python
# model_switch.py:73-77
def _amend_options() -> AmendOptions:
    """延迟导入 AmendOptions，避免 model 模块 <- service 的循环导入。"""
    from agent_harness.session.service import AmendOptions
    return AmendOptions()
```

**事实**：
- `service.py:68,77` **模块级**导入 `model_switch`
- `model_switch.py:28,75` **反向**延迟导入 `service.AmendOptions`
- → **双向依赖**，靠函数内延迟导入回环

**为何坏**：`_amend_options()` 的唯一用途是 `replace(amend or _amend_options(), model=model_id)`
（`model_switch.py:70`）—— 即「`amend` 为 `None` 时造一个默认值」。这是**纯数据载体构造**，
没有任何理由让它依赖 `service`。

**修法（择一，推荐 A）**：
- **A**：`AmendOptions` 下沉到独立模块（如 `session/amend.py` 或 `session/model_switch.py`），
  由 `service.py` 以 facade 形式 `from ... import AmendOptions` 重新导出
  （既有导入路径 `from agent_harness.session.service import AmendOptions` 不变，
  `web/app.py` 与 tests 无需改动）。
- **B**：`model_switch` 内提供 `AmendOptions` 的本地等价构造，由 `service` 统一导出。

> ⚠️ **注意**：`AmendOptions` 被 `web/app.py`（3 处 `from_request`）与多个测试文件
> 从 `service` 导入。任何下沉**必须**经 `service.py` 重导出，否则破坏兼容面。

---

## 💡 建议项（非阻断）

### S1 — `_logger()` 硬编码模块名（孤立反模式）

```python
# model_switch.py:80-83
def _logger():
    import logging
    return logging.getLogger("agent_harness.session.service")
```

**问题**：代码现位于 `model_switch.py`，却自称 `session.service` → 日志溯源误导。
且全仓统一模式是**模块级** `logger = logging.getLogger("agent_harness.xxx")`
（`runtime.py:80`、`builder.py:21` 等十余处），此处为孤例。

**修法**：改为模块级 `logger = logging.getLogger("agent_harness.session.model_switch")`
（或沿用 `agent_harness.session` 保持既有日志分类），调用点改 `logger.warning(...)`。

### S2 — `approval.py` `__all__` 误导出 `PermissionPolicy`

```python
# approval.py:146-150
__all__ = ["InteractiveCallbackHolder", "PermissionPolicy", "build_approval_callback"]
```

`PermissionPolicy` 在 `approval.py` **只 import 未使用**（第 24 行导入，第 148 行仅列 `__all__`），
且 `service.py` 自己**直接从 `tooling.contract` 导入**（第 89 行），**不经由 `approval`**。
→ re-export **无人消费**，纯多余。

**修法**：从 `__all__` 移除 `PermissionPolicy`，并删除第 24 行的未使用导入。

### S3 — `PHASE_STATUS` 条目缺提交 hash

同文件既有先例均带 hash（如 `169d9a4..daa7b5d`），本批条目未记录
`21c9779`/`9489bb3`/`ccd1639`。建议补上以便溯源。

### S4 — 范围越界说明

`1401ef6`（`.gitattributes`，仓库级配置）与 `f8e0ba7` 中的 `scripts/run_tests_clean.sh`
均非 spec 授权的交付物。虽属改进，但注入了一个「3 commit / 零行为变化」的批次。
ticket 已自述「同批派生」，透明度尚可。建议后续此类改动走独立 ticket。

---

## 两轴汇总

| 轴 | 发现数 | 最严重 |
|---|---|---|
| **Standards** | 4（2 硬 + 2 判断） | **H1** `approval.py` 夹带新增 `as_callback`（违反纯重构契约） |
| **Spec** | 3（0 阻断） | **范围**：`.gitattributes` + 新脚本未经 spec 授权 |

**无阻断性缺陷**：三个候选的核心实现正确、约束全保、测试零改动、门禁全绿。
但 H1/H2 应在 push 前修掉 —— 它们恰好落在本批次最核心的契约（「纯结构重构」）上。

---

## push 前建议动作

1. 修 **H1**（删 `as_callback`，全仓零调用，风险低）
2. 修 **H2**（下沉 `AmendOptions` + `service` facade 重导出；须复跑 `tests/session/` + `tests/web/` 验证兼容面）
3. 顺手修 **S1/S2**（各 2-3 行，零风险）
4. 复跑全量 + `ruff check .`，确认测试数与基线一致
5. 更新 ticket/PHASE_STATUS 记录本次 review 结论

---

## ✅ 修复记录（2026-09-10 18:46）

### H1 — 删除夹带 API

- `src/agent_harness/session/approval.py`：删除 `as_callback()` 方法定义（-3 行）
- 同步修正 docstring：`"调用方需通过 as_callback() 获取真正的 callable"`
  → `"（bind 前调用 raise）"`
- 验证：全仓 `grep as_callback` → **零引用**

### H2 — 消除双向依赖

**新增** `src/agent_harness/session/amend.py`（自包含，仅 stdlib 依赖）：
- `AmendOptions` 数据类（含 `from_request` / `to_runtime_kwargs`）
- `amend_kwargs()` 辅助函数（原 `service._amend_kwargs`）

**改动**：
- `service.py`：删除原 `AmendOptions` 定义与 `_amend_kwargs`，改为
  `from agent_harness.session.amend import AmendOptions, amend_kwargs` 重导出；
  2 处调用点 `**_amend_kwargs(amend)` → `**amend_kwargs(amend)`
- `model_switch.py`：删除 `_amend_options()`（延迟导入回环），
  改为顶层 `from agent_harness.session.amend import AmendOptions`；
  `replace(amend or _amend_options(), ...)` → `replace(amend or AmendOptions(), ...)`

**环消除验证**（双向导入压力测试）：
```
先 import service      → OK
先 import model_switch → OK
AmendOptions 同一对象（service / amend）→ True
```

### S1 — logger 归一

`model_switch.py`：删除 `_logger()` 工厂，改为模块级
`logger = logging.getLogger("agent_harness.session.model_switch")`（+ `import logging`），
调用点 `_logger().warning(...)` → `logger.warning(...)`。

### S2 — `__all__` 清理

`approval.py`：`__all__` 移除未使用的 `PermissionPolicy`，并删除
`from agent_harness.tooling.contract import PermissionPolicy`（-2 行）。

### 门禁结果

| 检查 | 结果 |
|---|---|
| `ruff check .` | ✅ All checks passed |
| 核心子集（session/web/evaluation/cli/assembly） | ✅ **389 passed / 0 failed** |
| **全量套**（净化环境） | ✅ **1485 passed, 9 skipped, 39 deselected, 0 failed** |
| `tests/` 改动 | ✅ **零改动**（纯结构重构契约保持） |
| 改动面 | 3 修改（approval/model_switch/service）+ 2 新增（amend.py/review 文档） |

**全量测试数与修复前逐字一致** → 零回归。

### 未处理（留给后续）

- **S3** PHASE_STATUS 本批条目补 commit hash —— 待本次修复提交后一并补
- **S4** 范围越界（`.gitattributes` + `run_tests_clean.sh`）—— 已发生，记录在案即可
