import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

const authStore = useAuthStore(pinia)
if (typeof window !== 'undefined') {
  window.addEventListener('auth:unauthorized', () => {
    authStore.clearUser()
  })
}

app.mount('#app')
