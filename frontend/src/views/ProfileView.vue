<template>
  <div class="profile-page">
    <section class="profile-hero">
      <div>
        <p class="profile-hero__eyebrow">Profile Intelligence</p>
        <h1 class="profile-hero__title">学习画像</h1>
        <p class="profile-hero__subtitle">
          这里展示的是结构化学习信号：最近关注点、待观察薄弱点、活跃薄弱点和已克服记录。
          先把画像做稳，再考虑更精细的知识点详情展示。
        </p>
      </div>
      <div class="profile-hero__actions">
        <el-button text @click="goBack">
          <el-icon class="mr-1"><ArrowLeft /></el-icon>
          返回对话
        </el-button>
        <el-button type="primary" plain @click="refreshProfile">刷新画像</el-button>
      </div>
    </section>

    <el-skeleton v-if="profileStore.loading && !detail" :rows="8" animated />

    <template v-else-if="detail">
      <section class="profile-metrics">
        <article class="metric-card metric-card--indigo">
          <span class="metric-card__label">当前章节</span>
          <strong class="metric-card__value">{{ detail.progress.current_chapter || '尚未稳定识别' }}</strong>
          <span class="metric-card__hint">基于最近连续提问聚合</span>
        </article>

        <article class="metric-card">
          <span class="metric-card__label">最近关注知识点</span>
          <strong class="metric-card__value">{{ detail.recent_concepts.length }}</strong>
          <span class="metric-card__hint">按最近提及时间排序，同时保留提及次数</span>
        </article>

        <article class="metric-card metric-card--sky">
          <span class="metric-card__label">待观察薄弱点</span>
          <strong class="metric-card__value">{{ detail.pending_weak_spots.length }}</strong>
          <span class="metric-card__hint">出现过一次澄清，后续会继续观察</span>
        </article>

        <article class="metric-card metric-card--amber">
          <span class="metric-card__label">活跃薄弱点</span>
          <strong class="metric-card__value">{{ detail.weak_spots.length }}</strong>
          <span class="metric-card__hint">目前仍需要继续巩固</span>
        </article>

        <article class="metric-card metric-card--emerald">
          <span class="metric-card__label">已克服薄弱点</span>
          <strong class="metric-card__value">{{ detail.stats.total_resolved_weak_spots }}</strong>
          <span class="metric-card__hint">会保留在长期画像里</span>
        </article>
      </section>

      <section class="profile-grid">
        <article class="panel panel--wide">
          <div class="panel__header">
            <div>
              <p class="panel__eyebrow">Recent Concepts</p>
              <h2 class="panel__title">最近关注点</h2>
            </div>
            <span class="panel__caption">当前只展示稳定的结构化摘要，不再展开教材分块片段</span>
          </div>

          <div v-if="detail.recent_concepts.length" class="concept-list">
            <div
              v-for="concept in detail.recent_concepts"
              :key="concept.concept_id"
              class="concept-item"
            >
              <div class="concept-item__main">
                <div class="concept-item__name-row">
                  <span class="concept-item__name">{{ concept.display_name }}</span>
                  <el-tag size="small" effect="light" type="primary" round>x{{ concept.mention_count }}</el-tag>
                </div>
                <div class="concept-item__meta">
                  <span>{{ concept.chapter || '未分类章节' }}</span>
                  <span v-if="concept.last_question_type">{{ concept.last_question_type }}</span>
                </div>
              </div>
              <div class="concept-item__time">{{ formatTime(concept.last_mentioned_at) }}</div>
            </div>
          </div>
          <el-empty v-else description="还没有形成稳定的近期关注点" />
        </article>

        <article class="panel">
          <div class="panel__header">
            <div>
              <p class="panel__eyebrow">Observed Signals</p>
              <h2 class="panel__title">待观察薄弱点</h2>
            </div>
          </div>

          <div v-if="detail.pending_weak_spots.length" class="weakspot-list">
            <div
              v-for="spot in detail.pending_weak_spots"
              :key="spot.concept_id"
              class="weakspot-item weakspot-item--pending"
            >
              <div class="weakspot-item__title">
                <span>{{ spot.display_name }}</span>
                <el-tag size="small" type="info" effect="light" round>观察中</el-tag>
              </div>
              <div class="weakspot-item__meta">
                <span>已出现澄清 {{ spot.clarification_count }} 次</span>
                <span>{{ formatTime(spot.last_triggered_at) }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无待观察薄弱点" />
        </article>

        <article class="panel">
          <div class="panel__header">
            <div>
              <p class="panel__eyebrow">Active Weak Spots</p>
              <h2 class="panel__title">当前薄弱点</h2>
            </div>
          </div>

          <div v-if="detail.weak_spots.length" class="weakspot-list">
            <div
              v-for="spot in detail.weak_spots"
              :key="spot.concept_id"
              class="weakspot-item weakspot-item--active"
            >
              <div class="weakspot-item__title">
                <div class="weakspot-item__title-main">
                  <span>{{ spot.display_name }}</span>
                  <strong>{{ Math.round(spot.confidence * 100) }}%</strong>
                </div>
                <el-button
                  size="small"
                  text
                  type="primary"
                  :loading="resolvingConceptId === spot.concept_id"
                  @click="handleResolveWeakSpot(spot)"
                >
                  手动移除
                </el-button>
              </div>
              <div class="weakspot-item__meta">
                <span>澄清次数 {{ spot.clarification_count }}</span>
                <span>{{ formatTime(spot.last_triggered_at) }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无活跃薄弱点" />
        </article>

        <article class="panel">
          <div class="panel__header">
            <div>
              <p class="panel__eyebrow">Resolved History</p>
              <h2 class="panel__title">已克服薄弱点</h2>
            </div>
          </div>

          <div v-if="detail.resolved_weak_spots.length" class="weakspot-list">
            <div
              v-for="spot in detail.resolved_weak_spots"
              :key="`${spot.concept_id}-${spot.resolved_at || spot.last_triggered_at}`"
              class="weakspot-item weakspot-item--resolved"
            >
              <div class="weakspot-item__title">
                <span>{{ spot.display_name }}</span>
                <el-tag size="small" type="success" effect="light" round>已克服</el-tag>
              </div>
              <div class="weakspot-item__meta">
                <span>曾澄清 {{ spot.clarification_count }} 次</span>
                <span>{{ formatTime(spot.resolved_at) }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="还没有记录到已克服的薄弱点" />
        </article>

        <article class="panel">
          <div class="panel__header">
            <div>
              <p class="panel__eyebrow">Study Trace</p>
              <h2 class="panel__title">学习轨迹</h2>
            </div>
          </div>

          <div class="chapter-bars">
            <div
              v-for="item in chapterStats"
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

          <div class="activity-strip">
            <div
              v-for="item in activityItems"
              :key="item.day"
              class="activity-strip__item"
            >
              <span class="activity-strip__day">{{ item.day }}</span>
              <strong class="activity-strip__count">{{ item.count }}</strong>
            </div>
          </div>
        </article>
      </section>
    </template>
  </div>
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
  padding: 28px;
  background:
    radial-gradient(circle at top left, rgba(99, 102, 241, 0.12), transparent 28%),
    radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.10), transparent 24%),
    linear-gradient(180deg, #fafaf9 0%, #f5f5f4 100%);
  color: #1c1917;
}

.profile-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 24px;
}

