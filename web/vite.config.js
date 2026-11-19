import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const appBase = process.env.VITE_APP_BASE_PATH || '/'
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8084'

export default defineConfig({
  base: appBase,
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
    // Vite 8 emits an invalid client placeholder in agent environments unless this is explicit.
    forwardConsole: { unhandledErrors: false, logLevels: [] },
    port: 5185,
    host: '127.0.0.1',
    proxy: {
      [`${appBase}api`]: {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: path => appBase === '/' ? path : path.slice(appBase.length - 1)
      }
    }
  }
})
