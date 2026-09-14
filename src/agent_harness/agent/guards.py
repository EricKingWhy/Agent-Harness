"""RepeatedToolFailureGuard — AgentRuntime 的同错熔断护栏（ADR-0014 决策 2-6）。

检测模型在工具受限环境下反复重试同一失败工具（#69）：
- 指纹 = (tool_name, canonical args)；连续 N=3 次同指纹 ok=False → 软熔断
  （注入 user 角色纠正消息，给模型一次自纠机会）；
- 再 N=3 仍同指纹失败 → 硬熔断（end_run failed）。
- 计数器仅在指纹变化时清零（Q12 选项 b：成功不重置——振荡场景每个指纹
  各自计数更公平，堵住「碰巧成功一次就洗计数」的绕过路径）。

无上游蓝图：pi-mono / oh-my-pi / claude-code 都没有工具失败检测。
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass


class GuardLevel(enum.IntEnum):
    """护栏动作级别（IntEnum 便于 max() 比较）。"""

    NONE = 0
    SOFT = 1
    HARD = 2


@dataclass(frozen=True)
class GuardSignal:
    """observe() 的返回：本轮观察到的最严重动作 + 诊断字段。"""

    level: GuardLevel
    tool_name: str
    fingerprint: str
    consecutive_failures: int


class RepeatedToolFailureGuard:
    """跟踪连续同指纹工具失败，在阈值触发软/硬两级熔断。

    状态机：fingerprint 变化 → 重置计数 + soft_triggered；
    成功 → 不重置（Q12 b）；失败 → 计数++，按阈值判定。
    """

    def __init__(self, *, soft_threshold: int = 3, hard_threshold: int = 3) -> None:
        self._soft_threshold = soft_threshold
        self._hard_threshold = hard_threshold
        self._fingerprint: str | None = None
        self._consecutive_failures = 0
        self._soft_triggered = False

    @staticmethod
    def make_fingerprint(tool_name: str, args: dict) -> str:
        """规范化指纹：tool_name + 排序 JSON（key 顺序无关、Unicode 不转义）。"""
        return f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"

    def observe(self, tool_name: str, args: dict, ok: bool) -> GuardSignal:
        """喂入一次工具结果，返回本轮该不该触发动作。"""
        fp = self.make_fingerprint(tool_name, args)
        if fp != self._fingerprint:
            self._fingerprint = fp
            self._consecutive_failures = 0
            self._soft_triggered = False

        if ok:
            return GuardSignal(GuardLevel.NONE, tool_name, fp, self._consecutive_failures)

        self._consecutive_failures += 1

        if not self._soft_triggered and self._consecutive_failures >= self._soft_threshold:
            self._soft_triggered = True
            return GuardSignal(GuardLevel.SOFT, tool_name, fp, self._consecutive_failures)

        if self._soft_triggered and self._consecutive_failures >= self._soft_threshold + self._hard_threshold:
            return GuardSignal(GuardLevel.HARD, tool_name, fp, self._consecutive_failures)

        return GuardSignal(GuardLevel.NONE, tool_name, fp, self._consecutive_failures)

    def reset(self) -> None:
        """手动重置（如新一轮 run 开始时）。"""
        self._fingerprint = None
        self._consecutive_failures = 0
        self._soft_triggered = False
