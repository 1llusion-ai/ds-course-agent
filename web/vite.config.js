import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8084'

export default defineConfig({
  plugins: [
    vue(),
    Components({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })]
    })
  ],
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern'
      }
    }
  },
  build: {
    // Three.js is deferred with the 3D knowledge-map canvas and currently ships as one upstream module.
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          const modulePath = id.replaceAll('\\', '/')
          if (modulePath.includes('/node_modules/katex/') || modulePath.includes('/node_modules/marked/')) {
            return 'markdown-vendor'
          }
          if (
            modulePath.includes('/node_modules/vue/')
            || modulePath.includes('/node_modules/@vue/')
            || modulePath.includes('/node_modules/pinia/')
          ) {
            return 'framework-vendor'
          }
          if (modulePath.includes('/node_modules/three/')) return 'knowledge-graph-three'
          if (modulePath.includes('/node_modules/d3-')) return 'knowledge-graph-d3'
          if (
            modulePath.includes('/node_modules/3d-force-graph/')
            || modulePath.includes('/node_modules/three-forcegraph/')
            || modulePath.includes('/node_modules/three-render-objects/')
          ) {
            return 'knowledge-graph-runtime'
          }
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
