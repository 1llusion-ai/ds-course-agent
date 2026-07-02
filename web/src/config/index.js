// 全局配置

// 当前用户ID（后续应从登录态/鉴权获取）
export const DEFAULT_STUDENT_ID = import.meta.env.VITE_STUDENT_ID || 'default_student'

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
