"""Web 层：FastAPI app + SSE + REST（Phase 9/10 精简版 + ADR-0016 detached-run）。

对外暴露 create_app()——FastAPI 应用工厂。路由：
    GET  /api/sessions                     列历史 session
    GET  /api/sessions/{id}/events         读历史事件（全量重建用）
    GET  /api/sessions/{id}/stream         重连续传（after_seq 游标，ADR-0016 §2.3）
    POST /api/sessions                     起新 session + 跑任务（SSE 订阅 detached run）
    POST /api/sessions/{id}/cancel         显式取消在途 run（ADR-0016 §2.2）
    POST /api/sessions/{id}/recover        恢复崩溃 session（07 §9）
    GET  /api/health                       健康检查
    POST /api/sessions/{id}/approve        审批决策（V1 seam：auto-approve 为主）

设计原则（spec 11 §4 + ADR-0016 §2.1）：
- run 生命周期与 HTTP 请求解耦：SSE 只是 detached run 的一个订阅者，
  断连只 unsubscribe，显式取消走 POST /cancel（孤儿回收兜底）。
- 前端直接消费 AgentEvent 流，不在后端做投影（不变量 #22）。
- durable 事实按 seq 幂等合并（listener 通道 + 镜像通道不重复）。
"""

from agent_harness.web.app import create_app, create_prod_app, mount_static

__all__ = ["create_app", "create_prod_app", "mount_static"]
