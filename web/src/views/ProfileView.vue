<template>
  <main class="profile-page">
    <header class="profile-header">
      <div>
        <p class="profile-kicker">学习空间</p>
        <h1>学生画像</h1>
        <p>把近期学习信号整理成可观察、可行动的诊断视图。</p>
      </div>
      <button
        type="button"
        class="icon-button"
        :disabled="profileStore.loading"
        aria-label="刷新学生画像"
        title="刷新画像"
        @click="refreshProfile"
      >
        <el-icon :class="{ 'is-spinning': profileStore.loading }"><Refresh /></el-icon>
      </button>
    </header>

    <div v-if="profileStore.loading && !detail" class="profile-loading" aria-live="polite">
      <span class="profile-loading__pulse" />
      正在整理学习信号…
    </div>

    <div v-else-if="loadError && !detail" class="profile-error" role="alert">
      <el-icon><Warning /></el-icon>
      <div>
        <strong>学生画像暂时无法加载</strong>
        <p>{{ loadError }}</p>
      </div>
      <el-button plain @click="loadProfile()">重新加载</el-button>
    </div>

    <template v-else-if="detail">
      <section class="profile-overview" aria-labelledby="profile-summary-title">
        <div class="profile-overview__copy">
          <span class="status-label">当前诊断</span>
          <h2 id="profile-summary-title">{{ profileHeadline }}</h2>
          <p>{{ profileNarrative }}</p>
          <div class="overview-context">
            <span><el-icon><Aim /></el-icon>当前关注：{{ focusConceptText }}</span>
            <span><el-icon><Reading /></el-icon>{{ currentChapterText }}</span>
          </div>
        </div>

        <dl class="profile-metrics" aria-label="画像统计">
          <div>
            <dt>探索概念</dt>
            <dd>{{ recentConcepts.length }}</dd>
          </div>
          <div class="metric--warning">
            <dt>需要巩固</dt>
            <dd>{{ activeWeakSpots.length }}</dd>
          </div>
          <div class="metric--watching">
            <dt>待观察</dt>
            <dd>{{ pendingWeakSpots.length }}</dd>
          </div>
          <div class="metric--resolved">
            <dt>已克服</dt>
            <dd>{{ detail.stats.total_resolved_weak_spots }}</dd>
          </div>
        </dl>
      </section>

      <div class="profile-workspace">
        <div class="profile-primary">
          <section class="profile-section">
            <div class="section-heading"><h2>测验表现</h2></div>
            <div v-if="practice.length" class="signal-list">
              <button v-for="item in practice" :key="item.concept_id" type="button" class="signal-item" @click="askAboutConcept(item.display_name, '请结合我的测验表现讲解')">
                <strong>{{ item.display_name }}</strong>
                <span>最近 {{ item.recent_correct_count }} / {{ item.recent_answered_count }} 题正确</span>
                <small>{{ practiceLabels[item.level] }} · 累计 {{ item.answered_count }} 题</small>
              </button>
            </div>
            <p v-else class="empty-copy">暂无测验记录，掌握情况尚待了解。</p>
          </section>
          <section class="profile-section">
            <div class="section-heading">
              <div>
                <span class="section-label">Learning signals</span>
                <h2>学习信号分布</h2>
              </div>
              <p>点击知识点可直接发起针对性讨论</p>
            </div>

            <div class="signal-board">
              <article class="signal-lane signal-lane--recent">
                <header>
                  <span class="signal-dot" />
                  <strong>近期关注</strong>
                  <small>{{ recentConcepts.length }}</small>
                </header>
                <div v-if="recentConcepts.length" class="signal-list">
                  <button
                    v-for="concept in recentConcepts.slice(0, 6)"
                    :key="concept.concept_id"
                    type="button"
                    @click="askAboutConcept(concept.display_name, '梳理')"
                  >
                    <span>{{ concept.display_name }}</span>
                    <small>{{ concept.mention_count }} 次提及</small>
                  </button>
                </div>
                <p v-else class="empty-copy">继续提问后会形成关注分布。</p>
              </article>

              <article class="signal-lane signal-lane--watching">
                <header>
                  <span class="signal-dot" />
                  <strong>待观察</strong>
                  <small>{{ pendingWeakSpots.length }}</small>
                </header>
                <div v-if="pendingWeakSpots.length" class="signal-list">
                  <button
                    v-for="spot in pendingWeakSpots.slice(0, 5)"
                    :key="spot.concept_id"
                    type="button"
                    @click="askAboutConcept(spot.display_name, '检查理解')"
                  >
                    <span>{{ spot.display_name }}</span>
                    <small>{{ spot.clarification_count }} 次讲解</small>
                  </button>
                </div>
                <p v-else class="empty-copy">暂无需要继续观察的信号。</p>
              </article>

              <article class="signal-lane signal-lane--review">
                <header>
                  <span class="signal-dot" />
                  <strong>重点巩固</strong>
                  <small>{{ activeWeakSpots.length }}</small>
                </header>
                <div v-if="activeWeakSpots.length" class="signal-list">
                  <button
                    v-for="spot in activeWeakSpots.slice(0, 5)"
                    :key="spot.concept_id"
                    type="button"
                    @click="askAboutConcept(spot.display_name, '复习')"
                  >
                    <span>{{ spot.display_name }}</span>
                    <small>证据置信度 {{ formatPercent(spot.confidence) }}</small>
                  </button>
                </div>
                <p v-else class="empty-copy">目前没有稳定的薄弱点。</p>
              </article>
            </div>
          </section>

          <section class="profile-section">
            <div class="section-heading">
              <div>
                <span class="section-label">Diagnosis</span>
                <h2>薄弱点优先级</h2>
              </div>
              <p>置信度表示薄弱信号的稳定程度，不代表掌握度</p>
            </div>

            <div v-if="activeWeakSpots.length" class="risk-list">
              <article v-for="spot in activeWeakSpots" :key="spot.concept_id" class="risk-row">
                <div class="risk-row__heading">
                  <div>
                    <strong>{{ spot.display_name }}</strong>
                    <span>{{ spot.evidence_count }} 条证据 · {{ spot.clarification_count }} 次讲解</span>
                  </div>
                  <b>{{ formatPercent(spot.confidence) }}</b>
                </div>
                <div class="risk-track" aria-hidden="true">
                  <span :style="{ width: formatPercent(spot.confidence) }" />
                </div>
                <footer>
                  <span>最近触发 {{ formatTime(spot.last_triggered_at) }}</span>
                  <div>
                    <button type="button" @click="askAboutConcept(spot.display_name, '出一道理解题检查')">出题检查</button>
                    <button
                      type="button"
                      :disabled="resolvingConceptId === spot.concept_id"
                      @click="handleResolveWeakSpot(spot)"
                    >
                      {{ resolvingConceptId === spot.concept_id ? '处理中…' : '标记已掌握' }}
                    </button>
                  </div>
                </footer>
              </article>
            </div>
            <div v-else class="empty-state">
              <el-icon><CircleCheck /></el-icon>
              <strong>目前没有稳定薄弱点</strong>
              <span>继续围绕近期关注概念做练习即可。</span>
            </div>
          </section>
        </div>

        <aside class="profile-secondary">
          <section class="profile-section">
            <div class="section-heading section-heading--compact">
              <div>
                <span class="section-label">Attention</span>
                <h2>章节关注分布</h2>
              </div>
            </div>
            <div v-if="chapterStats.length" class="chapter-chart">
              <div v-for="item in chapterStats.slice(0, 7)" :key="item.chapter" class="chapter-chart__row">
                <div><span>{{ item.chapter }}</span><strong>{{ item.count }}</strong></div>
                <div class="chapter-chart__track"><span :style="{ width: `${item.width}%` }" /></div>
              </div>
            </div>
            <p v-else class="empty-copy">暂无章节互动记录。</p>
          </section>

          <section class="profile-section">
            <div class="section-heading section-heading--compact">
              <div>
                <span class="section-label">Last 7 active days</span>
                <h2>学习活动</h2>
              </div>
              <strong class="activity-total">{{ activityTotal }}</strong>
            </div>
            <div v-if="activityItems.length" class="activity-chart" aria-label="最近七个活跃日的学习互动次数">
              <div
                v-for="item in activityItems"
                :key="item.day"
                class="activity-chart__day"
                :title="`${item.day}：${item.count} 次互动`"
              >
                <span :style="{ opacity: activityOpacity(item.count) }">{{ item.count }}</span>
                <small>{{ item.day }}</small>
              </div>
            </div>
            <p v-else class="empty-copy">暂无近期活动记录。</p>
          </section>

          <section class="profile-section next-actions">
            <div class="section-heading section-heading--compact">
              <div>
                <span class="section-label">Next actions</span>
                <h2>下一步</h2>
              </div>
            </div>
            <button
              v-for="(item, index) in nextStepSuggestions"
              :key="item"
              type="button"
              @click="askSuggestion(item)"
            >
              <span>{{ index + 1 }}</span>
              <strong>{{ item }}</strong>
              <el-icon><ArrowRight /></el-icon>
            </button>
          </section>

          <section v-if="resolvedWeakSpots.length" class="profile-section">
            <div class="section-heading section-heading--compact">
              <div>
                <span class="section-label">Resolved</span>
                <h2>已克服记录</h2>
              </div>
            </div>
            <div class="resolved-list">
              <div v-for="spot in resolvedWeakSpots.slice(0, 5)" :key="spot.concept_id">
                <el-icon><CircleCheck /></el-icon>
                <span>{{ spot.display_name }}</span>
                <small>{{ formatTime(spot.resolved_at) }}</small>
              </div>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Aim, ArrowRight, CircleCheck, Reading, Refresh, Warning } from '@element-plus/icons-vue'

