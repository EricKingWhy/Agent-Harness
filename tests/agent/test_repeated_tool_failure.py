"""RepeatedToolFailureGuard 单元测试（T1, #76, ADR-0014）。"""

from __future__ import annotations

from agent_harness.agent.guards import GuardLevel, RepeatedToolFailureGuard


class TestRepeatedToolFailureGuard:
    """纯状态机测试——不涉及 AgentRuntime 注入。"""

    def test_no_action_on_success(self):
        guard = RepeatedToolFailureGuard()
        signal = guard.observe("bash", {"command": "ls"}, ok=True)
        assert signal.level == GuardLevel.NONE

    def test_no_action_below_soft_threshold(self):
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        signal = guard.observe("bash", {"command": "ls"}, ok=False)
        assert signal.level == GuardLevel.NONE
        assert signal.consecutive_failures == 1

    def test_soft_after_3_consecutive_same_fingerprint_failures(self):
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        signal = None
        for _ in range(3):
            signal = guard.observe("bash", {"command": "ls"}, ok=False)
        assert signal.level == GuardLevel.SOFT
        assert signal.consecutive_failures == 3

    def test_hard_after_6_consecutive_same_fingerprint_failures(self):
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        signal = None
        for _ in range(6):
            signal = guard.observe("bash", {"command": "ls"}, ok=False)
        assert signal.level == GuardLevel.HARD
        assert signal.consecutive_failures == 6

    def test_intermediate_signals_between_soft_and_hard_are_none(self):
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        signals = [
            guard.observe("bash", {"command": "ls"}, ok=False) for _ in range(6)
        ]
        assert signals[2].level == GuardLevel.SOFT  # 3rd failure
        assert signals[3].level == GuardLevel.NONE  # 4th — not yet hard
        assert signals[4].level == GuardLevel.NONE  # 5th
        assert signals[5].level == GuardLevel.HARD  # 6th

    def test_fingerprint_change_resets_counter(self):
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        guard.observe("bash", {"command": "ls"}, ok=False)
        guard.observe("bash", {"command": "ls"}, ok=False)
        signal = guard.observe("bash", {"command": "pwd"}, ok=False)
        assert signal.level == GuardLevel.NONE  # reset
        assert signal.consecutive_failures == 1  # fresh count

    def test_different_tool_name_resets(self):
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        guard.observe("bash", {"command": "ls"}, ok=False)
        guard.observe("bash", {"command": "ls"}, ok=False)
        signal = guard.observe("read", {"path": "a.txt"}, ok=False)
        assert signal.level == GuardLevel.NONE
        assert signal.consecutive_failures == 1

    def test_success_does_not_reset_counter(self):
        """Q12 选项 b：成功不重置——只有指纹变化才清零。"""
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        guard.observe("bash", {"command": "ls"}, ok=False)
        guard.observe("bash", {"command": "ls"}, ok=False)
        guard.observe("bash", {"command": "ls"}, ok=True)  # success — no reset
        signal = guard.observe("bash", {"command": "ls"}, ok=False)
        assert signal.level == GuardLevel.SOFT
        assert signal.consecutive_failures == 3

    def test_args_key_order_independent_fingerprint(self):
        """排序 JSON → key 顺序不同但语义相同的 args 视为同一指纹。"""
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        guard.observe("edit", {"path": "a", "content": "b"}, ok=False)
        signal = guard.observe("edit", {"content": "b", "path": "a"}, ok=False)
        assert signal.consecutive_failures == 2

    def test_unicode_args_in_fingerprint(self):
        """ensure_ascii=False → CJK args 正常归一化不转义。"""
        guard = RepeatedToolFailureGuard(soft_threshold=2, hard_threshold=2)
        guard.observe("retrieve_knowledge", {"query": "知识库检索"}, ok=False)
        signal = guard.observe("retrieve_knowledge", {"query": "知识库检索"}, ok=False)
        assert signal.level == GuardLevel.SOFT

    def test_hard_after_soft_then_3_more_failures(self):
        """软触发后，再连续 3 次同指纹失败 → 硬。"""
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        for _ in range(3):
            guard.observe("bash", {"command": "fail"}, ok=False)  # SOFT at 3rd
        signal = None
        for _ in range(3):
            signal = guard.observe("bash", {"command": "fail"}, ok=False)
        assert signal.level == GuardLevel.HARD

    def test_soft_triggered_flag_persists_across_success(self):
        """软触发后即使中间有一次成功，仍需累计到 hard 阈值（count=6 时 HARD）。"""
        guard = RepeatedToolFailureGuard(soft_threshold=3, hard_threshold=3)
        for _ in range(3):
            guard.observe("bash", {"command": "fail"}, ok=False)  # SOFT at 3rd, count=3
        guard.observe("bash", {"command": "fail"}, ok=True)  # success — no reset, count stays 3
        guard.observe("bash", {"command": "fail"}, ok=False)  # count=4
        guard.observe("bash", {"command": "fail"}, ok=False)  # count=5
        signal = guard.observe("bash", {"command": "fail"}, ok=False)  # count=6 -> HARD
        assert signal.level == GuardLevel.HARD

    def test_reset_clears_all_state(self):
        guard = RepeatedToolFailureGuard(soft_threshold=2, hard_threshold=2)
        for _ in range(2):
            guard.observe("bash", {"command": "x"}, ok=False)  # SOFT
        guard.reset()
        signal = guard.observe("bash", {"command": "x"}, ok=False)
        assert signal.level == GuardLevel.NONE
        assert signal.consecutive_failures == 1

    def test_default_thresholds(self):
        """默认 soft=3, hard=3（总 6 次连续同指纹失败 → HARD）。"""
        guard = RepeatedToolFailureGuard()
        assert guard._soft_threshold == 3
        assert guard._hard_threshold == 3
