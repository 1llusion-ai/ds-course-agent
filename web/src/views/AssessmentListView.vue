<template>
  <main class="assessment-page assessment-list-page">
    <section class="assessment-list-toolbar">
      <div>
        <small>我的测验</small>
        <h1>{{ activeTab === 'active' ? '待完成测验' : '完成记录' }}</h1>
      </div>
      <div class="assessment-list-filters">
        <el-select v-model="sessionFilter" aria-label="筛选会话" placeholder="全部会话">
          <el-option label="全部会话" value="" />
          <el-option v-for="session in sessionStore.sortedSessions" :key="session.id" :label="session.title || '未命名会话'" :value="session.id" />
        </el-select>
        <el-segmented v-model="activeTab" :options="tabs" />
      </div>
    </section>

    <section class="assessment-list-content" aria-live="polite">
      <el-skeleton v-if="store.loading" :rows="6" animated />
      <div v-else-if="error" class="assessment-empty">
        <el-icon><Warning /></el-icon><h2>测验加载失败</h2><p>{{ error }}</p>
        <el-button plain @click="load">重新加载</el-button>
      </div>
      <div v-else-if="!visibleAssessments.length && !visiblePreparations.length" class="assessment-empty">
        <el-icon><DocumentChecked /></el-icon>
        <h2>{{ activeTab === 'active' ? '暂时没有待完成测验' : '还没有完成记录' }}</h2>
        <el-button v-if="activeTab === 'active'" plain @click="router.push(sessionFilter ? `/chat/${sessionFilter}` : '/chat')">
          <el-icon><ChatDotRound /></el-icon>继续对话
        </el-button>
      </div>
      <div v-else class="assessment-list">
        <article v-for="job in visiblePreparations" :key="job.id" class="assessment-list-item">
          <div class="assessment-list-item__status" :data-status="job.status">
            {{ job.status === 'failed' ? '准备失败' : job.status === 'generating' ? '准备中' : '待准备' }}
          </div>
          <div class="assessment-list-item__body">
            <h3>{{ job.display_name }}</h3>
            <p>{{ sessionTitle(job.session_id) }}</p>
          </div>
          <el-button v-if="job.status === 'failed'" plain :loading="retrying === job.id" @click="retry(job)">
            <el-icon><Refresh /></el-icon>重新准备
          </el-button>
          <el-icon v-else class="is-loading"><Loading /></el-icon>
        </article>
        <article v-for="item in visibleAssessments" :key="item.id" class="assessment-list-item">
          <div class="assessment-list-item__status" :data-status="item.status">
            {{ assessmentStatusText[item.status] }}
          </div>
          <div class="assessment-list-item__body">
            <h3>{{ item.title }}</h3>
            <p>{{ item.question_count }} 题 · {{ formatAssessmentTime(item.assigned_at) }}</p>
            <p v-if="item.session_id">{{ sessionTitle(item.session_id) }}</p>
          </div>
          <el-button type="primary" @click="open(item)">
            {{ item.status === 'submitted' ? '查看结果' : item.status === 'in_progress' ? '继续作答' : '开始作答' }}
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </article>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, ChatDotRound, DocumentChecked, Loading, Refresh, Warning } from '@element-plus/icons-vue'

import { assessmentsApi } from '../api/assessments'
import { useAssessmentStore } from '../stores/assessment'
import { useSessionStore } from '../stores/session'
import { assessmentStatusText, formatAssessmentTime } from '../utils/assessment'

const POLL_INTERVAL_MS = 10_000
const PENDING_PREPARATION_STATUSES = new Set(['pending', 'queued', 'generating'])

const router = useRouter()
const store = useAssessmentStore()
const sessionStore = useSessionStore()
const sessionFilter = ref(sessionStore.currentSessionId || '')
const activeTab = ref('active')
const error = ref('')
const retrying = ref('')
let pollTimer = null
let disposed = false
const visibleAssessments = computed(() => store.assessments.filter(item => !sessionFilter.value || item.session_id === sessionFilter.value))
const visiblePreparations = computed(() => activeTab.value === 'active'
  ? store.preparations.filter(job => job.status !== 'ready' && (!sessionFilter.value || job.session_id === sessionFilter.value))
  : [])
const hasPendingPreparation = computed(() => store.preparations.some(job => PENDING_PREPARATION_STATUSES.has(job.status)))
const tabs = [{ label: '待完成', value: 'active' }, { label: '已完成', value: 'completed' }]

function sessionTitle(sessionId) {
  return sessionStore.sessions.find(session => session.id === sessionId)?.title || '课程对话'
}

function clearPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function shouldPoll() {
  return !disposed
    && activeTab.value === 'active'
    && hasPendingPreparation.value
    && typeof document !== 'undefined'
    && !document.hidden
}

function schedulePolling() {
  clearPolling()
  if (!shouldPoll()) return
  pollTimer = window.setTimeout(() => load(true), POLL_INTERVAL_MS)
}

async function load(silent = false) {
  clearPolling()
  if (!silent) error.value = ''
  try {
    await store.fetchOverview(activeTab.value === 'active' ? ['ready', 'in_progress'] : ['submitted'], silent)
  } catch (requestError) {
    error.value = requestError.response?.data?.detail || '请稍后重试。'
  } finally {
    schedulePolling()
  }
}

async function retry(job) {
  retrying.value = job.id
  try {
    await assessmentsApi.retryPreparation(job.id)
    await load(true)
  } catch (requestError) {
    error.value = requestError.response?.data?.detail || '暂时无法准备测验。'
  } finally {
    retrying.value = ''
  }
}

function open(item) {
  router.push(item.status === 'submitted' ? `/assessments/${item.id}/result` : `/assessments/${item.id}`)
}

function handleVisibilityChange() {
  if (document.hidden) {
    clearPolling()
  } else if (shouldPoll()) {
    load(true)
  }
}

watch(activeTab, () => load())
onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  load()
})
onUnmounted(() => {
  disposed = true
  clearPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style src="../styles/assessment.css"></style>
