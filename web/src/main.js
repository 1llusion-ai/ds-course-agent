import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/es/components/alert/style/css.mjs'
import 'element-plus/es/components/button/style/css.mjs'
import 'element-plus/es/components/card/style/css.mjs'
import 'element-plus/es/components/dropdown/style/css.mjs'
import 'element-plus/es/components/form/style/css.mjs'
import 'element-plus/es/components/icon/style/css.mjs'
import 'element-plus/es/components/input/style/css.mjs'
import 'element-plus/es/components/loading/style/css.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import 'element-plus/es/components/message-box/style/css.mjs'
import 'element-plus/es/components/overlay/style/css.mjs'
import 'element-plus/es/components/popover/style/css.mjs'
import 'element-plus/es/components/progress/style/css.mjs'
import 'element-plus/es/components/scrollbar/style/css.mjs'
import 'element-plus/es/components/segmented/style/css.mjs'
import 'element-plus/es/components/select/style/css.mjs'
import 'element-plus/es/components/skeleton/style/css.mjs'
import 'element-plus/es/components/switch/style/css.mjs'
import 'element-plus/es/components/tooltip/style/css.mjs'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import { installElementPlus } from './element-plus'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
installElementPlus(app)

const authStore = useAuthStore(pinia)
if (typeof window !== 'undefined') {
  window.addEventListener('auth:unauthorized', () => {
    authStore.clearUser()
  })
}

app.mount('#app')
