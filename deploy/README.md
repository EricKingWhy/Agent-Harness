# deploy/ —— 单端口运行与云沙箱发布

把整个项目跑成**一个 HTTP 端口**（API + 前端 + 会话数据一体），并发布到
云端沙箱供评委直接打开。这里记录的是**实测踩过的坑**，重做一遍时按顺序看即可。

## 一、本地/服务器直接跑

```bash
pip install -r requirements.txt      # 只需 pyproject 的运行时依赖，不含 optional extras
cp .env.example .env                 # 填 MODEL_API_KEY
bash start.sh                        # 默认 :8000，读 $PORT 环境变量
```

`start.sh` 做三件事：选解释器 → `PYTHONPATH=src` → 启动 `serve.py`。

## 二、发布到云端沙箱（一键链接）

以本仓库为源，发布时把「后端源码 + 前端构建产物 + 运行数据」放成一个目录：

```
<发布目录>/
├── src/agent_harness/     后端源码
├── web/dist/              前端构建产物（vite build）
├── web/site/              同一份产物（见坑 1）
├── .agent/workspace/      会话事件 JSONL + harness.db（预置演示数据）
├── tiktoken_cache/        词表缓存（见坑 3）
├── serve.py  start.sh  requirements.txt  .env
```

发布参数：`language=python`、`port=8000`、`installCmd=pip install -r requirements.txt`、
`startCmd=bash start.sh`。

## 三、踩过的坑（都已在代码里修掉）

**1. 平台上传会跳过 `dist` 目录** → 容器里 `web/dist` 不存在，
`create_prod_app()` 的静态挂载被 exists 守卫跳过 → 首页 404、API 却正常。
对策：产物同时放一份到 `web/site/`，由 `serve.py` 顶上（不依赖被跳过的目录名）。

**2. 静态目录不能在导入期缓存判定** → 平台会在文件同步完成前就拉起进程；
若在 `.py` 导入期算出 `web/site` 不存在并据此**不注册路由**，应用就永久没有界面
（表现为：CDN 把 `/` 的旧 200 缓存住，看起来首页正常，但刷新/深链全 404）。
对策：`serve.py::_resolved_site()` **每次请求时**解析目录，路由无条件注册。

**3. tiktoken 首次使用要联网下载词表** → 受限出网环境里
`openaipublic.blob.core.windows.net` 被掐断，抛 `SSLError`；
`ContextBuilder` 第一步就失败 → run 直接 `run/failed`（事件里不带原因，极难查）。
对策：词表随包携带，`start.sh` 里 `export TIKTOKEN_CACHE_DIR=$(pwd)/tiktoken_cache`。
缓存文件名 = **词表 URL 的 sha1**，所以是 `9b5ad71b…` 这种名字，不要改名。

**4. `uvicorn …:app --factory` 指向 app 对象会报**
`FastAPI.__call__() missing 3 required positional arguments`。
对策：`start.sh` 直接 `python serve.py`（启动器写在 `if __name__ == "__main__"` 里），
不走命令行目标解析。

**5. 配置来自 `.env` 文件、不进 `os.environ`** → 项目用 pydantic-settings 读
仓库根的 `.env`，所以**诊断脚本里 `os.environ["MODEL_API_KEY"]` 一定是空的**；
要取配置请用 `Settings()`。发布时 `.env` 必须随包上传。

**6. `mount("/")` 会遮蔽其后注册的所有路由**（Starlette 按注册顺序匹配）→
自检端点一律 404。对策：用「精确 `/assets` 子挂载 + 末尾 `/{path}` catch-all」，
并把 `/api`、`/__` 前缀的未命中路径如实返回 404，避免用 index.html 掩盖接口缺失。

**7. 单进程写锁** → `workspace_dir` 同一时刻只允许一个进程持有
（`.agent/workspace/.instance.lock`）。本地同时起两个实例时第二个会启动失败并
提示占用者 pid——这是有意设计，不是 bug。

**8. 重新发布是「增量合并」，不是同步删除** → 发布同一目录会复用沙箱，上传是
「覆盖 + 新增」：**沙箱里上一版存在、这一版删掉的文件会原样留着**。
把运行时数据（会话 / 记忆 / 产出）从发布目录删掉再重新发布，线上不会跟着变干净。
对策（按推荐度）：① 让应用指向一个**全新的数据目录**（`WORKSPACE_DIR=.agent/demo`
这类配置项，一次性、无破坏性）；② 先下线再发布（可能换新沙箱、**分享链接会变**）；
③ 在容器启动脚本里做一次性清理（最重，容易误删用户新数据）。

## 四、上线自检（`serve.py` 内置，令牌门控）

| 端点 | 用途 |
|---|---|
| `GET /__deploy_info` | 静态目录到底落在哪、挂上没有、index.html 在不在（**故意不门控**） |
| `GET /__netprobe?t=<token>` | DNS / TCP / TLS 三段分别报错；带令牌时做一次真实模型调用 |
| `GET /__selftest?t=<token>` | 按 Agent 真实路径自测：tiktoken → 建模型 → bind_tools → 流式首块 |
| `GET /__logs?t=<token>&n=60` | 诊断日志尾部，用来定位 `run/failed` 的真实异常 |
| `GET /__gwprobe?t=<token>&via=raw\|langchain&tools=0\|1` | **流式攒包定位**：测同一次流式请求在「裸 HTTP」与「真实 langchain 路径」两层的首块延迟 / 增量帧数 / 帧跨度 |

令牌取自 `.env` 的 `DEMO_PROBE_TOKEN`（参数名是 `t=`，传成 `?token=` 会返回
`{"error":"forbidden"}`，看起来像端点坏了）。发布后用这几个端点可以在**一分钟内**
区分「环境没起来 / 网络不通 / 模型不通 / Agent 内部报错」。

**注意**：`/__*` 端点**只在沙箱里可用**。本地直跑时若 `web/dist` 存在，项目自带的
静态挂载会遮蔽其后注册的路由，这些端点一律 404——这不是没注册，是顺序问题（见坑 6）。
