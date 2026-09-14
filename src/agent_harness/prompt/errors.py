"""Prompt 域显式错误词汇表（PRD §10.3）。

形制照抄 `capability/base.py` 的 `CapabilityError`——全项目既有约定是**单一
异常类 + code 字段**，不要为每种失败发明一个异常类型。测试按 `code` 断言。

`code` 取值：`duplicate_section` / `invalid_section_name` / `invalid_scope` /
`invalid_variable_name` / `undefined_variable` / `template_syntax` /
`missing_variable` / `missing_identity` / `empty_assembly` /
`invalid_persona_config`（T5，形制照抄 `parse_capabilities_config`）。
"""

from __future__ import annotations

__all__ = ["PromptError"]


class PromptError(RuntimeError):
    """所有 prompt 校验/组装失败的统一异常，用 `code` 区分具体原因。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