import { useProfileStore } from '../stores/profile'

const router = useRouter()
const profileStore = useProfileStore()
const resolvingConceptId = ref(null)
const loadError = ref('')

const detail = computed(() => profileStore.detail)
const recentConcepts = computed(() => detail.value?.recent_concepts || [])
const activeWeakSpots = computed(() => detail.value?.weak_spots || [])
const pendingWeakSpots = computed(() => detail.value?.pending_weak_spots || [])
const resolvedWeakSpots = computed(() => detail.value?.resolved_weak_spots || [])
const practice = computed(() => detail.value?.practice || [])
const practiceLabels = {
  needs_practice: '仍需巩固',
  practiced: '已有正确作答',
  ready_for_extension: '可尝试拓展'
}

const focusConceptText = computed(() => {
  const names = recentConcepts.value.slice(0, 3).map(concept => concept.display_name).filter(Boolean)
  return names.length ? names.join('、') : '尚未稳定识别'
})

const currentChapterText = computed(() => {
  const chapter = detail.value?.progress?.current_chapter
  return chapter ? `主要集中在 ${chapter}` : '尚未形成稳定章节关注'
})

const profileHeadline = computed(() => {
  if (activeWeakSpots.value.length) return `${activeWeakSpots.value.length} 个知识点需要优先巩固`
  if (pendingWeakSpots.value.length) return '学习状态稳定，部分知识点仍需观察'
  return '当前学习状态稳定'
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
  activeWeakSpots.value.slice(0, 2).forEach(spot => suggestions.push(`复习「${spot.display_name}」并完成一道理解题`))
  if (pendingWeakSpots.value.length) suggestions.push(`检查「${pendingWeakSpots.value[0].display_name}」是否已经理解`)
  if (recentConcepts.value.length) suggestions.push(`梳理「${recentConcepts.value[0].display_name}」的概念关系`)
  if (!suggestions.length) suggestions.push('从一个课程概念开始新的学习对话', '完成一道课程知识自测题')
  return [...new Set(suggestions)].slice(0, 4)
})

