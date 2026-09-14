"""测试替身再导出（Phase 15 升格：实现移至 src/agent_harness/model/scripted.py，
eval runner 与测试共用同一确定性 seam——ADR-0018 D10）。"""

from agent_harness.model.scripted import RequestSnapshot, ScriptedModel

__all__ = ["RequestSnapshot", "ScriptedModel"]
