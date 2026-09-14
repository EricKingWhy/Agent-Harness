# Phase 8 预设 MCP Server 配置模板（用户拍板：GitHub + Google chrome-devtools + Sentry + Context7）

> 默认 `capabilities` 配置保持空（opt-in 安全默认）。以下模板由运营者按需粘进
> `CAPABILITIES` env JSON 的 `options.servers[]`。`${VAR}` 引用进程环境变量，
> 明文 token 不入库。来源核对：官方 registry 反向 DNS 命名空间 / 厂商官方 repo。

```jsonc
{
  "mcp": {
    "provider": "builtin",
    "enabled": true,
    "options": {
      "servers": [
        // GitHub 官方（远程，需 PAT：env 里设 GITHUB_MCP_TOKEN）
        {
          "name": "github",
          "transport": "http",
          "url": "https://api.githubcopilot.com/mcp/",
          "headers": { "Authorization": "Bearer ${GITHUB_MCP_TOKEN}" },
          "timeout_seconds": 60,
          "enabled": true
        },
        // Google chrome-devtools-mcp（stdio，npx 拉起）
        {
          "name": "chrome-devtools",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "chrome-devtools-mcp@latest"],
          "timeout_seconds": 30,
          "enabled": true
        },
        // Sentry 官方（stdio，需 SENTRY_TOKEN）
        {
          "name": "sentry",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@sentry/mcp-server@latest"],
          "env": { "SENTRY_TOKEN": "${SENTRY_TOKEN}" },
          "timeout_seconds": 30,
          "enabled": true
        },
        // Context7（Upstash，stdio）
        {
          "name": "context7",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@upstash/context7-mcp@latest"],
          "timeout_seconds": 30,
          "enabled": true
        }
      ]
    }
  }
}
```

## 按栈增补（只写文档，不进预设）

- AWS：awslabs/mcp（托管 + uvx/Docker 本地）
- Cloudflare：远程 Streamable HTTP `/mcp`
- Figma：远程 `https://mcp.figma.com/mcp`
- Stripe：远程 `https://mcp.stripe.com`（会动钱——接入前必须逐工具审权限）
- Slack / Notion：官方远程 server
- JetBrains：stdio proxy（仅 JetBrains IDE 用户）

## 来源核对

| Server | 官方 repo / 文档 | 核对点 |
|---|---|---|
| github | github/github-mcp-server (MIT, 32.7k★) | 远程端点以 GitHub docs 为准 |
| chrome-devtools | ChromeDevTools/chrome-devtools-mcp (Apache-2.0, 50.9k★) | npx 包名 `chrome-devtools-mcp` |
| sentry | getsentry/sentry-mcp (Go) | npm 包名以 repo README 为准（施工时核实） |
| context7 | upstash/context7 (Apache-2.0) | npm 包名 `@upstash/context7-mcp` |

> ⚠️ 上表 npx/npm 包名与远程端点在 T5 文档 ticket 施工时逐一以官方 README 复核
> （调研数据为 2026-09-05，包名可能演进）。

## 复核记录（2026-09-05，pre-merge review 补记）

- **github**：✅ 真实验收通过（远程端点，`get_me` 返回登录身份，44 tools discovery）——docs/PHASE8_MANUAL_ACCEPTANCE.md。
- **chrome-devtools**：✅ 真实验收通过（npx `chrome-devtools-mcp` stdio，29 tools discovery；页面级 isError 为 Chrome 环境状态，非配置问题）。
- **context7**：✅ 真实验收通过（`@upstash/context7-mcp` npx 与远程 HTTP 双路径，真实调用返回 pydantic 文档）。
- **sentry**：⏸️ 未验证——需要 `SENTRY_TOKEN`，用户配置后按 docs/PHASE8_MANUAL_ACCEPTANCE.md 补跑。`getsentry/sentry-mcp` 的 npm 包名仍是"以 repo README 为准"的未核实项。
