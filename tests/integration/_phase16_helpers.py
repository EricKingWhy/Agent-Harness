"""Phase 16 Final Full E2E 链路 helper（ADR-0019 D7/D10）。

E2E 链路专用：ScriptedModel 关键路径剧本构造 + fake provider 组合套件。
同 `_kill_child.py` 先例——phase gate 文件依赖的共享 helper 放这里，不在
gate 文件里重复。混合 fixture 策略（D10）：单元级 fake provider 直接 import
复用，E2E 编排剧本（多轮预设回复）新建在本 helper。

薄编排层（D1）的关键路径剧本共 4 轮：
1. retrieve_knowledge（KB 证据不足 is_sufficient=false）
2. web_search（外部检索，带 citation）
3. add（coding 代理工具，走统一 ToolExecutor）
4. 模型给最终回答，引用 web 来源

deterministic + 零网络 + 零 token（同 Phase 15 ScriptedModel + fake provider 模式）。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage

from agent_harness.identity import IdentityContext, set_identity_context
from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
from agent_harness.knowledge.service import KnowledgeService
from agent_harness.knowledge.store import FakeKnowledgeVectorStore
from agent_harness.knowledge.tools import RetrieveKnowledgeTool
from agent_harness.model.scripted import ScriptedModel
from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.storage import SqliteOperationLedger
from agent_harness.tooling import (
    ApprovalResponse,
    ToolExecutor,
    ToolRegistry,
)
from agent_harness.tools import BashTool, EditTool, ReadTool, WriteTool
from agent_harness.websearch.fake import FakeWebSearchProvider
from agent_harness.websearch.tools import WebSearchTool
from evaluation.support import AddTool

# E2E 链路使用的固定身份（同 tests/knowledge/test_tools.py ALICE 风格）。
# 用固定 tenant/user 让 KB 检索的 fake store 命中预置 chunk（不依赖真
# IdentityContext 绑定——只在调 service.retrieve 时经 get_identity_context 取到）。
PHASE16_TENANT = "phase16"
PHASE16_USER = "e2e"
PHASE16_IDENTITY = IdentityContext(PHASE16_TENANT, PHASE16_USER, ["user", "session"])

# 关键路径引用的 web URL（剧本里 citation 引用、断言里校验格式）。
PHASE16_WEB_URL = "https://docs.python.org/3/"


def critical_path_scripted_model() -> ScriptedModel:
    """薄编排层用的 ScriptedModel（4 轮简化链路，ADR-0019 D1）。

    第 1 轮：模型判断需要 KB 证据 → 调 retrieve_knowledge（fake store 返回不足）
    第 2 轮：KB 不足 → 模型按 Retrieval Fallback affordance 调 web_search（带 citation）
    第 3 轮：模型顺带做一次 coding 代理计算 → 调 add（统一 ToolExecutor 路径）
    第 4 轮：模型给最终回答，文本里含 web citation（引用来源可追溯）
    """
    return ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{
                "id": "phase16-kb",
                "name": "retrieve_knowledge",
                "args": {"query": "python typing 类型标注"},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "phase16-web",
                "name": "web_search",
                "args": {"query": "Python asyncio 官方文档"},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "phase16-add",
                "name": "add",
                "args": {"first_number": 1, "second_number": 2},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content=f"答案参见 web:{PHASE16_WEB_URL}；合计 3。",
        ),
    ])


async def build_critical_path_registry(tmp_path: Path) -> ToolRegistry:
    """组装关键路径用的 ToolRegistry（KB + Web + Add 三工具，全 fake provider）。

    KB 走 FakeKnowledgeVectorStore（空语料 → is_sufficient=False，编排层据此
    证明 Retrieval Fallback affordance 链路）；Web 走 FakeWebSearchProvider（
    默认 demo 文档命中 Python 官方文档，citation=web:<url>）；Add 是评测域
    确定性求和工具。registry 初始化期绑定身份到 ContextVar，让 KB retrieve
    工具经 get_identity_context() 取到本 E2E 的 tenant。
    """
    # 绑定身份 ContextVar：Knowledge 工具的 _identity() 取这个值。
    # token 不 reset——本 helper 是测试体内一次性 setup，进程级隔离。
    set_identity_context(PHASE16_IDENTITY)

    registry = ToolRegistry()
    # KB：空 fake store（不预 ingest）→ retrieve 返回空 hits → is_sufficient=False
    kb_registry = SqliteKnowledgeSourceRegistry(tmp_path / "phase16_harness.db")
    await kb_registry.initialize()
    kb_service = KnowledgeService(
        store=FakeKnowledgeVectorStore(),
        registry=kb_registry,
        min_score=0.6,
    )
    registry.register(RetrieveKnowledgeTool(kb_service))
    # Web：默认 demo 文档（含 Python 官方文档，substring 命中评分）
    registry.register(WebSearchTool(FakeWebSearchProvider()))
    # Coding 代理：评测域确定性求和工具
    registry.register(AddTool())
    return registry


# ─── T2：research / KB insufficient / web / citation / permission 分段断言 ────
# 这些 helper 只服务 T2，不污染薄编排层 critical path（ADR-0019 D1 分段独立）。


async def build_kb_seeded_registry(
    tmp_path: Path,
    *,
    seeded_identity: IdentityContext | None = None,
) -> tuple[ToolRegistry, KnowledgeService, str]:
    """组装一个 KB 预置低相关度语料 + Web 默认 demo 文档的 registry（T2 用）。

    返回 (registry, kb_service, seeded_source_name)。调用方可以拿 kb_service 去
    `read_source(citation=...)` 反查 KB chunk（citation validity Gate 的"可查"维度）。

    预置策略：摄入一段完全不沾 query 关键词的文本作为 source `legacy-guide`，
    让 T2 用 `python typing` 这类 query 检索时命中空 → is_sufficient=False。
    这是诚实语义而非 fake hook——证明 KB 不足信号走的是真实的 store.search +
    service.retrieve 路径。
    """
    identity = seeded_identity or PHASE16_IDENTITY
    set_identity_context(identity)

    registry = ToolRegistry()
    kb_registry = SqliteKnowledgeSourceRegistry(tmp_path / "phase16_t2_harness.db")
    await kb_registry.initialize()
    kb_store = FakeKnowledgeVectorStore()
    kb_service = KnowledgeService(
        store=kb_store, registry=kb_registry, min_score=0.6,
    )
    # 摄入一段与 T2 query（python typing）零词重叠的文本 → retrieve 必然命中空。
    await kb_service.ingest(
        text="本指南记录团队 2019 年度团建行程安排与餐饮偏好。",
        source_name="legacy-guide", identity=identity,
    )
    registry.register(RetrieveKnowledgeTool(kb_service))
    registry.register(WebSearchTool(FakeWebSearchProvider()))
    return registry, kb_service, "legacy-guide"


def build_permission_registry(sandbox: LocalSubprocessSandbox) -> ToolRegistry:
    """组装 BashTool(DANGER) + ReadTool(READ_ONLY) 的 registry（T2 permission 分段用）。

    BashTool 默认 permission=DANGER，在默认 WORKSPACE_WRITE policy + 无审批回调下
    会被 approval gate 拒绝 → PERMISSION_DENIED；ReadTool 是 READ_ONLY 永远放行。
    这是 ToolExecutor 的真实审批路径（同 tests/tooling/test_approval_gate.py 模式），
    不是 fake stub。
    """
    registry = ToolRegistry()
    registry.register(BashTool(sandbox))
    registry.register(ReadTool(sandbox))
    return registry


def kb_insufficient_then_web_script() -> ScriptedModel:
    """T2 用剧本：KB 证据不足 → web 补齐 → 最终回答含 web citation。

    与薄编排层剧本的差异：第 3 轮不再调 add，而是直接给最终回答，让分段断言
    聚焦在 research→KB→web→citation 这一条链路（ADR-0019 D1 分段独立原则）。
    """
    return ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t2-kb",
                "name": "retrieve_knowledge",
                "args": {"query": "python typing 类型标注"},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t2-web",
                "name": "web_search",
                "args": {"query": "Python asyncio 官方文档"},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content=f"答案参见 web:{PHASE16_WEB_URL}。",
        ),
    ])


def permission_violation_script() -> ScriptedModel:
    """T2 permission 剧本：越权 bash 被拦 → 改走合法 read → 最终回答。

    第 1 轮：模型试图跑 bash（DANGER，无审批回调会被拒）
    第 2 轮：被拒后改用 read（READ_ONLY，永远放行）读合法 workspace 文件
    第 3 轮：基于 read 结果给最终回答

    这个剧本证明 ADR-0019 D8 permission violation Gate：
    - 显式越权尝试被 PERMISSION_DENIED 拦下
    - 同一链路里合法调用照常执行（不是"一被拦全链崩"）
    """
    return ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t2-bash",
                "name": "bash",
                "args": {"command": "echo violating"},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t2-read",
                "name": "read",
                "args": {"path": "notes.txt"},
                "type": "tool_call",
            }],
        ),
        AIMessage(content="已读取 workspace 文件并据此回答。"),
    ])


# ─── T3 #128：coding / edit / test-failure / mutating-tool 分段断言 ──────────


def _auto_approve(_req) -> ApprovalResponse:
    """测试用统一自动审批回调（BashTool DANGER 必须有 callback 才能执行）。"""
    return ApprovalResponse(approved=True, reason="phase16-t3-auto-approve")


def build_coding_registry(sandbox: LocalSubprocessSandbox) -> ToolRegistry:
    """T3 coding 分段用的 registry：WriteTool + EditTool + BashTool（全 MUTATING）。

    WriteTool/EditTool 是 WORKSPACE_WRITE（默认 policy 下不需审批）；
    BashTool 是 DANGER，必须配 approval_callback（测试用 _auto_approve）。
    """
    registry = ToolRegistry()
    registry.register(WriteTool(sandbox))
    registry.register(EditTool(sandbox))
    registry.register(BashTool(sandbox))
    return registry


def build_coding_executor(
    sandbox: LocalSubprocessSandbox,
    ledger: SqliteOperationLedger,
) -> ToolExecutor:
    """T3 coding 执行器：registry + Ledger + auto-approve（BashTool DANGER 放行）。"""
    return ToolExecutor(
        build_coding_registry(sandbox),
        operation_ledger=ledger,
        approval_callback=_auto_approve,
    )


def coding_failure_then_fix_script() -> ScriptedModel:
    """T3 coding 剧本：写失败测试 → 跑测试（exit_code=1）→ 修成通过 → 重跑通过 → 最终回答。

    证明 ADR-0002：bash 非零退出是确定性失败（ok=True），不触发 ToolExecutor 重试；
    模型据此调整策略（覆写测试文件）而非原地重试同一条命令。

    4 轮 bash 调用（跨平台：用 python -c 写文件，避免 echo 单/双引号在 Windows
    cmd 下的转义差异；跑测试也用 python -c 直接 exec + 调函数，零外部依赖）：
    1. write 失败测试文件
    2. 跑测试 → exit_code=1（AssertionError）
    3. write 通过测试文件
    4. 重跑测试 → exit_code=0
    """
    # 跨平台写文件：python -c 内 open(..., 'w').write(...) 不依赖 shell 引号语义。
    write_fail_cmd = (
        'python -c "open(\'test_fail.py\', \'w\').write(\'def test_x(): assert False\\n\')"'
    )
    write_pass_cmd = (
        'python -c "open(\'test_fail.py\', \'w\').write(\'def test_x(): assert True\\n\')"'
    )
    # 跑测试：exec 测试文件到独立命名空间，再调 test_x()；零依赖 pytest。
    run_cmd = (
        'python -c "ns={}; exec(open(\'test_fail.py\').read(), ns); ns[\'test_x\']()"'
    )
    return ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t3-write-fail",
                "name": "bash",
                "args": {"command": write_fail_cmd},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t3-run-fail",
                "name": "bash",
                "args": {"command": run_cmd},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t3-write-pass",
                "name": "bash",
                "args": {"command": write_pass_cmd},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t3-run-pass",
                "name": "bash",
                "args": {"command": run_cmd},
                "type": "tool_call",
            }],
        ),
        AIMessage(content="测试已修好并通过。"),
    ])


def mutating_tool_ledger_script() -> ScriptedModel:
    """T3 mutating-tool Ledger 剧本：write 新文件 → edit 改内容 → 最终回答。

    两次 MUTATING 工具调用，验证 Ledger 对每次副作用都有 PENDING → SUCCEEDED 流转记录，
    且文件系统副作用真实持久化（write 创建 + edit 替换字符串都生效）。
    """
    return ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t3-write",
                "name": "write",
                "args": {"path": "doc.md", "content": "原始草稿。待编辑。"},
                "type": "tool_call",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "t3-edit",
                "name": "edit",
                "args": {
                    "path": "doc.md",
                    "old_string": "待编辑。",
                    "new_string": "已编辑完成。",
                },
                "type": "tool_call",
            }],
        ),
        AIMessage(content="文档已写好并编辑完成。"),
    ])