const chapterStats = computed(() => {
  const entries = Object.entries(detail.value?.chapter_stats || {})
  const maxValue = Math.max(...entries.map(([, count]) => count), 1)
  return entries
    .sort((left, right) => right[1] - left[1])
    .map(([chapter, count]) => ({ chapter, count, width: Math.max(8, Math.round((count / maxValue) * 100)) }))
})

const activityItems = computed(() => Object.entries(detail.value?.daily_activity || {}).map(([day, count]) => ({ day, count })))
const activityTotal = computed(() => activityItems.value.reduce((total, item) => total + item.count, 0))
const maxActivity = computed(() => Math.max(...activityItems.value.map(item => item.count), 1))

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`
}

function activityOpacity(count) {
  return 0.25 + (count / maxActivity.value) * 0.75
}

function formatTime(value) {
  if (!value) return '刚形成'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚形成'
  return date.toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function askAboutConcept(concept, action) {
  router.push({ path: '/chat', query: { question: `请帮我${action}“${concept}”，结合我的学习情况进行讲解。` } })
}

function askSuggestion(suggestion) {
  router.push({ path: '/chat', query: { question: `请带我完成这个学习任务：${suggestion}` } })
}

async function loadProfile(showToast = false) {
  loadError.value = ''
  try {
    await profileStore.fetchDetail()
    await profileStore.fetchSummary()
    if (showToast) ElMessage.success('画像已刷新')
  } catch (error) {
    console.error('加载学生画像失败:', error)
    loadError.value = '请检查网络连接后重试。'
    if (showToast) ElMessage.error('刷新画像失败')
  }
}

async function refreshProfile() {
  await loadProfile(true)
}

async function handleResolveWeakSpot(spot) {
  if (!spot?.concept_id || resolvingConceptId.value) return

  try {
    await ElMessageBox.confirm(
      `确认把“${spot.display_name}”标记为已掌握吗？它仍会保留在已克服记录中。`,
      '更新学习状态',
      { type: 'warning' }
    )
  } catch {
    return
  }

  resolvingConceptId.value = spot.concept_id
  try {
    await profileStore.resolveWeakSpot(spot.concept_id)
    await loadProfile()
    ElMessage.success('已更新学习状态')
  } catch (error) {
    if (error?.response?.status === 404) {
      await loadProfile()
      ElMessage.warning('该知识点状态已经变化，画像已刷新')
    } else {
      ElMessage.error('更新失败，请稍后再试')
    }
  } finally {
    resolvingConceptId.value = null
  }
}

onMounted(loadProfile)
</script>

<style scoped src="../styles/profile.css"></style>
