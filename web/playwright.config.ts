import { defineConfig, devices } from '@playwright/test';

// T8（#101）E2E 车道（spec 03 §21 浏览器矩阵骨架）：
// - Chromium 单引擎（grill Q5 批准范围）；1280/1920 两档宽度两个 project。
// - webServer 起 vite dev（5173）；API 用 page.route 拦截（e2e/fixtures.ts
//   mock SSE，帧形状 = docs/BACKEND_CONTRACT_STREAMING_UI.md）——核心矩阵
//   不依赖真后端。真实模型/鉴权/长稳场景属联调车道（spec 03 §22 尾注：
//   夜间/手动），不进本骨架。
// - 不污染 vitest 车道：vitest.config.ts exclude e2e/**。
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  // §16.6 硬要求：e2e 一律 2 worker。4 worker 全量并行存在资源竞争型抖动，
  // 且同一 worktree 里并行跑两个 playwright 会争用 test-results/ 产生
  // `ENOENT … .playwright-artifacts-*` 式的假失败。写进配置让裸跑
  // `npx playwright test` 与门禁命令（`--workers=2`）等价，免得"门禁绿、
  // 本地红"反复消耗排查时间。（e2e-live/ 用独立配置，不受这里影响。）
  workers: 2,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: 'chromium-1280', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
    { name: 'chromium-1920', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } },
  ],
});
