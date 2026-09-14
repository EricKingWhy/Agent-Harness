"""T2 #118：RunTracer——run/model call 生命周期 → Langfuse trace/generation（ADR-0018 D5/D6/D7）。

映射（不发明第二套 trace identity）：Langfuse trace 根 = 一次 agent run
（name=agent-run、input=用户消息、metadata=run_id/agent_id/git_commit），
generation = 每次 model call（usage/latency/fallback 履历）。内容边界：
full=原样；redacted=截断。所有 span 操作零伪造、零抛出。
"""

from __future__ import annotations

from agent_harness.observability import LangfuseSink
from agent_harness.observability.tracer import RunTracer


class FakeSpan:
    def __init__(self, recorder: FakeRecorder, *, name: str, kind: str, kwargs: dict):
        self._recorder = recorder
        self.name = name
        self.kind = kind
        self.kwargs = kwargs
        self.updates: list[dict] = []
        self.ended = False
        self.children: list[FakeSpan] = []
        self.trace_id = recorder.next_trace_id
        recorder.spans.append(self)

    def start_observation(self, *, name: str, as_type: str = "span", **kwargs):
        child = FakeSpan(
            self._recorder, name=name, kind=as_type, kwargs=kwargs,
        )
        self.children.append(child)
        return child

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def end(self):
        self.ended = True


class FakeRecorder:
    def __init__(self):
        self.spans: list[FakeSpan] = []
        self.next_trace_id = "tr-fake-001"
        self.trace_url_template = (
            "https://cloud.langfuse.com/project/proj-trace-{trace_id}/traces/{trace_id}"
        )

    def client(self):
        recorder = self

        class _Client:
            def start_observation(self, *, name: str, as_type: str = "span", **kwargs):
                return FakeSpan(recorder, name=name, kind=as_type, kwargs=kwargs)

            def get_trace_url(self, *, trace_id):
                if trace_id is None:
                    return None
                return recorder.trace_url_template.format(trace_id=trace_id)

        return _Client()


def _tracer(recorder: FakeRecorder, *, trace_content: str = "full") -> RunTracer:
    sink = LangfuseSink(
        public_key="pk", secret_key="sk", base_url="https://example.invalid",
        trace_content=trace_content,
        client_factory=lambda **kwargs: recorder.client(),
    )
    assert sink.enabled
    return RunTracer(
        sink, session_id="sess-1", run_id="run-1", agent_id="default",
        user_input="计算 1+2",
    )


def test_run_started_creates_root_with_identity_metadata():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)

    tracer.run_started()

    assert tracer.trace_id == "tr-fake-001"
    root = recorder.spans[0]
    assert root.name == "agent-run"
    assert root.kwargs["input"] == "计算 1+2"
    meta = root.kwargs["metadata"]
    assert meta["session_id"] == "sess-1"
    assert meta["run_id"] == "run-1"
    assert meta["agent_id"] == "default"
    assert "git_commit" in meta  # 有值或键存在（CI/异常环境如实缺失）


def test_turn_index_passed_to_trace_metadata():
    """T9 #139：turn_index 出现在 trace metadata。"""
    recorder = FakeRecorder()
    tracer = RunTracer(
        LangfuseSink(
            public_key="pk", secret_key="sk", base_url="https://example.invalid",
            client_factory=lambda **kwargs: recorder.client(),
        ),
        session_id="sess-1", run_id="run-1", agent_id="default",
        user_input="hi", turn_index=3,
    )

    tracer.run_started()

    meta = recorder.spans[0].kwargs["metadata"]
    assert meta["turn_index"] == 3


