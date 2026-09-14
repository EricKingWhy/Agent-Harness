"""部署垫片（只存在于交付/发布目录，不修改项目源码）。

为什么需要它：发布沙箱上传时会跳过 `dist` 这类构建产物目录，容器里可能没有
`web/dist`，于是 `create_prod_app()` 自带的静态挂载被 exists 守卫跳过 → 首页 404。
这里把同一份构建产物同时放在 `web/site/`（不触发跳过规则），并在应用构造完成后
自行提供前端资源。

**为什么不用 mount("/")**：Starlette 按注册顺序匹配，Mount("/") 会把其后注册的
路由全部遮蔽（连自检端点一起吞掉）。所以这里用「精确子挂载 + 末尾 catch-all 路由」
——API 与自检路由都注册在它之前，天然优先。
"""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_harness.web.app import create_prod_app

_ROOT = Path(__file__).resolve().parent

app: FastAPI = create_prod_app()

#: 静态目录候选。**必须每次请求时解析**：发布平台会在文件同步完成前就拉起进程，
#: 若在导入期把结果缓存成 None（甚至据此不注册路由），应用就会永久失去界面。
#: 踩过一次：进程启动早于文件落盘 → 后续所有静态请求都 404，而 API 一切正常。
_SITE = _ROOT / "web" / "site"
_CANDIDATE_DIRS = (_SITE, _ROOT / "web" / "dist", _ROOT / "site")


def _resolved_site() -> Path | None:
    return next((p for p in _CANDIDATE_DIRS if p.is_dir()), None)


def _env_file_value(key: str) -> str:
    """从 .env 文本里取一个值（用不到 pydantic：DEMO_PROBE_TOKEN 不是 Settings 字段）。"""
    env_file = _ROOT / ".env"
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return ""


