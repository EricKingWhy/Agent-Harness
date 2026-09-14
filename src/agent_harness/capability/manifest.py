"""`GET /api/capabilities` 的 manifest 契约（SDD 03 §17）：条目形状 + **内置工具集**的 core 条目。

## 为什么有 core 条目（#193）

前端中心列的 tab 集由 `capabilities.ts::centerTabs` 决定，判据是"**能力声明为 true
且已实现**"。而 `changes`（「文件/改动」）与 `terminal`（「输出」）两个面由**内置工具**产出：

| 面 | 产出的内置工具 | 事实来源 |
| --- | --- | --- |
| `changes` | `write` / `edit` / `apply_patch`（结果的 `before/after`、`changed_files`） | `changedFiles.ts` 的投影 |
| `terminal` | `bash`（`tool/output_delta` 合帧 → 命令输出聚合） | `commandOutput.ts` |

它们在 `assembly.build_runtime` 里**无条件注册**（唯一收窄是 `agent_profile` 的
`tool_scope`），所以"本部署能产出这两个面"是**恒真**的部署级事实。

**这份声明是部署级的，不是 profile 级的**：本端点没有 session 上下文，读不到某个 profile
的 `tool_scope`。若某 profile 把 `bash` 收窄掉，「输出」面仍会出现（空态），而不是消失。
这是刻意的取舍——如实的空面 > 按 profile 猜（猜错就是"面忽然不见"）。要做到 profile 级
得让端点在 session 上下文里算，那是另一张票的范围。

`CapabilityRegistry` 只登记**插件** capability（memory / skills / mcp / knowledge /
multiagent / websearch / ticker）。把 `changes`/`terminal` 挂到其中任何一个名下都是假话
——它们不产出这两个面。而端点的保守默认（未声明 `surfaces` → `changes`/`terminal` = false）
写于"只搭骨架"阶段，两个面实现落地后没人回来改它，于是**两个面在所有真实部署里都被滤掉**
（前端 e2e 之所以能看到，是因为它们注入了 `true`——后端发不出那种载荷，见 #193）。
本模块把内置工具集的产出作为显式声明补上，端点的保守默认原样保留给插件条目。

## 判据（以后想再加一个 core 面时照这三条问）

1. 产出它的工具是否在 `build_runtime` 里**无条件注册**？（有 profile 收窄的算"条件"）
2. 它是否需要**额外配置**才能工作？（需要 → 不属 core，例如 `artifacts` 要有对象存储/本地目录）
3. 不声明时用户是否**看不到已经实现的面**？（是 → 必须声明）
"""

from __future__ import annotations

from typing import Any

from agent_harness.capability.base import CapabilityDescriptor

#: `GET /api/capabilities` 里 core 条目的 id。
#: 前端按 `{id, surfaces}` 解析并对多条取**并集**，不解释 id 的语义——这里起个短名只为排错可读。
CORE_CAPABILITY_ID = "core"

#: 内置工具集能产出的面。键集与前端 `SURFACE_KEYS`（`capabilities.ts`）逐字一致
#: ——**手工镜像**，跨语言没有共享来源：改这里必须同时改前端那份（`SURFACE_KEYS` 与
#: `fixtures.ts::CORE_CAPABILITY`），两端测试都锁着这个键集。
#: `artifacts` 刻意 false：外置产物要部署配了 store 才能读（`artifact_select.select_artifact_store`，
#: 没配时读接口是 503）——那是**条件性**能力，不是内置工具集无条件产出的东西（判据 2）。
CORE_SURFACES: dict[str, bool] = {
    "chat": True,
    "timeline": True,
    "changes": True,
    "terminal": True,
    "artifacts": False,
}

#: core **真的有入口**的交互动作。三个从既存路由读出（`web/app.py`）：
#: `POST /api/sessions/{id}/approve`（permissions）、`/cancel`（stop）、`/resume`（resume）。
#: `retry` 没有任何后端入口 ⇒ false。
#: 这里不跟端点的"未声明即全 false"保守默认走：对 core 而言"全 false"是**假话**
#: （三个路由明明在），而这份 manifest 的全部意义就是如实声明。
#:
#: **当前没有消费方**（前端 `capabilities.ts` 明确不读 `actions`，本批也不打算读）——
#: 声明它是为了让这个契约条目**完整且不假**：字段在契约里（SDD 03 §17），值可被测试钉住
#: （`tests/web/test_web_phase2_endpoints.py::test_core_actions_match_really_wired_entry_points`
#: 拿真实路由表比对）。将来做 UI 动作按钮时，读的应该是**会话级**路由状态，
#: 而不是把这里的布尔当授权——它就是一张"入口存不存在"的静态表。
CORE_ACTIONS: dict[str, bool] = {
    "permissions": True,
    "stop": True,
    "retry": False,
    "resume": True,
}


def manifest_entry(
    *,
    entry_id: str,
    display_name: str | None,
    version: str,
    provider_name: str,
    declared_surfaces: dict[str, bool] | None,
    declared_actions: dict[str, bool] | None,
) -> dict[str, Any]:
    """manifest 条目的**唯一形状**：descriptor 与 core 都经这里投影。

    保守默认（未声明的面/动作一律 false，`chat`/`timeline` 除外）只在本函数里写一遍——
    此前它内联在端点循环里，core 若要自己拼字典就会出现第二份形状定义，
    两处迟早漂移（端点、前端、验收文档三边都依赖这个形状）。

    `display_name` 缺省回落 `entry_id`（既有口径：插件不填就显示它的 id）。
    """
    surfaces = declared_surfaces or {}
    return {
        "id": entry_id,
        "display_name": display_name or entry_id,
        "version": version,
        "provider_name": provider_name,
        "surfaces": {
            "chat": surfaces.get("chat", True),
            "timeline": surfaces.get("timeline", True),
            "changes": surfaces.get("changes", False),
            "terminal": surfaces.get("terminal", False),
            "artifacts": surfaces.get("artifacts", False),
        },
        # 部分声明**原样透传**（契约里 actions 是可选的局部字典，不补齐）：只有整份
        # 未声明时才落保守默认。
        "actions": declared_actions or {
            "permissions": False,
            "stop": False,
            "retry": False,
            "resume": False,
        },
    }


def core_manifest_entry() -> dict[str, Any]:
    """内置工具集的 manifest 条目——**恒在**，且排在插件条目之前。

    前端取并集，所以顺序只影响可读性：core 是基线，插件是增量。
    """
    return manifest_entry(
        entry_id=CORE_CAPABILITY_ID,
        display_name="内置工具",
        version="1.0.0",
        provider_name="builtin",
        declared_surfaces=CORE_SURFACES,
        declared_actions=CORE_ACTIONS,
    )


def descriptor_manifest_entry(descriptor: CapabilityDescriptor) -> dict[str, Any]:
    """插件 descriptor → manifest 条目（字段与保守默认同 `manifest_entry`）。"""
    return manifest_entry(
        entry_id=descriptor.name,
        display_name=descriptor.display_name,
        version=descriptor.version,
        provider_name=descriptor.provider_name,
        declared_surfaces=descriptor.surfaces,
        declared_actions=descriptor.actions,
    )