def test_model_call_generation_mapping_and_usage_translation():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    root = recorder.spans[0]

    gen = tracer.model_call_started(step=1, messages=[{"role": "user", "content": "hi"}])
    tracer.model_call_completed(
        gen,
        output_text="1+2=3",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        duration_ms=123,
        fallback_transitions=[],
    )

    assert root.children, "generation 必须嵌套在 run 根观测下"
    gen_span = root.children[0]
    assert gen_span.kind == "generation"
    assert gen_span.kwargs["input"] == [{"role": "user", "content": "hi"}]
    assert gen_span.ended
    update = gen_span.updates[-1]
    assert update["output"] == "1+2=3"
    # 项目 usage 键 → Langfuse usage_details 键（input/output/total）
    assert update["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert update["metadata"]["duration_ms"] == 123


def test_fallback_transitions_recorded_on_generation():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    root = recorder.spans[0]
    gen = tracer.model_call_started(step=1, messages=[])

    class _T:
        from_model, to_model, reason = "primary-a", "fallback-b", "ModelStallError"

    tracer.model_call_completed(
        gen, output_text="x", usage=None, duration_ms=1,
        fallback_transitions=[_T()],
    )
    meta = root.children[0].updates[-1]["metadata"]
    assert meta["fallback_from"] == "primary-a"
    assert meta["fallback_to"] == "fallback-b"
    assert meta["fallback_reason"] == "ModelStallError"
    assert "usage_details" not in root.children[0].updates[-1]  # 零伪造：无 usage 不造


def test_model_call_with_tool_calls_writes_marker_when_output_empty():
    """Gap 5（D7 DEFER 批）：模型返回 tool_calls 但 content 空——generation output
    不应是 None/空，写结构化标记让 Langfuse UI 可读（tool_calls 轮可见）。"""
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    root = recorder.spans[0]
    gen = tracer.model_call_started(step=1, messages=[{"role": "user", "content": "hi"}])
    tracer.model_call_completed(
        gen,
        output_text="",
        tool_call_names=["add", "search"],
        usage={"total_tokens": 5},
    )
    update = root.children[0].updates[-1]
    assert update["output"], "tool_calls 轮 output 不应空白"
    assert "add" in update["output"]
    assert "search" in update["output"]


def test_model_call_with_content_ignores_tool_calls_marker():
    """正常回答轮（有 content）不写 tool_calls 标记——标记仅兜底空 content。"""
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    root = recorder.spans[0]
    gen = tracer.model_call_started(step=1, messages=[])
    tracer.model_call_completed(
        gen, output_text="最终回答", tool_call_names=["add"], usage=None,
    )
    update = root.children[0].updates[-1]
    assert update["output"] == "最终回答"  # 不被标记污染


def test_model_call_failed_marks_error_and_ends():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    root = recorder.spans[0]
    gen = tracer.model_call_started(step=1, messages=[])

    tracer.model_call_failed(gen, error_type="ModelStallError")

    update = root.children[0].updates[-1]
    assert update["level"] == "ERROR"
    assert root.children[0].ended


def test_redacted_mode_truncates_content_full_mode_preserves():
    long_text = "x" * 2000

    def _tracer_with_input(recorder: FakeRecorder, trace_content: str) -> RunTracer:
        sink = LangfuseSink(
            public_key="pk", secret_key="sk", base_url="https://example.invalid",
            trace_content=trace_content,
            client_factory=lambda **kwargs: recorder.client(),
        )
        return RunTracer(
            sink, session_id="s", run_id="r", agent_id="a", user_input=long_text,
        )

    recorder_full = FakeRecorder()
    _tracer_with_input(recorder_full, "full").run_started()
    assert recorder_full.spans[0].kwargs["input"] == long_text

    recorder_red = FakeRecorder()
    _tracer_with_input(recorder_red, "redacted").run_started()
    red_input = recorder_red.spans[0].kwargs["input"]
    assert len(red_input) < 600
    assert red_input.endswith("…")


def test_run_completed_and_failed_end_root():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    root = recorder.spans[0]

    tracer.run_completed("最终回答", usage_total={"total_tokens": 20})
    assert root.ended
    assert root.updates[-1]["output"] == "最终回答"

    tracer2 = _tracer(FakeRecorder())
    tracer2.run_started()
    tracer2.run_failed("cancelled")
    assert tracer2._root.ended
    assert tracer2._root.updates[-1]["level"] == "ERROR"


def test_disabled_sink_tracer_is_full_noop():
    sink = LangfuseSink(public_key="", secret_key="", base_url="")
    tracer = RunTracer(
        sink, session_id="s", run_id="r", agent_id="a", user_input="hi",
    )
    tracer.run_started()
    assert tracer.trace_id is None
    assert tracer.model_call_started(step=1, messages=[]) is None
    tracer.model_call_completed(None, output_text="x", usage=None, duration_ms=1)
    tracer.run_completed("done")
    tracer.run_failed("err")  # 全程不抛


def test_span_op_failures_never_propagate():
    class _BrokenSpan:
        trace_id = "tr-x"

        def start_observation(self, **kwargs):
            raise RuntimeError("sdk blew")

        def update(self, **kwargs):
            raise RuntimeError("sdk blew")

        def end(self):
            raise RuntimeError("sdk blew")

    sink = LangfuseSink(
        public_key="pk", secret_key="sk", base_url="https://example.invalid",
        client_factory=lambda **kwargs: type("_C", (), {"start_observation": lambda self, **kw: _BrokenSpan()})(),
    )
    tracer = RunTracer(sink, session_id="s", run_id="r", agent_id="a", user_input="hi")
    tracer.run_started()  # 不抛
    gen = tracer.model_call_started(step=1, messages=[])
    tracer.model_call_completed(gen, output_text="x", usage=None, duration_ms=1)  # 不抛
    tracer.run_completed("done")  # 不抛


# ── trace_url（trace_url 契约：官方 SDK URL 与 trace_id 并列缓存于终态） ──


def test_trace_url_cached_on_run_completed():
    """run_completed 时把 trace_id 经官方 SDK 合成可点击 URL 并缓存到 tracer。

    trace_id 与 trace_url 并列保留——前者机器可读 + Copy，后者人类可点击，
    不互相替代（契约决策）。URL 由 sink.get_trace_url（官方 SDK）合成，不手拼。
    """
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    assert tracer.trace_id == "tr-fake-001"
    # 终态前 trace_url 未构造（懒构造——只有终态时才确定该 run 是可点击句柄）
    assert tracer.trace_url is None

    tracer.run_completed("最终回答")
    assert tracer.trace_url == recorder.trace_url_template.format(trace_id="tr-fake-001")


def test_trace_url_cached_on_run_failed():
    """run_failed 对称缓存 trace_url（失败 run 在 Langfuse 也有可见 trace，
    跳转有排查价值——契约对称决策）。"""
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    tracer.run_started()
    tracer.run_failed("max_steps_exceeded")
    assert tracer.trace_url == recorder.trace_url_template.format(trace_id="tr-fake-001")


def test_trace_url_none_when_trace_id_none():
    """trace_id 未回填（SDK 未暴露 / sink 缺席）→ trace_url 恒 None。
    tracer 不得在 trace_id=None 时尝试合成 URL（契约降级模式）。"""
    sink = LangfuseSink(public_key="", secret_key="", base_url="")
    tracer = RunTracer(
        sink, session_id="s", run_id="r", agent_id="a", user_input="hi",
    )
    tracer.run_started()
    assert tracer.trace_id is None
    tracer.run_completed("done")
    assert tracer.trace_url is None


def test_trace_url_inherited_from_parent_on_nested_binding():
    """嵌套子 run（SubAgent adopt 父侧根）时 trace_url 同 trace_id 一起继承——
    子 run 与父 run 共享同一 trace 根，URL 一致（ADR-0018 D5 多 Agent 规则）。"""
    from agent_harness.observability.tracer import TraceBinding, current_trace_binding

    parent_recorder = FakeRecorder()
    parent_recorder.next_trace_id = "tr-parent-001"
    parent_tracer = _tracer(parent_recorder)
    parent_tracer.run_started()
    parent_tracer.run_completed("parent done")

    # 构造父侧 binding（delegate 执行期间由 executor 设置）
    binding = TraceBinding(
        trace_id=parent_tracer.trace_id,
        observation=object(),  # 测试只验 trace_url 继承，根句柄本身不入断言
    )
    token = current_trace_binding.set(binding)
    try:
        child_tracer = _tracer(FakeRecorder())
        child_tracer.run_started()  # adopt 模式：认领父侧 trace_id
        assert child_tracer.trace_id == "tr-parent-001"
        assert child_tracer.trace_url is None  # 未到终态
        child_tracer.run_completed("child done")
        # 子 run 用继承的 trace_id 经自己 sink 合成 URL（host/project 配置相同 → 一致）
        assert child_tracer.trace_url is not None
        assert "tr-parent-001" in child_tracer.trace_url
    finally:
        current_trace_binding.reset(token)
