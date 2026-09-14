import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: Vite serves frontend on :5173, proxies /api to FastAPI on :8000.
// Prod: FastAPI serves web/dist statically (see src/agent_harness/web/app.py).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // 生产不发布 sourcemap：.map 会把全部原始源码暴露给任何能拉到静态资源的人
    // （安全审查发现 3）。本地排障用 npm run build -- --sourcemap 临时开启。
    sourcemap: false,
    // 0 = 任何资源都不内联为 data: URI。后端 CSP `default-src 'self'` 下
    // font-src 回退 self，data: 字体会被拦（实测 2026-09-05：fontsource 最小的
    // vietnamese 子集默认被内联后遭浏览器拦截）。字体必须始终是同源文件。
    assetsInlineLimit: 0,
  },
})
