<template>
  <main class="profile-page">
    <header class="profile-header">
      <div class="profile-header__copy">
        <p class="profile-eyebrow">学习画像</p>
        <h1>学习档案与诊断建议</h1>
        <p class="profile-header__subtitle">
          基于你的近期提问、课程进度和薄弱点信号，整理一份可行动的学习画像。
        </p>
      </div>

      <div class="profile-header__actions">
        <el-button text @click="goBack">
          <el-icon class="mr-1"><ArrowLeft /></el-icon>
          返回对话
        </el-button>
        <el-button plain :loading="profileStore.loading" @click="refreshProfile">刷新画像</el-button>
      </div>
    </header>

    <el-skeleton v-if="profileStore.loading && !detail" :rows="8" animated />

    <template v-else-if="detail">
      <section class="profile-summary panel">
        <div class="profile-summary__main">
          <p class="section-kicker">Profile Summary</p>
          <h2>{{ profileHeadline }}</h2>
          <p>{{ profileNarrative }}</p>

          <div class="summary-facts">
            <div class="summary-fact">
              <span>当前关注</span>
              <strong>{{ focusConceptText }}</strong>
            </div>
            <div class="summary-fact">
              <span>学习状态</span>
              <strong>{{ learningStateText }}</strong>
            </div>
            <div class="summary-fact">
              <span>主要风险</span>
              <strong>{{ riskText }}</strong>
            </div>
          </div>
        </div>

        <div class="profile-summary__stats" aria-label="画像统计">
          <div class="summary-stat">
            <span>近期知识点</span>
            <strong>{{ recentConcepts.length }}</strong>
          </div>
          <div class="summary-stat">
            <span>活跃薄弱点</span>
            <strong>{{ activeWeakSpots.length }}</strong>
          </div>
          <div class="summary-stat">
            <span>待观察</span>
            <strong>{{ pendingWeakSpots.length }}</strong>
          </div>
          <div class="summary-stat">
            <span>已克服</span>
            <strong>{{ detail.stats.total_resolved_weak_spots }}</strong>
          </div>
        </div>
      </section>

      <section class="profile-layout">
        <div class="profile-main-column">
          <article class="panel">
            <div class="panel__header">
              <div>
                <p class="section-kicker">Recent Focus</p>
                <h2>近期关注</h2>
              </div>
              <span class="panel__hint">最近在对话里反复出现的概念</span>
            </div>

            <div v-if="recentConcepts.length" class="concept-list">
              <div
                v-for="concept in recentConcepts.slice(0, 6)"
                :key="concept.concept_id"
                class="concept-row"
              >
                <div class="concept-row__body">
                  <strong>{{ concept.display_name }}</strong>
                  <div class="row-meta">
                    <span>{{ concept.chapter || '未分类章节' }}</span>
                    <span v-if="concept.last_question_type">{{ concept.last_question_type }}</span>
                  </div>
                </div>
                <span class="count-chip">x{{ concept.mention_count }}</span>
              </div>
            </div>
            <div v-else class="empty-note">还没有形成稳定的近期关注点。</div>
          </article>

          <article class="panel">
            <div class="panel__header">
              <div>
                <p class="section-kicker">Diagnosis</p>
                <h2>薄弱点诊断</h2>
              </div>
              <span class="panel__hint">可手动将已经掌握的知识点移出活跃列表</span>
            </div>

            <div v-if="activeWeakSpots.length" class="weakspot-list">
              <div
                v-for="spot in activeWeakSpots"
                :key="spot.concept_id"
                class="weakspot-row weakspot-row--active"
              >
                <div class="weakspot-row__body">
                  <div class="weakspot-row__title">
                    <strong>{{ spot.display_name }}</strong>
                    <span class="confidence-chip">{{ Math.round(spot.confidence * 100) }}%</span>
                  </div>
                  <div class="row-meta">
                    <span>讲解次数 {{ spot.clarification_count }}</span>
                    <span>{{ formatTime(spot.last_triggered_at) }}</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="text-action"
                  :disabled="resolvingConceptId === spot.concept_id"
                  @click="handleResolveWeakSpot(spot)"
                >
                  {{ resolvingConceptId === spot.concept_id ? '处理中…' : '已掌握' }}
                </button>
              </div>
            </div>
            <div v-else class="empty-note">暂无活跃薄弱点。</div>

            <div v-if="pendingWeakSpots.length" class="subsection">
              <h3>待观察信号</h3>
              <div class="compact-list">
                <div
                  v-for="spot in pendingWeakSpots.slice(0, 4)"
                  :key="spot.concept_id"
                  class="compact-row"
                >
                  <span>{{ spot.display_name }}</span>
                  <small>出现讲解 {{ spot.clarification_count }} 次</small>
                </div>
              </div>
            </div>
          </article>
        </div>

        <aside class="profile-side-column">
          <article class="panel panel--advice">
            <div class="panel__header">
              <div>
                <p class="section-kicker">Next Step</p>
                <h2>下一步建议</h2>
              </div>
            </div>

            <ol class="advice-list">
              <li v-for="item in nextStepSuggestions" :key="item">{{ item }}</li>
            </ol>
          </article>

          <article class="panel">
            <div class="panel__header">
              <div>
                <p class="section-kicker">Trace</p>
                <h2>学习轨迹</h2>
              </div>
            </div>

            <div v-if="chapterStats.length" class="chapter-bars">
              <div
                v-for="item in chapterStats.slice(0, 6)"
                :key="item.chapter"
                class="chapter-bar"
              >
                <div class="chapter-bar__meta">
                  <span>{{ item.chapter }}</span>
                  <strong>{{ item.count }}</strong>
                </div>
                <div class="chapter-bar__track">
                  <div class="chapter-bar__fill" :style="{ width: `${item.width}%` }" />
                </div>
              </div>
            </div>
            <div v-else class="empty-note">暂无章节轨迹。</div>

            <div v-if="activityItems.length" class="activity-strip">
              <div
                v-for="item in activityItems.slice(-7)"
                :key="item.day"
                class="activity-strip__item"
              >
                <span>{{ item.day }}</span>
                <strong>{{ item.count }}</strong>
              </div>
            </div>
          </article>

          <article class="panel">
            <div class="panel__header">
              <div>
                <p class="section-kicker">Resolved</p>
                <h2>已克服记录</h2>
              </div>
            </div>

            <div v-if="resolvedWeakSpots.length" class="compact-list">
              <div
                v-for="spot in resolvedWeakSpots.slice(0, 5)"
                :key="`${spot.concept_id}-${spot.resolved_at || spot.last_triggered_at}`"
                class="compact-row"
              >
                <span>{{ spot.display_name }}</span>
                <small>{{ formatTime(spot.resolved_at) }}</small>
              </div>
            </div>
            <div v-else class="empty-note">还没有记录到已克服的薄弱点。</div>
          </article>
        </aside>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { DEFAULT_STUDENT_ID } from '../config'
