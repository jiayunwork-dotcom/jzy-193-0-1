import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发态把 /api 代理到本机后端；生产由 FastAPI 直接托管构建产物
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
})
