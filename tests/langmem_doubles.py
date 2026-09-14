"""langmem / trustcall 测试替身的共用形状（`tests/` 下多个文件复用，避免副本各自漂移）。

trustcall 在"**存在既有文档**"的分支里访问 `self.bound.bound.bind_tools(...)`：它假设
`bind_tools` 返回 `RunnableBinding`，`.bound` 才是底层模型。该分支只有在
`enable_deletes=True`（#157 解禁删除）且检索命中既有记忆时才走到——真实模型天然满足这个形状，
假模型必须显式模拟，否则删除/更新路径会在假模型上 AttributeError，而生产完全正常。

为什么不用项目自己的 `ScriptedModel`：trustcall 把 prompt 与模型用 `|` 组成 chain，
必须是真 LangChain Runnable；`src/agent_harness/model/scripted.py` 的替身只是鸭子类型，
没有 `__or__`。所以这里继承 `FakeMessagesListChatModel`。
"""

import uuid
from typing import ClassVar

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.types import MemoryNamespace

#: `langmem` 生成检索 query 那次调用的 prompt 特征（`extraction.py` 的 `query_gen` 分支）。
#: 给了 `query_model` 才有这次调用；它产出的是**搜索工具调用**，不是记忆决策。
QUERY_GENERATION_MARKER = "Use parallel tool calling"

#: 决策阶段（trustcall）prompt 的特征。**必须做反向判别**：候选正文整段会被塞进决策 prompt，
#: 一条内容里恰好带上面那句话的记忆，会让只做正向匹配的判别把**决策**调用认成 query 生成
#: ——测试就静默地测了别的相位（code-review N2）。
DECISION_PROMPT_MARKER = "memory subroutine"


def _is_query_generation(messages) -> bool:
    """这次调用是"生成检索 query"（而非"决策 insert/update/delete"）吗？"""
    text = " ".join(str(getattr(message, "content", "")) for message in messages)
    return QUERY_GENERATION_MARKER in text and DECISION_PROMPT_MARKER not in text


class BoundSelfMixin:
    """`bind_tools` 无副作用，`bound` 指回自身（等价于"绑定无副作用的模型"）。

    trustcall 会 bind 自己的工具集；真模型换成假模型后，绑定不得真去改什么状态。
    """

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def bound(self):
        return self


class QueryGenerationMixin:
    """自动应答"生成检索 query"那次调用，让脚本响应仍然只对应**决策**阶段。

    `#158` 起 manager 用**同一个模型**生成检索 query（`query_model=model`，AC1 选的路线），
    于是每次写入有两段 LLM 调用：①生成"假想记忆"当 query（`query_gen` 分支）→ ②拿检索结果
    做决策。假模型若不给①一个形状正确的回答，脚本响应就会被①吃掉，测试测的就不是生产路径
    （实测：错位后①把决策的参数当成搜索参数传下去，直接 `TypeError`）。

    上游只取 `tc["args"]`（不校验工具名），所以这里返回一条带 `query` 的搜索工具调用即可。
    """

    _QUERY_GENERATION_TOOL_CALL: ClassVar[dict] = {
        "name": "search_memory",
        "args": {"query": "与当前对话相关的用户长期记忆"},
        "id": "query-gen",
    }

    def _query_generation_result(self) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="", tool_calls=[dict(self._QUERY_GENERATION_TOOL_CALL)]))])


class ScriptedChatModel(QueryGenerationMixin, BoundSelfMixin, FakeMessagesListChatModel):
    """按序吐预置响应的 LangChain 假模型；`responses=` 语义同基类（只对应**决策**阶段）。"""

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        if _is_query_generation(messages):
            return self._query_generation_result()
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        if _is_query_generation(messages):
            return self._query_generation_result()
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class HangingChatModel(QueryGenerationMixin, BoundSelfMixin, FakeMessagesListChatModel):
    """**决策阶段**永久卡住的假模型（检索 query 生成照常应答）。

    #158 的"预算到期 → 降级写入"路径需要它在**检索之后**卡住：检索已经发生（开销已付出），
    决策还没返回。空 `responses=` 的 `ScriptedChatModel` 达不到这个形状——它立刻 IndexError，
    预算根本到不了期；而检索 query 生成若也卡住，则连检索都不会发生，测的是另一个形状。
    """

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        import asyncio

        if _is_query_generation(messages):
            return self._query_generation_result()
        await asyncio.sleep(30)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        raise RuntimeError("HangingChatModel 只用于异步路径")


class AlwaysHitVectorStore(FakeVectorStore):
    """`search` 命中本 namespace 的**全部** key（真实 embedding 语义匹配的替身）。

    manager 内部的检索查询是**对话窗口文本**（`get_dialated_windows`），真实 embedding 下它与既有
    记忆是语义匹配；`FakeVectorStore` 是单向字面匹配（query ⊆ content），长窗口查询永远命中不了短
    记忆，会把"删除/更新链路"堵在检索那一步（而"检索得到既有记忆"正是这两条路径的前提：trustcall
    只在 `existing` 非空时才绑定 RemoveDoc，`PatchDoc` 也只在既有文档里找得到目标）。
    查询生成与检索策略是 #158 的范围，这里只让"检索得到"成立，其余（RemoveDoc 的 id 校验、
    adelete/aput → adapter → 记录库）全部走真实实现。

    副作用需要显式容忍：命中集合会包含"记录行已删、索引还没收敛"的 id —— 这正是 provider 删除被
    解禁后新出现的窗口，生产代码在 adapter 的 SearchOp 与能力层的检索里都跳过这类行。
    """

    async def search(self, query, identity, scope, limit):  # type: ignore[override]
        if not query:
            return []
        namespace = MemoryNamespace.of(scope, identity).as_tuple()
        return [(key, 1.0) for (ns, key) in self._rows if ns == namespace][: max(0, limit)]


def stable_doc_id(memory_id: str, namespace: tuple[str, ...]) -> str:
    """LangMem 认的文档 id（`MemoryStoreManager._stable_id` 的同一公式）。

    manager 只允许删"它自己检索回来的那些 id"，检索结果以这个 uuid5 为键，
    所以脚本化 `RemoveDoc` / `PatchDoc` 时必须给出同一个值。
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, str((*namespace, memory_id))).hex