import { useProfileStore } from '../stores/profile'

const router = useRouter()
const profileStore = useProfileStore()
const resolvingConceptId = ref(null)

const detail = computed(() => profileStore.detail)
const recentConcepts = computed(() => detail.value?.recent_concepts || [])
const activeWeakSpots = computed(() => detail.value?.weak_spots || [])
const pendingWeakSpots = computed(() => detail.value?.pending_weak_spots || [])
const resolvedWeakSpots = computed(() => detail.value?.resolved_weak_spots || [])

const focusConceptText = computed(() => {
  const names = recentConcepts.value.slice(0, 3).map(concept => concept.display_name).filter(Boolean)
  return names.length ? names.join(' / ') : '尚未稳定识别'
})

const profileHeadline = computed(() => {
  const chapter = detail.value?.progress?.current_chapter
  if (chapter) return `当前主要围绕「${chapter}」学习。`
  return '正在根据你的对话形成学习画像。'
})

const profileNarrative = computed(() => {
  if (activeWeakSpots.value.length) {
    return '系统已经捕捉到一些需要巩固的知识点，建议先做小范围复习，再通过例题确认是否真正掌握。'
  }
  if (pendingWeakSpots.value.length) {
    return '目前有一些待观察信号，可以继续通过追问和练习确认它们是否会发展成稳定薄弱点。'
  }
  return '目前没有明显薄弱点，可以继续围绕近期关注概念做拓展练习，保持学习节奏。'
})

const learningStateText = computed(() => {
  if (activeWeakSpots.value.length) return `${activeWeakSpots.value.length} 个知识点需要巩固`
  if (pendingWeakSpots.value.length) return `${pendingWeakSpots.value.length} 个知识点正在观察`
  return '状态稳定，继续积累对话信号'
})

