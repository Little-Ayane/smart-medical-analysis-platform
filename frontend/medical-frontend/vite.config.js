import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // 核心分析（下钻/透视等）→ FastAPI core 服务 8000
      '/api/v1/analysis/dimension-combine': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/metric-switch': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/drill-down': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/time-rollup': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/pivot': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/metadata': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/summary': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/api/v1/analysis/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      // 大屏数据 → Flask 5000
      '/api/v1/bigscreen': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      },
      // DRG 分析 → FastAPI drg 服务 8001（前缀 /api/v1/drg）
      '/api/v1/drg': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true
      },
      // 其余 /api → Flask 分析服务 5000（病种/支付/质量/费用/急诊）
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      }
    }
  }
})