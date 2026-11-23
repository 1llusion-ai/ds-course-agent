import { ElMessageBox } from 'element-plus'

export const roleLabels = { student: '学生', admin: '管理员' }
export const inviteStatusLabels = { active: '可用', disabled: '已停用', expired: '已过期' }

export function formatDate(value, options = {}) {
  if (!value) return '暂无记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无记录'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    ...options
  }).format(date)
}

export function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

export function formatRelativeTime(value) {
  if (!value) return '暂无记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无记录'
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date)
}

export function formatPercent(value) {
  return value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
}

export function errorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return '请检查输入内容及日期范围后重试。'
  return error?.response?.status === 403 ? '当前账号没有执行此操作的权限。' : '暂时无法完成请求，请稍后重试。'
}

export function dateInputValue(date = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date)
}

export const roleDescription = {
  student: '使用课程问答与练习，查看自己的学习记录。',
  admin: '管理账号、角色和注册码，查看个人使用汇总与操作记录。'
}
export const registrationSourceLabels = {
  legacy: '历史账号 · 来源未知',
  manual: '管理员创建',
  invite: '凭注册码注册',
  open: '开放注册'
}
export async function confirmAdminDeletion(message, title) {
  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger'
    })
    return true
  } catch {
    return false
  }
}

export function confirmAccountDeletion(user) {
  return confirmAdminDeletion(
    `删除账号「${user.username}」？删除后无法在管理台恢复，账号将失去登录权限。学习记录仍会保留。`,
    '删除账号'
  )
}
