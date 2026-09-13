<template>
  <main class="profile-page">
    <header class="profile-header">
      <div>
        <h1>学习画像</h1>
      </div>
      <div class="profile-header__actions">
        <el-dropdown trigger="click" @command="handlePeriodChange">
          <button type="button" class="profile-filter-button" :disabled="profileStore.loading">
            <el-icon><Calendar /></el-icon>{{ selectedPeriodLabel }}<el-icon><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="option in periodOptions" :key="option.days" :command="option.days" :disabled="option.days === selectedPeriodDays">
                {{ option.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button type="button" class="profile-filter-button" :disabled="profileStore.loading" @click="refreshProfile">
          <el-icon :class="{ 'is-spinning': profileStore.loading }"><Refresh /></el-icon>刷新
        </button>
        <button type="button" class="profile-filter-button profile-filter-button--icon" aria-label="更多操作" title="更多操作"><el-icon><MoreFilled /></el-icon></button>
      </div>
    </header>

    <div v-if="profileStore.loading && !detail" class="profile-loading" aria-live="polite">
      <span class="profile-loading__pulse" />
      正在整理学习信号…
    </div>

    <div v-else-if="loadError && !detail" class="profile-error" role="alert">
      <el-icon><Warning /></el-icon>
      <div>
        <strong>学习画像暂时无法加载</strong>
        <p>{{ loadError }}</p>
      </div>
      <el-button plain @click="loadProfile()">重新加载</el-button>
    </div>

    <template v-else-if="detail">
      <div class="profile-dashboard">
        <div class="profile-main-column">
          <section class="profile-overview" aria-labelledby="profile-summary-title">
            <div class="profile-overview__copy">
              <div class="profile-overview__content">
                <span class="status-label">当前学习信号</span>
                <h2 id="profile-summary-title">优先巩固：{{ activeWeakSpots[0]?.display_name || '暂无稳定薄弱点' }}</h2>
                <div class="overview-context">
                  <span><el-icon><Aim /></el-icon>当前关注：{{ focusConceptText }}</span>
                  <span><el-icon><Reading /></el-icon>{{ currentChapterText }}</span>
                </div>
              </div>
              <div class="profile-recommendation__actions">
                <button type="button" class="primary-action" @click="askAboutConcept(activeWeakSpots[0]?.display_name || focusConceptText, '复习')">
                  开始巩固 <el-icon><ArrowRight /></el-icon>
                </button>
              </div>
            </div>
          </section>

          <div class="profile-content">
            <section class="profile-knowledge-panel" aria-labelledby="knowledge-title">
            <div class="profile-panel-heading">
              <div>
                <h2 id="knowledge-title">知识点</h2>
              </div>
              <label class="profile-search">
                <el-icon><Search /></el-icon>
                <input v-model="conceptSearch" aria-label="搜索知识点" placeholder="搜索知识点" />
              </label>
            </div>
            <div class="profile-tabs" role="tablist" aria-label="知识点状态筛选">
              <button v-for="tab in profileTabs" :key="tab.key" type="button" :class="{ active: activeProfileTab === tab.key }" @click="activeProfileTab = tab.key">
                {{ tab.label }} <span>{{ tab.count }}</span>
              </button>
            </div>
            <div class="profile-table" role="list" aria-label="知识点列表">
              <div
                v-for="item in visibleKnowledgeRows"
                :key="item.concept_id"
                class="profile-table__row profile-table__row--interactive"
                :class="{ 'profile-table__row--priority': item.statusKey === 'review' && item.concept_id === activeWeakSpots[0]?.concept_id }"
                role="button"
                tabindex="0"
                @click="openKnowledgeMap(item)"
                @keydown.enter="openKnowledgeMap(item)"
              >
                <div class="profile-table__concept">
                  <strong>{{ item.display_name }}</strong>
                  <span>{{ item.recordLabel }}</span>
                </div>
                <span class="profile-status" :class="`profile-status--${item.statusKey}`"><i />{{ item.status }}</span>
                <button type="button" class="profile-table__action" @click.stop="askAboutConcept(item.display_name, item.action)">
                  {{ item.actionLabel }} <el-icon><ArrowRight /></el-icon>
                </button>
                <el-icon class="profile-table__more"><MoreFilled /></el-icon>
              </div>
              <p v-if="!visibleKnowledgeRows.length" class="empty-copy">没有找到匹配的知识点。</p>
            </div>
            </section>
          </div>
        </div>

        <aside class="profile-sidebar" aria-label="学习概况">
          <section class="profile-sidebar__section" aria-labelledby="chapter-title">
            <div class="sidebar-heading">
              <h2 id="chapter-title">章节关注分布</h2>
              <button type="button" class="sidebar-link">查看全部 <el-icon><ArrowRight /></el-icon></button>
            </div>
            <div v-if="chapterStats.length" class="chapter-chart">
              <div v-for="item in chapterStats.slice(0, 7)" :key="item.chapter" class="chapter-chart__row">
                <div><span>{{ item.chapter }}</span><strong>{{ item.count }}</strong></div>
                <div class="chapter-chart__track"><span :style="{ width: `${item.width}%` }" /></div>
              </div>
            </div>
            <p v-else class="empty-copy">暂无章节互动记录。</p>
          </section>

          <section class="profile-sidebar__section" aria-labelledby="activity-title">
            <div class="sidebar-heading sidebar-heading--activity">
              <h2 id="activity-title">学习活动</h2>
              <span class="sidebar-period-label">{{ selectedPeriodLabel }}</span>
            </div>
            <div class="activity-total-row"><strong class="activity-total">{{ activityTotal }}</strong><span>次学习活动</span></div>
            <div v-if="activityItems.length" class="activity-chart" aria-label="最近七个活跃日的学习互动次数">
              <div v-for="item in activityItems" :key="item.day" class="activity-chart__day" :title="`${item.day}：${item.count} 次互动`">
                <span class="activity-chart__value">{{ item.count }}</span>
                <span class="activity-chart__bar" :style="{ height: `${activityHeight(item.count)}px`, opacity: activityOpacity(item.count) }" aria-hidden="true" />
                <small>{{ formatActivityDay(item.day) }}</small>
              </div>
            </div>
            <p v-else class="empty-copy">暂无近期活动记录。</p>
          </section>

          <section class="profile-sidebar__section" aria-labelledby="next-step-title">
            <div class="sidebar-heading">
              <h2 id="next-step-title">下一步</h2>
              <button type="button" class="sidebar-link">查看全部 <el-icon><ArrowRight /></el-icon></button>
            </div>
            <div class="next-step-list">
              <button v-for="(item, index) in nextStepSuggestions" :key="item" type="button" @click="askSuggestion(item)">
                <span>{{ index + 1 }}</span>
                <strong>{{ item }}</strong>
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>
          </section>
        </aside>
      </div>
    </template>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Aim, ArrowDown, ArrowRight, Calendar, MoreFilled, Reading, Refresh, Search, Warning } from '@element-plus/icons-vue'

import { useProfileStore } from '../stores/profile'

const router = useRouter()
const profileStore = useProfileStore()
const loadError = ref('')
const conceptSearch = ref('')
const activeProfileTab = ref('all')
const selectedPeriodDays = ref(7)
const periodOptions = [
  { days: 7, label: '最近 7 天' },
  { days: 30, label: '最近 1 个月' },
  { days: 90, label: '最近 3 个月' }
]

const detail = computed(() => profileStore.detail)
const selectedPeriodLabel = computed(() => periodOptions.find(option => option.days === selectedPeriodDays.value)?.label || '最近 7 天')
const recentConcepts = computed(() => detail.value?.recent_concepts || [])
const activeWeakSpots = computed(() => detail.value?.weak_spots || [])
const pendingWeakSpots = computed(() => detail.value?.pending_weak_spots || [])
const knowledgeRows = computed(() => {
  const rows = new Map()
  recentConcepts.value.forEach(concept => rows.set(concept.concept_id, {
    ...concept,
    recordLabel: `${concept.mention_count || 0} 次提及`,
    status: '近期关注',
    statusKey: 'recent',
    action: '梳理',
    actionLabel: '查看记录'
  }))
  pendingWeakSpots.value.forEach(spot => rows.set(spot.concept_id, {
    ...spot,
    recordLabel: `${spot.clarification_count || 0} 次讲解`,
    status: '待观察',
    statusKey: 'watching',
    action: '检查理解',
    actionLabel: '验证理解'
  }))
  activeWeakSpots.value.forEach(spot => rows.set(spot.concept_id, {
    ...spot,
    recordLabel: `${spot.evidence_count || 0} 条证据`,
    status: '重点巩固',
    statusKey: 'review',
    action: '复习',
    actionLabel: '去巩固'
  }))
  const priority = { review: 0, watching: 1, recent: 2 }
  return [...rows.values()].sort((left, right) => priority[left.statusKey] - priority[right.statusKey])
})
const profileTabs = computed(() => [
  { key: 'all', label: '全部', count: knowledgeRows.value.length },
  { key: 'review', label: '重点巩固', count: activeWeakSpots.value.length },
  { key: 'watching', label: '待观察', count: pendingWeakSpots.value.length },
  { key: 'recent', label: '近期关注', count: recentConcepts.value.length },
])
const visibleKnowledgeRows = computed(() => knowledgeRows.value.filter(item => {
  const matchesTab = activeProfileTab.value === 'all' || item.statusKey === activeProfileTab.value
  const matchesSearch = !conceptSearch.value.trim() || item.display_name.toLowerCase().includes(conceptSearch.value.trim().toLowerCase())
  return matchesTab && matchesSearch
}))
const focusConceptText = computed(() => {
  const names = recentConcepts.value.slice(0, 3).map(concept => concept.display_name).filter(Boolean)
  return names.length ? names.join('、') : '尚未稳定识别'
})

const currentChapterText = computed(() => {
  const chapter = detail.value?.progress?.current_chapter
  return chapter ? `主要集中在 ${chapter}` : '尚未形成稳定章节关注'
})

const profileNarrative = computed(() => {
  if (activeWeakSpots.value.length) {
    return '先处理高置信度薄弱点，再通过小题验证理解，能比重复阅读更快确认是否真正掌握。'
  }
  if (pendingWeakSpots.value.length) {
    return '目前没有稳定薄弱点，可以通过一次追问或练习判断待观察信号是否只是暂时卡顿。'
  }
  return '继续围绕近期关注概念做拓展练习，系统会根据新的学习信号更新诊断。'
})

const nextStepSuggestions = computed(() => {
  const suggestions = []
  activeWeakSpots.value.slice(0, 1).forEach(spot => suggestions.push(`巩固「${spot.display_name}」的核心概念`))
  if (pendingWeakSpots.value.length) suggestions.push(`验证「${pendingWeakSpots.value[0].display_name}」的理解`)
  if (recentConcepts.value.length) suggestions.push(`回顾「${recentConcepts.value[0].display_name}」的相关记录`)
  return [...new Set(suggestions)].slice(0, 3)
})

const chapterStats = computed(() => {
  const entries = Object.entries(detail.value?.chapter_stats || {})
  const maxValue = Math.max(...entries.map(([, count]) => count), 1)
  return entries
    .sort((left, right) => right[1] - left[1])
    .map(([chapter, count]) => ({ chapter, count, width: Math.max(8, Math.round((count / maxValue) * 100)) }))
})

const activityItems = computed(() => {
  const entries = Object.entries(detail.value?.daily_activity || {}).map(([day, count]) => ({ day, count }))
  if (entries.length <= 7) return entries

  const bucketSize = Math.ceil(entries.length / 7)
  return Array.from({ length: Math.ceil(entries.length / bucketSize) }, (_, index) => {
    const bucket = entries.slice(index * bucketSize, (index + 1) * bucketSize)
    return {
      day: `${formatActivityDay(bucket[0]?.day)}-${formatActivityDay(bucket[bucket.length - 1]?.day).slice(-5)}`,
      count: bucket.reduce((total, item) => total + item.count, 0)
    }
  })
})
const activityTotal = computed(() => activityItems.value.reduce((total, item) => total + item.count, 0))
const maxActivity = computed(() => Math.max(...activityItems.value.map(item => item.count), 1))

function activityOpacity(count) {
  return 0.25 + (count / maxActivity.value) * 0.75
}

function activityHeight(count) {
  return 18 + Math.round((count / maxActivity.value) * 72)
}

function formatActivityDay(value) {
  const match = String(value || '').match(/^(?:\d{4}-)?(\d{2})-(\d{2})$/)
  return match ? `${match[1]}-${match[2]}` : value
}

function askAboutConcept(concept, action) {
  router.push({ path: '/chat', query: { question: `请帮我${action}“${concept}”，结合我的学习情况进行讲解。` } })
}

function openKnowledgeMap(item) {
  if (!item?.concept_id) return
  router.push({ path: '/knowledge-map', query: { concept: item.concept_id } })
}

function askSuggestion(suggestion) {
  router.push({ path: '/chat', query: { question: `请带我完成这个学习任务：${suggestion}` } })
}

async function loadProfile(showToast = false) {
  loadError.value = ''
  try {
    await profileStore.fetchDetail(selectedPeriodDays.value)
    await profileStore.fetchSummary()
    if (showToast) ElMessage.success('画像已刷新')
  } catch (error) {
    console.error('加载学习画像失败:', error)
    loadError.value = '请检查网络连接后重试。'
    if (showToast) ElMessage.error('刷新画像失败')
  }
}

async function refreshProfile() {
  await loadProfile(true)
}

async function handlePeriodChange(days) {
  if (days === selectedPeriodDays.value) return
  selectedPeriodDays.value = days
  await loadProfile()
}

onMounted(loadProfile)
</script>

<style scoped src="../styles/profile.css"></style>
