"""memory 领域的异常词汇（web 层用它做 HTTP 翻译，见 `web/domain_errors.py`）。

为什么单独一个模块：`memory` 包不依赖传输层（不变量：领域层不知道 HTTP），所以
"目标不存在"这种领域事实必须有自己的异常类型，由 web 层决定它对应哪个状态码。

为什么 `forget` 不抛这个异常：`forget(memory_id) -> bool` 的契约（#156 冻结）是
"id 不存在 → 幂等 False，不是错误"——后台路径（writeback/整合）反复遗忘同一条记忆是
正常的事。把 False 显式化成异常是**入口层**的选择：用户对着一个具体 id 点"删除"，
"这条不存在"对他来说是一个要报出来的结果（404），而不是静默成功。
"""


class MemoryDomainError(Exception):
    """memory 领域异常基类（web 层按类型精确映射状态码）。"""


class SessionBindingMissing(ValueError):
    """SESSION scope 需要可信会话绑定，而当前上下文没有。

    **刻意是 `ValueError`**（#156 起的语义：这是"调用方少给了一个绑定"，不是归属判定），
    并且**刻意不是 `MemoryDomainError`**——它不需要被翻译成 HTTP 状态码，所以不该进
    `web/domain_errors.py` 的映射表。唯一需要区分它的地方是 `types.row_namespace_matches`：
    那里"这一行的 namespace 解析不出"要转成归属拒绝（→ `PermissionError`）。类型化之后那个
    `except` 不必再裸接 `ValueError`（否则 `of()` 里将来任何无关的 ValueError 都会被静默吞掉）。
    """


class MemoryNotFound(MemoryDomainError):
    """按 id 操作的目标不存在（`forget` 返回 False 在入口层的显式化）。"""

    def __init__(self, memory_id: str) -> None:
        self.memory_id = memory_id
        super().__init__(f"记忆不存在：{memory_id}")
