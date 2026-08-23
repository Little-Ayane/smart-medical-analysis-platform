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
    proxy: {
      '/api': {
        target: 'http://192.168.247.128:5000',
        changeOrigin: true
      },
      '/drg': {
        target: 'http://192.168.247.128:8001',
        changeOrigin: true
      }
    }
  }
})