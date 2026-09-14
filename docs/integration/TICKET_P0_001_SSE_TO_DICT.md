# Ticket P0-001：send_message 续聊路径 SSE 序列化崩溃（`ev.to_dict()`）

> **Spec**：Issue #140
> **车道**：后端 `D:\intelligence-agent-backend`（`feat/backend`）
> **优先级**：P0（会 500）
> **验收走法**：先写红灯测试，再修码，再见绿灯。

---

## 背景

续聊入口 `POST /api/sessions/{id}/messages` 的 SSE 生成器对事件对象调用了 `ev.to_dict()`。

审计确认：`AgentEvent` **没有** `to_dict()` 方法（只有 `SessionEvent` 有）。因此一旦运行进入该生成器发射首包，就会在 `ev.to_dict()` 处触发 `AttributeError`，续聊流崩溃 500。

同一事件对象在三条入口的序列化语义应完全一致（不变量：同形状、`BACKEND_CONTRACT_STREAMING_UI.md`）：
- `create_session` `/sessions` POST（`app.py:951`）→ 正确用 `_event_to_sse_dict`
- `resume_session` stream GET（`app.py:1056`）→ 正确用 `_event_to_sse_dict`
- `send_message` `/sessions/{id}/messages` POST（`app.py:1189`）→ **错误用 `ev.to_dict()`**

这就是序列化层的「一条统一路径」被破坏：三条入口应对同一函数，唯独续聊这条漏了。

## 现状（`feat/backend` @ `3715bf2`）

```python
async def event_generator():          # app.py:1186
    try:
        async for ev in subscriber:
            yield {"event": ev.type, "data": json.dumps(ev.to_dict())}   # ← BUG
            if ev.type in {"run/completed", "run/failed"}:
                break
    finally:
        run.unsubscribe(subscriber)
```

## 要做什么

把 `send_message` 的事件生成器里的 `ev.to_dict()` 替换为 `_event_to_sse_dict(ev, session_id)`，与 `create_session` / `resume_session` 一致：

```python
yield _event_to_sse_dict(ev, session_id)
```

- 复用现有 `_event_to_sse_dict`（`app.py:460`）。
- 不做任何额外抽象 / 改造。
- 不改变事件形状合约。

## 回归测试

**接缝**：真实 ASGI 服务器 + `httpx2` 流式客户端 + `ScriptedModel.astream` 测试桩——复用 `tests/web/test_web_stream.py` 的 `_start_server` + `aiter_lines` 模式。

**场景**：
1. 建会话并驱动到完成（`run/completed`）；
2. 对 `POST /api/sessions/{id}/messages` 发起续聊；
3. 断言 SSE 事件被正确序列化且**不抛 `AttributeError`**（续聊首包可被 `data:` 解析、字段与 live 通道同形）。

**prior art**：`tests/web/test_web_stream.py`。

## 不要做什么

- ❌ 不重构事件序列化子系统
- ❌ 不改 `AgentEvent` / `SessionEvent` 类
- ❌ 不统一三入口之外的代码
- ❌ 不做本 ticket 之外的顺手重构