const riskText = computed(() => {
  const active = activeWeakSpots.value.length
  const pending = pendingWeakSpots.value.length
  if (active && pending) return `${active} 个活跃薄弱点，${pending} 个待观察信号`
  if (active) return `${active} 个活跃薄弱点`
  if (pending) return `${pending} 个待观察信号`
  return '暂无明显风险'
})

const nextStepSuggestions = computed(() => {
  const suggestions = []

  activeWeakSpots.value.slice(0, 2).forEach(spot => {
    suggestions.push(`优先复习「${spot.display_name}」，用一道例题确认理解。`)
  })

  if (pendingWeakSpots.value.length) {
    suggestions.push(`继续追问「${pendingWeakSpots.value[0].display_name}」，判断是否只是暂时卡顿。`)
  }

  if (recentConcepts.value.length) {
    suggestions.push(`围绕「${recentConcepts.value[0].display_name}」整理一页概念笔记。`)
  }

  const chapter = detail.value?.progress?.current_chapter
  if (chapter) {
    suggestions.push(`回顾「${chapter}」的核心定义、公式和案例。`)
  }

  if (!suggestions.length) {
    suggestions.push('先完成 3～5 个课程概念提问，让系统形成更稳定的画像。')
    suggestions.push('每次学习后用一句话总结“我现在还不确定什么”。')
  }

  return [...new Set(suggestions)].slice(0, 4)
})

const chapterStats = computed(() => {
  const stats = detail.value?.chapter_stats || {}
  const entries = Object.entries(stats)
  const maxValue = Math.max(...entries.map(([, count]) => count), 1)

  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([chapter, count]) => ({
      chapter,
      count,
      width: Math.max(18, Math.round((count / maxValue) * 100))
    }))
})

const activityItems = computed(() => {
  const stats = detail.value?.daily_activity || {}
  return Object.entries(stats).map(([day, count]) => ({ day, count }))
})

