import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,  // 增加到120秒，首次请求需要加载embedding
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' }
})

function redirectToLogin() {
  if (typeof window === 'undefined') {
    return
  }

  window.dispatchEvent(new CustomEvent('auth:unauthorized'))

  const { pathname, search, hash } = window.location
  if (pathname === '/login') {
    return
  }

  const redirect = `${pathname}${search}${hash}`
  window.location.assign(`/login?redirect=${encodeURIComponent(redirect)}`)
}

client.interceptors.request.use(
  (config) => {
    console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => Promise.reject(error)
)

client.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('[API Error]', error.response?.data || error.message)
    if (error.response?.status === 401 && !error.config?.skipAuthRedirect) {
      redirectToLogin()
    }
    return Promise.reject(error)
  }
)

export default client
