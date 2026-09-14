"""OrchestrationAdapter seam（Phase 13 T11, #92）+ import 边界契约。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.orchestration import OrchestrationAdapter


class TestImportBoundary:
    #: 显式豁免清单：langgraph 互操作 adapter（LangMem 可选 provider 经
    #: langgraph.store BaseStore 协议对接记忆存储——非编排用途，且仅由可选
    #: 路径导入，Core 零依赖）。新增豁免必须在此登记并说明用途。
    ALLOWED_LANGGRAPH_IMPORTS = frozenset({
        Path("agent_harness") / "memory" / "base_store_adapter.py",
    })

    def test_core_never_imports_langgraph(self):
        """不变量 #20：编排零依赖 langgraph——全 src 树扫描（spec §13 验收）。

        唯一豁免 = memory 的 LangGraph BaseStore 互操作 adapter（LangMem
        可选 provider 专用，Core 从不导入）。"""
        src_root = Path(__file__).resolve().parents[2] / "src"
        violations: list[str] = []
        for py in src_root.rglob("*.py"):
            rel = py.relative_to(src_root)
            if rel in self.ALLOWED_LANGGRAPH_IMPORTS:
                continue
            text = py.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith(("#", '"', "'")):
                    continue
                if "langgraph" in stripped and stripped.startswith(("import ", "from ")):
                    violations.append(f"{rel}:{lineno}")
        assert violations == []

    def test_langgraph_not_installed_in_ci_env(self):
        """CI 环境无 langgraph 也必须全绿（当前环境即证：import 失败即环境不符）。"""
        try:
            import langgraph  # noqa: F401

            pytest.skip("langgraph 已安装——本环境非最小 Core 口径")
        except ImportError:
            pass


class TestAdapterProtocol:
    def test_protocol_shape_documented(self):
        """协议位存在且 docstring 声明三契约（可序列化 state / 不替代 Ledger /
        节点走既有 AgentRuntime）。"""
        doc = OrchestrationAdapter.__doc__ or ""
        assert "AgentRuntime" in doc
        assert "Operation Ledger" in doc
        assert "可序列化" in doc

    def test_adapter_implementation_is_swappable(self):
        """任何实现（含未来的 LangGraph 图）只需满足协议即可接入。"""

        class _NoopAdapter:
            async def run_graph(self, state, *, delegate):
                return {**state, "visited": True}

        from agent_harness.orchestration import OrchestrationAdapter as Adapter

        assert isinstance(_NoopAdapter(), Adapter)
