// 全局配置

// API 配置
export const API_CONFIG = {
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000
}

// 其他全局配置
export const APP_CONFIG = {
  appName: '智能课程助教',
  courseName: '数据科学导论'
}
