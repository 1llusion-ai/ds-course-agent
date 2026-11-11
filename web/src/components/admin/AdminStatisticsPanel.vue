<template>
  <section class="admin-page">
    <header class="admin-page__header">
      <div>
        <h1>{{ detailed ? '统计分析' : '数据概览' }}</h1>
        <p class="admin-page__description">
          {{ detailed ? '按时间与课程，了解学习活动和练习完成情况。' : '在这里了解账号增长与课程使用情况。' }}
        </p>
      </div>
      <button
        v-if="detailed"
        class="admin-button"
        type="button"
        :disabled="loading || exporting || !data"
        @click="exportCsv"
      >
        <el-icon aria-hidden="true"><Download /></el-icon>
        {{ exporting ? '正在导出…' : '导出汇总 CSV' }}
      </button>
    </header>
    <form class="admin-toolbar" @submit.prevent="applyFilters">
      <label class="admin-field">
        时间范围
        <select v-model="period" class="admin-select" @change="onPeriodChange">
          <option value="7">最近 7 天</option>
          <option value="30">最近 30 天</option>
          <option value="custom">自定义日期</option>
        </select>
      </label>
      <template v-if="period === 'custom'">
        <label class="admin-field">
          开始日期
          <input v-model="filters.start" type="date" class="admin-input" required />
        </label>
        <label class="admin-field">
          结束日期
          <input v-model="filters.end" type="date" class="admin-input" required />
        </label>
      </template>
      <label class="admin-field">
        课程
        <select v-model="filters.course_id" class="admin-select" @change="applyFilters">
          <option value="">全部课程</option>
          <option v-for="course in courses" :key="course.course_id" :value="course.course_id">
            {{ course.display_name }}
          </option>
        </select>
      </label>
      <button class="admin-button" type="submit" :disabled="loading">{{ loading ? '加载中…' : '应用筛选' }}</button>
    </form>
    <p v-if="filterError || error || exportError" class="admin-error" role="alert">
      {{ filterError || error || exportError }}
      <button v-if="error" class="admin-link" type="button" @click="load">重新加载</button>
    </p>
    <p v-if="courseError" class="admin-note" role="status">
      课程列表加载失败，仍可查看全部课程统计。
      <button class="admin-link" type="button" @click="loadCourses">重试</button>
    </p>
    <section
      v-if="!detailed && isAdmin && signals"
      class="admin-card admin-signals"
      aria-labelledby="signals-title"
    >
      <div class="admin-card__header">
        <div>
          <h2 id="signals-title">待关注</h2>
          <p>容量、邀请码与回答状态的自动提醒。</p>
        </div>
      </div>
      <ul v-if="signalItems.length" class="admin-signal-list">
        <li v-for="item in signalItems" :key="item.text" class="admin-signal" :class="`admin-signal--${item.tone}`">
          <span class="admin-signal__dot" aria-hidden="true"></span>
          <span class="admin-signal__text">{{ item.text }}</span>
          <router-link v-if="item.to" :to="item.to" class="admin-link">去处理 →</router-link>
        </li>
      </ul>
      <p v-else class="admin-note">容量、邀请码与回答状态均正常，暂无待关注事项。</p>
    </section>
    <div v-if="loading" class="admin-loading" role="status">正在汇总数据…</div>
    <template v-else-if="data">
      <div class="admin-metrics">
        <div v-for="metric in metrics" :key="metric.label" class="admin-metric">
          <span class="admin-metric__label">{{ metric.label }}</span>
          <strong class="admin-metric__value">{{ metric.value }}</strong>
          <span class="admin-metric__hint">{{ metric.hint }}</span>
          <span v-if="metric.delta" class="admin-metric__delta">{{ metric.delta }}</span>
        </div>
      </div>
      <section class="admin-card" aria-labelledby="activity-trend-title">
        <div class="admin-card__header">
          <div>
            <h2 id="activity-trend-title">提问趋势</h2>
            <p>{{ data.start }} — {{ data.end }} · 上海时间</p>
          </div>
          <span class="admin-pill">每日提问量</span>
        </div>
        <AdminActivityChart :rows="data.daily" />
      </section>
      <div class="admin-two-columns">
        <section class="admin-card" aria-labelledby="account-summary-title">
          <div class="admin-card__header">
            <h2 id="account-summary-title">账号概况</h2>
            <span class="admin-note">全站账号</span>
          </div>
          <div class="admin-breakdown">
            <div v-for="row in accountRows" :key="row.label" class="admin-breakdown__row">
              <span>{{ row.label }}</span>
              <strong>{{ typeof row.value === 'number' ? formatNumber(row.value) : row.value }}</strong>
            </div>
          </div>
        </section>
        <section class="admin-card" aria-labelledby="assessment-summary-title">
          <div class="admin-card__header">
            <h2 id="assessment-summary-title">练习与回答</h2>
            <span class="admin-note">所选时间与课程</span>
          </div>
          <div class="admin-breakdown">
            <div v-for="row in usageRows" :key="row.label" class="admin-breakdown__row">
              <span>{{ row.label }}</span>
              <strong>{{ row.value }}</strong>
            </div>
          </div>
        </section>
      </div>
      <section class="admin-card" aria-labelledby="course-statistics-title">
        <div class="admin-card__header">
          <h2 id="course-statistics-title">课程使用情况</h2>
          <router-link v-if="!detailed" to="/admin/statistics" class="admin-link">查看详细统计 →</router-link>
        </div>
        <div class="admin-table-wrap">
          <table class="admin-table">
            <thead>
              <tr>
                <th>课程</th>
                <th class="admin-numeric">活跃人数</th>
                <th class="admin-numeric">提问量</th>
                <th class="admin-numeric">期间提交练习</th>
                <th class="admin-numeric">发布批次完成率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="course in data.courses" :key="course.course_id">
                <td>{{ course.display_name }}</td>
                <td class="admin-numeric">{{ formatNumber(course.active_users) }}</td>
                <td class="admin-numeric">{{ formatNumber(course.questions) }}</td>
                <td class="admin-numeric">{{ formatNumber(course.assessments_submitted) }}</td>
                <td class="admin-numeric">{{ formatPercent(course.completion_rate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!data.courses.length" class="admin-empty">所选范围暂无课程使用记录</p>
      </section>
      <template v-if="detailed">
        <section class="admin-card" aria-labelledby="daily-statistics-title">
          <div class="admin-card__header"><h2 id="daily-statistics-title">每日明细</h2></div>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th class="admin-numeric">新增账号</th>
                  <th class="admin-numeric">活跃人数</th>
                  <th class="admin-numeric">提问量</th>
                  <th class="admin-numeric">提交练习</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="day in data.daily" :key="day.date">
                  <td>{{ day.date }}</td>
                  <td class="admin-numeric">{{ formatNumber(day.new_users) }}</td>
                  <td class="admin-numeric">{{ formatNumber(day.active_users) }}</td>
                  <td class="admin-numeric">{{ formatNumber(day.questions) }}</td>
                  <td class="admin-numeric">{{ formatNumber(day.submissions) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!data.daily.length" class="admin-empty">暂无每日记录</p>
        </section>
        <section class="admin-card" aria-labelledby="source-statistics-title">
          <div class="admin-card__header">
            <div>
              <h2 id="source-statistics-title">注册来源</h2>
              <p>按邀请码或注册方式查看新增账号及后续活跃情况</p>
            </div>
          </div>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>来源</th>
                  <th class="admin-numeric">注册人数</th>
                  <th class="admin-numeric">活跃人数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="source in data.sources" :key="source.name">
                  <td>{{ source.name }}</td>
                  <td class="admin-numeric">{{ formatNumber(source.registered_users) }}</td>
                  <td class="admin-numeric">{{ formatNumber(source.active_users) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!data.sources.length" class="admin-empty">所选范围暂无注册来源记录</p>
        </section>
      </template>
      <p class="admin-note">
        活跃指至少提问或提交练习一次；同一用户在全站去重。练习完成率按同批次已发布练习计算，回答状态仅覆盖已保存记录。
      </p>
      <p class="admin-note">{{ data.coverage_note }} · 截至 {{ formatDate(data.as_of) }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { adminApi } from '../../api/admin'
import { coursesApi } from '../../api/courses'
import { useAdminResource } from '../../composables/useAdminResource'
import { useAuthStore } from '../../stores/auth'
import { dateInputValue, errorMessage, formatDate, formatNumber, formatPercent } from '../../utils/admin'
import AdminActivityChart from './AdminActivityChart.vue'

const props = defineProps({ detailed: Boolean })
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)
const period = ref('30')
const filters = reactive({ start: '', end: '', course_id: '' })
const appliedFilters = ref({})
const filterError = ref('')
const exportError = ref('')
const exporting = ref(false)
const courses = ref([])
const courseError = ref(false)
const signals = ref(null)
const { data, loading, error, load } = useAdminResource(() => adminApi.statistics(appliedFilters.value))
const metrics = computed(() => {
  const previous = data.value.previous || {}
  const usage = data.value.usage
  return [
    {
      label: '活跃用户',
      value: formatNumber(usage.active_users),
      hint: '所选范围内的去重学习用户',
      delta: deltaLabel(usage.active_users, previous.active_users)
    },
    {
      label: '新增账号',
      value: formatNumber(data.value.accounts.new_users),
      hint: '所选时间内的全站注册账号',
      delta: deltaLabel(data.value.accounts.new_users, previous.new_users)
    },
    {
      label: '提问次数',
      value: formatNumber(usage.questions),
      hint: '按独立提问轮次统计',
      delta: deltaLabel(usage.questions, previous.questions)
    },
    {
      label: '练习完成率',
      value: formatPercent(usage.completion_rate),
      hint: '所选期间发布的练习，截至当前的提交比例',
      delta: rateDelta(usage.completion_rate, previous.completion_rate)
    }
  ]
})
const signalItems = computed(() => {
  const payload = signals.value
  if (!payload) return []
  const items = []
  const capacity = payload.capacity
  if (capacity.remaining != null) {
    if (capacity.remaining <= 0) {
      items.push({
        tone: 'danger',
        text: `全站账号容量已用尽（${capacity.total_users}/${capacity.max_users}），新账号无法注册。`,
        to: '/admin/registration'
      })
    } else if (capacity.remaining <= Math.max(5, Math.round(capacity.max_users * 0.1))) {
      items.push({
        tone: 'warn',
        text: `全站账号容量仅剩 ${capacity.remaining} 个名额（已用 ${capacity.total_users}/${capacity.max_users}）。`,
        to: '/admin/registration'
      })
    }
  }
  if (payload.invitations.exhausted) {
    items.push({
      tone: 'warn',
      text: `${payload.invitations.exhausted} 个邀请码次数已用尽，需要时请提高上限或新建。`,
      to: '/admin/registration'
    })
  }
  if (payload.invitations.expiring) {
    items.push({ tone: 'warn', text: `${payload.invitations.expiring} 个邀请码将在 7 天内过期。`, to: '/admin/registration' })
  }
  const answers = payload.answers
  if (answers.errors >= 5 && answers.errors >= answers.previous_errors * 2) {
    items.push({
      tone: 'danger',
      text: `近 7 天回答失败 ${answers.errors} 次${answers.previous_errors ? `，上一周期为 ${answers.previous_errors} 次` : ''}。`
    })
  }
  return items
})
const accountRows = computed(() => [
  { label: '账号总数', value: data.value.accounts.total },
  { label: '正常 / 已停用', value: `${data.value.accounts.active} / ${data.value.accounts.disabled}` },
  { label: '学生', value: data.value.accounts.roles.student },
  { label: '统计查看者', value: data.value.accounts.roles.observer },
  { label: '管理员', value: data.value.accounts.roles.admin }
])
const usageRows = computed(() => [
  { label: '期间发布练习', value: formatNumber(data.value.usage.assessments_assigned) },
  { label: '期间提交练习', value: formatNumber(data.value.usage.assessments_submitted) },
  { label: '会话数', value: formatNumber(data.value.usage.sessions) },
  { label: '作答正确率', value: formatPercent(data.value.usage.accuracy) },
  { label: '回答完成', value: formatNumber(data.value.usage.answers_completed) },
  { label: '主动停止', value: formatNumber(data.value.usage.answers_stopped) },
  { label: '回答失败', value: formatNumber(data.value.usage.answers_error) }
])
function deltaLabel(current, previous) {
  if (previous == null || previous === 0) return ''
  const change = ((current - previous) / previous) * 100
  if (!change) return ''
  const rounded = Math.abs(change) >= 10 ? Math.round(change) : Math.round(change * 10) / 10
  return `较上一周期 ${change > 0 ? '↑' : '↓'} ${Math.abs(rounded)}%`
}
function rateDelta(current, previous) {
  if (current == null || previous == null) return ''
  const diff = (current - previous) * 100
  if (!diff) return ''
  return `较上一周期 ${diff > 0 ? '↑' : '↓'} ${Math.abs(Math.round(diff * 10) / 10)} 个百分点`
}
function changePeriod() {
  if (period.value === 'custom') return
  const end = new Date()
  const start = new Date(end.getTime() - (Number(period.value) - 1) * 86400000)
  filters.start = dateInputValue(start)
  filters.end = dateInputValue(end)
}
function onPeriodChange() {
  changePeriod()
  if (period.value !== 'custom') applyFilters()
}
function applyFilters() {
  filterError.value = ''
  exportError.value = ''
  if (!filters.start || !filters.end || filters.start > filters.end) {
    filterError.value = '请选择有效的日期范围，开始日期不能晚于结束日期。'
    return
  }
  appliedFilters.value = {
    start: filters.start,
    end: filters.end,
    ...(filters.course_id ? { course_id: filters.course_id } : {})
  }
  load()
}
async function loadCourses() {
  courseError.value = false
  try {
    courses.value = (await coursesApi.list()).courses
  } catch {
    courseError.value = true
  }
}
async function loadSignals() {
  try {
    signals.value = await adminApi.signals()
  } catch {
    signals.value = null
  }
}
async function exportCsv() {
  exporting.value = true
  exportError.value = ''
  try {
    const blob = await adminApi.exportStatistics(appliedFilters.value)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `学习统计-${data.value.start}-${data.value.end}.csv`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {
    exportError.value = errorMessage(cause)
  } finally {
    exporting.value = false
  }
}
onMounted(() => {
  changePeriod()
  applyFilters()
  loadCourses()
  if (!props.detailed && authStore.isAdmin) loadSignals()
})
</script>