@app.get("/__deploy_info")
def _deploy_info() -> dict:
    """上线自检：静态目录到底在哪、挂上没挂上（只暴露路径与文件数）。"""
    live = _resolved_site()
    return {
        "root": str(_ROOT),
        "candidates": [
            {
                "path": str(p),
                "exists": p.is_dir(),
                "files": sum(1 for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0,
            }
            for p in _CANDIDATE_DIRS
        ],
        "serving_from": str(live) if live is not None else None,
        "index_exists": (live / "index.html").is_file() if live is not None else False,
    }


@app.get("/__netprobe")
def _netprobe(t: str = "") -> dict:
    """出网连通性探针：DNS / TCP / TLS 分段报错，定位「模型调用失败」的真实原因。

    只回传网络层结果，绝不回显任何密钥。`?t=<DEMO_PROBE_TOKEN>` 命中时额外做一次
    真实模型调用（会花钱），否则只做网络探测。
    """
    import os
    import socket
    import ssl
    import time
    import urllib.error
    import urllib.request

    # 模型配置必须从 Settings 取：项目用 pydantic-settings 读 .env，
    # 这些值**不会**出现在 os.environ 里（踩过一次）。
    from agent_harness.config import Settings

    st = Settings()
    base = st.model_base_url or ""
    model_name = st.model_name or ""
    key = st.model_api_key.get_secret_value()
    host = base.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    out: dict = {"base_url": base, "host": host}

    try:
        t0 = time.time()
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        out["dns"] = {
            "ok": True,
            "ms": round((time.time() - t0) * 1000),
            "ips": sorted({i[4][0] for i in infos}),
        }
    except Exception as exc:  # noqa: BLE001
        out["dns"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return out

    try:
        t0 = time.time()
        with socket.create_connection((host, 443), timeout=10):
            out["tcp"] = {"ok": True, "ms": round((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        out["tcp"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return out

    try:
        t0 = time.time()
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                out["tls"] = {
                    "ok": True,
                    "ms": round((time.time() - t0) * 1000),
                    "version": tls.version(),
                }
    except Exception as exc:  # noqa: BLE001
        out["tls"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return out

    token = _env_file_value("DEMO_PROBE_TOKEN")
    if token and t == token:
        body = json.dumps(
            {
                "model": model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 4,
            }
        ).encode()
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
            method="POST",
        )
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=30) as resp:
                out["model_call"] = {
                    "ok": True,
                    "status": resp.status,
                    "ms": round((time.time() - t0) * 1000),
                    "body": resp.read(300).decode("utf-8", "replace"),
                }
        except urllib.error.HTTPError as exc:
            out["model_call"] = {
                "ok": False,
                "status": exc.code,
                "body": exc.read(300).decode("utf-8", "replace"),
            }
        except Exception as exc:  # noqa: BLE001
            out["model_call"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return out


@app.get("/__logs")
def _logs(t: str = "", n: int = 60) -> dict:
    """诊断日志尾部（定位 run/failed 的真实异常）。令牌门控。"""
    token = _env_file_value("DEMO_PROBE_TOKEN")
    if not token or t != token:
        return {"error": "forbidden"}

    from agent_harness.config import Settings

    ws = Path(Settings().workspace_dir)
    log_path = (ws if ws.is_absolute() else _ROOT / ws).parent / "logs" / "agent.jsonl"
    if not log_path.is_file():
        return {"log_path": str(log_path), "exists": False}

    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(1, n):]
    return {"log_path": str(log_path), "exists": True, "lines": lines}


@app.get("/__selftest")
def _selftest(t: str = "") -> dict:
    """按 Agent 的真实路径自测模型：tiktoken 计数 → 构造 ChatModel → bind_tools → 流式首块。

    每一步单独捕获异常并回传 `类型: 消息`，用来把「run/failed 但不给原因」定位到具体环节。
    令牌门控（会真花钱）。
    """
    token = _env_file_value("DEMO_PROBE_TOKEN")
    if not token or t != token:
        return {"error": "forbidden"}

    import asyncio
    import traceback

    out: dict = {}

    try:
        from agent_harness.context.tokens import estimate_tokens

        out["tiktoken"] = {"ok": True, "tokens": estimate_tokens("hello world")}
    except Exception as exc:  # noqa: BLE001
        out["tiktoken"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                           "tb": traceback.format_exc()[-400:]}

    try:
        from agent_harness.config import Settings
        from agent_harness.model.config import ModelConfig
        from agent_harness.model.provider import create_chat_model

        cfg = ModelConfig.from_settings(Settings())
        model = create_chat_model(cfg)
        out["build"] = {"ok": True, "provider": cfg.provider, "model": cfg.model_name,
                        "class": type(model).__name__}

        tool_schema = {
            "type": "function",
            "function": {"name": "noop", "description": "noop",
                         "parameters": {"type": "object", "properties": {}}},
        }
        bound = model.bind_tools([tool_schema])
        out["bind_tools"] = {"ok": True}

        async def first_chunk() -> dict:
            from langchain_core.messages import HumanMessage

            async for chunk in bound.astream(
                [HumanMessage(content="reply with exactly: pong")]
            ):
                tc = getattr(chunk, "tool_calls", None)
                return {"ok": True, "content": str(getattr(chunk, "content", ""))[:120],
                        "tool_calls": bool(tc)}
            return {"ok": False, "error": "流结束但没有任何 chunk"}

        out["astream"] = asyncio.run(first_chunk())
    except Exception as exc:  # noqa: BLE001
        out["astream"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                          "tb": traceback.format_exc()[-800:]}
    return out


@app.get("/__gwprobe")
def _gwprobe(t: str = "", via: str = "raw", tools: int = 0) -> dict:
    """**流式诊断**：测同一次流式请求在两层的「攒包度」。

    - `via=raw`（默认）：绕开 langchain/httpx，直接对 MODEL_BASE_URL 发流式请求；
    - `via=langchain`：走项目真实的 `ModelConfig → create_chat_model → astream` 路径。

    两者对比即可定位攒包发生在哪一层：
    - raw 逐字、langchain 攒包 → SDK/请求形态的问题；
    - 两者都逐字、线上 App 仍攒包 → 攒包在 Harness 的事件发射/持久化环节。
    再加 `tools=1` 带上工具定义（Agent 主链的真实请求形态）。

    只读配置、不落库；令牌门控（会真花钱）。
    """
    token = _env_file_value("DEMO_PROBE_TOKEN")
    if not token or t != token:
        return {"error": "forbidden"}

    import time

    from agent_harness.config import Settings

    s = Settings()
    prompt = "请写一段大约一百字的说明，介绍什么是事件溯源。"

    if via == "langchain":
        import asyncio

        from langchain_core.messages import HumanMessage

        from agent_harness.model.config import ModelConfig
        from agent_harness.model.provider import create_chat_model

        async def measure() -> dict:
            model = create_chat_model(ModelConfig.from_settings(s))
            bound = model
            if tools:
                bound = model.bind_tools([{
                    "type": "function",
                    "function": {"name": "noop", "description": "noop",
                                 "parameters": {"type": "object", "properties": {}}},
                }])
            t0 = time.time()
            stamps: list[float] = []
            async for chunk in bound.astream([HumanMessage(content=prompt)]):
                # 只记有增量的 chunk（含 reasoning 增量）
                has = bool(getattr(chunk, "content", "")) or bool(
                    (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content"))
                if has:
                    stamps.append(time.time() - t0)
            return {"stamps": stamps}

        try:
            res = asyncio.run(measure())
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "via": via, "error": f"{type(exc).__name__}: {exc}"}
        stamps = res["stamps"]
        if not stamps:
            return {"ok": False, "via": via, "error": "没有增量 chunk"}
        span = stamps[-1] - stamps[0]
        return {
            "ok": True, "via": via, "tools": bool(tools),
            "chunks": len(stamps), "ttft_s": round(stamps[0], 3),
            "span_s": round(span, 3),
            "verdict": ("逐字流式" if span >= 1.0 else
                        ("攒包" if len(stamps) >= 5 else "帧太少判不准")),
        }

    import urllib.error
    import urllib.request

    key = s.model_api_key.get_secret_value()
    url = (s.model_base_url or "").rstrip("/") + "/chat/completions"
    payload: dict = {"model": s.model_name,
                     "messages": [{"role": "user", "content": prompt}],
                     "max_tokens": 400, "stream": True}
    if tools:
        payload["tools"] = [{
            "type": "function",
            "function": {"name": "noop", "description": "noop",
                         "parameters": {"type": "object", "properties": {}}},
        }]
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 # 部分网关按 UA 拦非浏览器客户端（403），带上更稳
                 "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36")},
    )
    t0 = time.time()
    stamps: list[float] = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    stamps.append(time.time() - t0)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": url, "status": exc.code,
                "body": exc.read(300).decode("utf-8", "replace")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}

    if not stamps:
        return {"ok": False, "url": url, "error": "没有任何内容帧"}
    span = stamps[-1] - stamps[0]
    return {
        "ok": True, "url": url, "model": s.model_name,
        "ttft_s": round(stamps[0], 3),
        "chunks": len(stamps),
        "span_s": round(span, 3),
        "verdict": ("逐字流式（这一跳没问题）" if span >= 1.0
                    else ("攒包：响应到齐才交付" if len(stamps) >= 5
                          else "帧太少，判不准")),
    }


# ── 前端资源：精确子挂载 + 末尾 catch-all（都注册在自检路由之后）──────────
# 目录在**请求时**解析（见 _resolved_site 注释），所以这里无条件注册，
# 不受「进程启动早于文件落盘」影响。
app.mount(
    "/assets",
    StaticFiles(directory=str(_SITE / "assets"), check_dir=False),
    name="assets",
)


@app.get("/{full_path:path}", include_in_schema=False)
def _spa(full_path: str) -> FileResponse:
    # /api 与 /__ 前缀的缺失路由必须如实 404（返回 index.html 会掩盖真实接口缺失）
    if full_path.startswith(("api/", "__")):
        raise HTTPException(status_code=404, detail="Not Found")

    for base in _CANDIDATE_DIRS:
        if not base.is_dir():
            continue
        target = base / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        index = base / "index.html"
        if index.is_file():
            return FileResponse(index)
    raise HTTPException(status_code=404, detail="静态资源尚未就绪")


if __name__ == "__main__":
    # 自包含启动器：直接跑本文件（python serve.py），不走 uvicorn 命令行目标解析
    import os

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
