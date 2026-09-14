import { defineConfig, devices } from '@playwright/test';

// 联调车道（spec 03 §22 尾注：真实模型/鉴权/长稳，夜间/手动）。
//
// 与主车道（playwright.config.ts）的区别：**不 mock 任何网络**——直连
// 真实后端（vite 的 /api 代理 → 127.0.0.1:8000）与真实模型，因此
// **不入标准门禁**：需要后端已启动、模型可用、且耗时/结果非确定。
//
// 运行：
//   1. 后端：在 D:\intelligence-agent-backend 启动 web app（127.0.0.1:8000）
//   2. 前端：本目录 `npm run dev`（或让下面 webServer 拉起）
//   3. `npx playwright test --config playwright.live.config.ts --workers=1`
export default defineConfig({
  testDir: './e2e-live',
  // 真模型往返 + 人工审批窗口，给足余量（后端审批超时默认 300s，fail-closed）
  timeout: 420_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    // 联调车道要求**手动确认**前端来源：CI 下不复用（与主车道同规矩），
    // 本地复用是为了让「已手起 dev server」的工作流可用。
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: 'live-chromium-1280', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
  ],
});