function formatTime(value) {
  if (!value) return '刚形成'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚形成'
  return date.toLocaleString([], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

async function loadProfile(showToast = false) {
  await profileStore.fetchDetail(DEFAULT_STUDENT_ID)
  await profileStore.fetchSummary(DEFAULT_STUDENT_ID)
  if (showToast) {
    ElMessage.success('画像已刷新')
  }
}

async function refreshProfile() {
  await loadProfile(true)
}

async function handleResolveWeakSpot(spot) {
  if (!spot?.concept_id || resolvingConceptId.value) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认把“${spot.display_name}”从活跃薄弱点中移除吗？它会保留到已克服历史里。`,
      '手动移除薄弱点',
      { type: 'warning' }
    )
  } catch (error) {
    return
  }

  resolvingConceptId.value = spot.concept_id
  try {
    await profileStore.resolveWeakSpot(DEFAULT_STUDENT_ID, spot.concept_id)
    await loadProfile()
    ElMessage.success('已移出活跃薄弱点')
  } catch (error) {
    const status = error?.response?.status
    if (status === 404) {
      await loadProfile()
      ElMessage.warning('这个薄弱点状态已经变化，我已为你刷新画像')
      return
    }
    ElMessage.error('移除薄弱点失败，请稍后再试')
  } finally {
    resolvingConceptId.value = null
  }
}

function goBack() {
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.push('/chat')
}

onMounted(async () => {
  await loadProfile()
})
</script>

<style scoped>
.profile-page {
  min-height: 100vh;
  padding: 30px;
  color: #1c1917;
  background:
    radial-gradient(circle at top left, rgba(245, 158, 11, 0.12), transparent 26%),
    radial-gradient(circle at 82% 12%, rgba(79, 70, 229, 0.10), transparent 30%),
    radial-gradient(circle at right center, rgba(20, 184, 166, 0.08), transparent 30%),
    linear-gradient(140deg, #fafaf9 0%, #f8fafc 46%, #eef2ff 100%);
  overflow-y: auto;
}

.profile-header,
.profile-summary,
.profile-layout {
  width: min(100%, 1120px);
  margin-inline: auto;
}

.profile-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 18px;
}

.profile-header__copy {
  max-width: 680px;
}

.profile-eyebrow,
.section-kicker {
  margin: 0 0 7px;
  color: #78716c;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.profile-header h1 {
  margin: 0;
  color: #1c1917;
  font-size: clamp(28px, 4vw, 44px);
  font-weight: 760;
  line-height: 1.12;
  letter-spacing: -0.04em;
}

.profile-header__subtitle {
  max-width: 620px;
  margin: 12px 0 0;
  color: #57534e;
  line-height: 1.7;
}

.profile-header__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.panel {
  color: #1c1917;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(214, 211, 209, 0.62);
  border-radius: 22px;
  box-shadow: none;
  backdrop-filter: blur(14px);
}

.profile-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 18px;
  padding: 22px;
  margin-bottom: 18px;
}

.profile-summary__main h2 {
  margin: 0;
  font-size: 23px;
  line-height: 1.3;
  letter-spacing: -0.02em;
}

.profile-summary__main p:not(.section-kicker) {
  max-width: 720px;
  margin: 10px 0 0;
  color: #57534e;
  line-height: 1.72;
}

.summary-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.summary-fact {
  min-width: 0;
  padding: 12px;
  background: rgba(248, 250, 252, 0.68);
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 16px;
}

.summary-fact span,
.summary-stat span,
.panel__hint,
.row-meta,
.compact-row small,
.activity-strip__item span {
  color: #78716c;
  font-size: 12px;
}

.summary-fact strong {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: #292524;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.profile-summary__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.summary-stat {
  padding: 14px;
  background: rgba(250, 250, 249, 0.72);
  border: 1px solid rgba(231, 229, 228, 0.72);
  border-radius: 18px;
}

.summary-stat strong {
  display: block;
  margin-top: 7px;
  color: #1c1917;
  font-size: 26px;
  line-height: 1;
}

.profile-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
  gap: 18px;
}

.profile-main-column,
.profile-side-column {
  display: grid;
  gap: 18px;
  align-content: start;
}

.profile-layout .panel {
  padding: 18px;
}

.panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.panel__header h2 {
  margin: 0;
  font-size: 18px;
  letter-spacing: -0.02em;
}

.panel__hint {
  max-width: 240px;
  text-align: right;
  line-height: 1.45;
}

.concept-list,
.weakspot-list,
.compact-list,
.chapter-bars {
  display: grid;
  gap: 9px;
}

.concept-row,
.weakspot-row,
.compact-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 12px;
  background: rgba(250, 250, 249, 0.72);
  border: 1px solid rgba(231, 229, 228, 0.72);
  border-radius: 15px;
}

.concept-row__body,
.weakspot-row__body {
  min-width: 0;
}

.concept-row strong,
.weakspot-row strong,
.compact-row span {
  color: #292524;
  font-weight: 720;
}

.weakspot-row__title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 5px;
}

.count-chip,
.confidence-chip {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 9px;
  color: #57534e;
  background: rgba(28, 25, 23, 0.05);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 760;
}

.weakspot-row--active {
  border-color: rgba(180, 83, 9, 0.18);
  background: rgba(255, 251, 235, 0.58);
}

.text-action {
  flex-shrink: 0;
  min-height: 30px;
  padding: 0 11px;
  color: #57534e;
  background: transparent;
  border: 1px solid rgba(214, 211, 209, 0.78);
  border-radius: 999px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 760;
  transition: background 0.16s ease, color 0.16s ease, border-color 0.16s ease;
}

.text-action:hover:not(:disabled) {
  color: #292524;
  background: rgba(28, 25, 23, 0.05);
}

.text-action:disabled {
  cursor: default;
  opacity: 0.58;
}

.subsection {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid rgba(231, 229, 228, 0.72);
}

.subsection h3 {
  margin: 0 0 10px;
  color: #57534e;
  font-size: 13px;
}

.panel--advice {
  background: rgba(255, 255, 255, 0.78);
}

.advice-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: advice;
}

.advice-list li {
  position: relative;
  padding: 10px 12px 10px 38px;
  color: #292524;
  background: rgba(248, 250, 252, 0.72);
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 15px;
  line-height: 1.55;
  counter-increment: advice;
}

.advice-list li::before {
  content: counter(advice);
  position: absolute;
  left: 11px;
  top: 11px;
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  color: #57534e;
  background: rgba(28, 25, 23, 0.06);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
}

.chapter-bar__meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  color: #44403c;
  font-size: 13px;
}

.chapter-bar__meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-bar__track {
  height: 7px;
  overflow: hidden;
  background: rgba(231, 229, 228, 0.84);
  border-radius: 999px;
}

.chapter-bar__fill {
  height: 100%;
  background: #78716c;
  border-radius: inherit;
}

.activity-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(58px, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.activity-strip__item {
  padding: 9px;
  background: rgba(250, 250, 249, 0.72);
  border: 1px solid rgba(231, 229, 228, 0.72);
  border-radius: 13px;
}

.activity-strip__item strong {
  display: block;
  margin-top: 4px;
  font-size: 16px;
}

.empty-note {
  padding: 18px;
  color: #78716c;
  text-align: center;
  background: rgba(250, 250, 249, 0.58);
  border: 1px dashed rgba(214, 211, 209, 0.78);
  border-radius: 16px;
}

:global(html.theme-dark) .profile-page {
  color: var(--dark-text);
  background: var(--dark-bg);
}

:global(html.theme-dark) .profile-header h1,
:global(html.theme-dark) .profile-summary__main h2,
:global(html.theme-dark) .summary-stat strong,
:global(html.theme-dark) .summary-fact strong,
:global(html.theme-dark) .panel__header h2,
:global(html.theme-dark) .concept-row strong,
:global(html.theme-dark) .weakspot-row strong,
:global(html.theme-dark) .compact-row span,
:global(html.theme-dark) .advice-list li,
:global(html.theme-dark) .chapter-bar__meta {
  color: var(--dark-text);
}

:global(html.theme-dark) .profile-header__subtitle,
:global(html.theme-dark) .profile-summary__main p:not(.section-kicker),
:global(html.theme-dark) .profile-eyebrow,
:global(html.theme-dark) .section-kicker,
:global(html.theme-dark) .summary-fact span,
:global(html.theme-dark) .summary-stat span,
:global(html.theme-dark) .panel__hint,
:global(html.theme-dark) .row-meta,
:global(html.theme-dark) .compact-row small,
:global(html.theme-dark) .activity-strip__item span,
:global(html.theme-dark) .empty-note {
  color: var(--dark-text-muted);
}

:global(html.theme-dark) .panel,
:global(html.theme-dark) .profile-summary {
  background: var(--dark-panel);
  border-color: var(--dark-border);
  backdrop-filter: none;
}

:global(html.theme-dark) .summary-fact,
:global(html.theme-dark) .summary-stat,
:global(html.theme-dark) .concept-row,
:global(html.theme-dark) .weakspot-row,
:global(html.theme-dark) .compact-row,
:global(html.theme-dark) .advice-list li,
:global(html.theme-dark) .activity-strip__item {
  background: var(--dark-panel-soft);
  border-color: var(--dark-border);
}

:global(html.theme-dark) .weakspot-row--active {
  background: rgba(245, 158, 11, 0.10);
  border-color: rgba(245, 158, 11, 0.22);
}

:global(html.theme-dark) .count-chip,
:global(html.theme-dark) .confidence-chip,
:global(html.theme-dark) .advice-list li::before {
  color: var(--dark-text-muted);
  background: rgba(255, 255, 255, 0.08);
}

:global(html.theme-dark) .text-action {
  color: var(--dark-text-muted);
  border-color: var(--dark-border);
}

:global(html.theme-dark) .text-action:hover:not(:disabled) {
  color: var(--dark-text);
  background: var(--dark-hover);
}

:global(html.theme-dark) .subsection {
  border-top-color: var(--dark-border-soft);
}

:global(html.theme-dark) .chapter-bar__track {
  background: var(--dark-bg-subtle);
}

:global(html.theme-dark) .chapter-bar__fill {
  background: var(--dark-text-faint);
}

:global(html.theme-dark) .empty-note {
  background: transparent;
  border-color: var(--dark-border);
}

@media (max-width: 980px) {
  .profile-summary,
  .profile-layout {
    grid-template-columns: 1fr;
  }

  .summary-facts {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .profile-page {
    padding: 18px;
  }

  .profile-header {
    flex-direction: column;
  }

  .profile-header__actions {
    width: 100%;
  }

  .profile-summary,
  .profile-layout .panel {
    padding: 16px;
  }

  .profile-summary__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .panel__header,
  .concept-row,
  .weakspot-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .panel__hint {
    max-width: none;
    text-align: left;
  }
}
</style>
