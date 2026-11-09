import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发代理：/api → FastAPI（uvicorn 默认 8000）；生产由反向代理同源托管。
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
