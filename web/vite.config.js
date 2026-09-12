import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8084'

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('katex') || id.includes('marked')) return 'markdown-vendor'
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'element-plus-vendor'
          if (id.includes('vue') || id.includes('pinia')) return 'framework-vendor'
          return undefined
        }
      }
    }
  },
  server: {
    port: 5185,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true
      }
    }
  }
})
