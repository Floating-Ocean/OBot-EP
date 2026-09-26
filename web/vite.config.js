import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'

// 后端地址：开发时 Vite 把 /api 代理过去，前后端同源，会话 Cookie 直接带上。
const BACKEND = process.env.OBOT_EP_API ?? 'http://127.0.0.1:8000'
const DEV_PORT = Number(process.env.OBOT_EP_WEB_PORT ?? 5173)

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      imports: ['vue', 'vue-router'],
      dts: false,
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 显式绑 127.0.0.1：默认只监听 ::1，导致 127.0.0.1:5173 连不上、
    // 打印出来的 Local 地址也点不动，很容易以为没起来。
    host: '127.0.0.1',
    port: DEV_PORT,
    // 端口被占用时直接报错退出，不要悄悄换到 5174，否则代理目标对不上
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
})