.profile-hero__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.profile-hero__eyebrow,
.panel__eyebrow {
  margin: 0 0 6px;
  color: #6366f1;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.profile-hero__title,
.panel__title {
  margin: 0;
  font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
}

.profile-hero__title {
  font-size: clamp(30px, 4vw, 42px);
}

.profile-hero__subtitle {
  max-width: 720px;
  margin: 12px 0 0;
  color: #57534e;
  line-height: 1.7;
}

.profile-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.metric-card,
.panel {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(231, 229, 228, 0.92);
  border-radius: 24px;
  box-shadow: 0 14px 40px rgba(28, 25, 23, 0.06);
  backdrop-filter: blur(8px);
}

.metric-card {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-card--indigo {
  background: linear-gradient(180deg, rgba(238, 242, 255, 0.92), rgba(255, 255, 255, 0.92));
}

.metric-card--amber {
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.92), rgba(255, 255, 255, 0.92));
}

.metric-card--sky {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.94), rgba(255, 255, 255, 0.92));
}

.metric-card--emerald {
  background: linear-gradient(180deg, rgba(236, 253, 245, 0.92), rgba(255, 255, 255, 0.92));
}

.metric-card__label {
  font-size: 12px;
  color: #78716c;
}

.metric-card__value {
  font-size: 30px;
  line-height: 1.1;
}

