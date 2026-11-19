import { appPath, redirectToLogin } from '../utils/appPaths'
import axios from 'axios'

const client = axios.create({
  baseURL: appPath('api'),
  timeout: 120000,  // 增加到120秒，首次请求需要加载embedding
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' }
})


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