.metric-card__hint {
  font-size: 12px;
  color: #a8a29e;
}

.profile-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 16px;
}

.panel {
  padding: 18px;
}

.panel--wide {
  grid-column: 1 / 2;
  grid-row: span 2;
}

.panel__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.panel__caption {
  color: #a8a29e;
  font-size: 12px;
  max-width: 260px;
  text-align: right;
}

.concept-list,
.weakspot-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.concept-item,
.weakspot-item {
  width: 100%;
  text-align: left;
  border-radius: 20px;
}

.concept-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid rgba(224, 231, 255, 0.95);
  background: linear-gradient(180deg, rgba(248, 250, 255, 0.96), rgba(255, 255, 255, 0.96));
}

.concept-item__name-row,
.weakspot-item__title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.weakspot-item__title {
  justify-content: space-between;
}

.weakspot-item__title-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.concept-item__name {
  font-size: 18px;
  font-weight: 700;
}

.concept-item__meta,
.weakspot-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 6px;
  color: #78716c;
  font-size: 12px;
}

.concept-item__time {
  white-space: nowrap;
  color: #57534e;
  font-size: 12px;
  align-self: center;
}

.weakspot-item {
  padding: 14px 16px;
}

.weakspot-item--active {
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.98), rgba(255, 255, 255, 0.98));
  border: 1px solid rgba(251, 191, 36, 0.28);
}

.weakspot-item--pending {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.98), rgba(255, 255, 255, 0.98));
  border: 1px solid rgba(59, 130, 246, 0.18);
}

.weakspot-item--resolved {
  background: linear-gradient(180deg, rgba(236, 253, 245, 0.98), rgba(255, 255, 255, 0.98));
  border: 1px solid rgba(16, 185, 129, 0.22);
}

.chapter-bars {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 18px;
}

.chapter-bar__meta {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #44403c;
  margin-bottom: 6px;
}

.chapter-bar__track {
  height: 10px;
  border-radius: 999px;
  background: rgba(231, 229, 228, 0.9);
  overflow: hidden;
}

.chapter-bar__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #6366f1 0%, #22c55e 100%);
}

.activity-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
  gap: 10px;
}

.activity-strip__item {
  padding: 12px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.9);
}

.activity-strip__day {
  display: block;
  font-size: 12px;
  color: #78716c;
  margin-bottom: 4px;
}

.activity-strip__count {
  font-size: 18px;
}

@media (max-width: 1080px) {
  .profile-grid {
    grid-template-columns: 1fr 1fr;
  }

  .panel--wide {
    grid-column: auto;
    grid-row: auto;
  }
}

@media (max-width: 720px) {
  .profile-page {
    padding: 18px;
  }

  .profile-hero {
    flex-direction: column;
  }

  .profile-hero__actions {
    width: 100%;
  }

  .profile-metrics,
  .profile-grid {
    grid-template-columns: 1fr;
  }

  .concept-item {
    flex-direction: column;
  }

  .panel__header {
    flex-direction: column;
  }

  .panel__caption {
    text-align: left;
    max-width: none;
  }
}
</style>
