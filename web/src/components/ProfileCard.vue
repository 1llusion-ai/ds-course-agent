<template>
  <div class="profile-card" :class="{ 'profile-card--compact': compact }">
    <div class="profile-card__header">
      <div>
        <p class="profile-card__eyebrow">Learning Snapshot</p>
        <h3 class="profile-card__title">学习快照</h3>
      </div>
      <el-button link type="primary" size="small" @click="$router.push('/profile')">查看完整 →</el-button>
    </div>

    <el-skeleton v-if="profileStore.loading" :rows="4" animated />

    <template v-else-if="profileStore.summary">
      <div class="profile-card__section">
        <div class="profile-card__section-label">最近聊到</div>
        <div class="profile-card__tag-list">
          <el-tag
            v-for="concept in profileStore.summary.recent_concepts?.slice(0, 4)"
            :key="concept.concept_id"
            type="primary"
            effect="light"
            round
            class="profile-card__tag"
          >
            {{ concept.display_name }}
            <span class="profile-card__tag-count">×{{ concept.mention_count }}</span>
          </el-tag>
          <span v-if="!profileStore.summary.recent_concepts?.length" class="profile-card__empty">还没有可用画像</span>
        </div>
      </div>

      <div class="profile-card__section">
        <div class="profile-card__section-label">待观察薄弱点</div>
        <div class="profile-card__tag-list">
          <el-tag
            v-for="spot in profileStore.summary.pending_weak_spots?.slice(0, compact ? 2 : 3)"
            :key="spot.concept_id"
            type="info"
            effect="light"
            round
            class="profile-card__tag"
          >
            {{ spot.display_name }}
            <span class="profile-card__tag-count">观察中</span>
          </el-tag>
          <span v-if="!profileStore.summary.pending_weak_spots?.length" class="profile-card__empty">暂无待观察项</span>
        </div>
      </div>

      <div class="profile-card__section">
        <div class="profile-card__section-label">当前薄弱点</div>
        <div class="profile-card__tag-list">
          <el-tag
            v-for="spot in profileStore.summary.weak_spots?.slice(0, 3)"
            :key="spot.concept_id"
            type="warning"
            effect="light"
            round
            class="profile-card__tag"
          >
            {{ spot.display_name }}
            <span class="profile-card__tag-count">{{ Math.round(spot.confidence * 100) }}%</span>
          </el-tag>
          <span v-if="!profileStore.summary.weak_spots?.length" class="profile-card__empty">暂无活跃薄弱点</span>
        </div>
      </div>

      <div class="profile-card__footer">
        <div class="profile-card__metric">
          <span class="profile-card__metric-value">{{ profileStore.summary.pending_weak_spots?.length || 0 }}</span>
          <span class="profile-card__metric-label">待观察薄弱点</span>
        </div>
        <div class="profile-card__metric">
          <span class="profile-card__metric-value">{{ profileStore.summary.resolved_weak_spot_count || 0 }}</span>
          <span class="profile-card__metric-label">已克服薄弱点</span>
        </div>
        <div class="profile-card__metric">
          <span class="profile-card__metric-value">{{ profileStore.summary.recent_concepts?.length || 0 }}</span>
          <span class="profile-card__metric-label">近期关注知识点</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useProfileStore } from '../stores/profile'

defineProps({
  compact: {
    type: Boolean,
    default: false
  }
})

const profileStore = useProfileStore()

onMounted(() => profileStore.fetchSummary())
</script>

<style scoped>
.profile-card {
  background:
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.12), transparent 38%),
    linear-gradient(180deg, #ffffff 0%, #fcfcfd 100%);
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 24px;
  padding: 18px;
  box-shadow: 0 10px 30px rgba(28, 25, 23, 0.06);
}

.profile-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.profile-card__eyebrow {
  margin: 0 0 4px;
  color: #6366f1;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: 700;
}

.profile-card__title {
  margin: 0;
  font-size: 20px;
  color: #1c1917;
  font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
}

.profile-card__section {
  margin-bottom: 16px;
}

.profile-card__section-label {
  font-size: 12px;
  font-weight: 700;
  color: #57534e;
  margin-bottom: 8px;
}

.profile-card__tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.profile-card__tag {
  max-width: 100%;
}

.profile-card__tag-count {
  margin-left: 4px;
  opacity: 0.72;
}

.profile-card__empty {
  font-size: 12px;
  color: #a8a29e;
}

.profile-card__footer {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.profile-card__metric {
  padding: 12px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.9);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.profile-card__metric-value {
  font-size: 20px;
  font-weight: 700;
  color: #292524;
}

.profile-card__metric-label {
  font-size: 12px;
  color: #78716c;
}

.profile-card--compact {
  padding: 16px;
  border-radius: 22px;
  box-shadow: 0 14px 30px rgba(79, 70, 229, 0.08);
}

.profile-card--compact .profile-card__header {
  margin-bottom: 14px;
}

.profile-card--compact .profile-card__title {
  font-size: 18px;
}

.profile-card--compact .profile-card__section {
  margin-bottom: 14px;
}

.profile-card--compact .profile-card__section-label,
.profile-card--compact .profile-card__metric-label,
.profile-card--compact .profile-card__empty {
  font-size: 11px;
}

.profile-card--compact .profile-card__footer {
  gap: 8px;
}

.profile-card--compact .profile-card__metric {
  padding: 10px;
  border-radius: 14px;
}

.profile-card--compact .profile-card__metric-value {
  font-size: 18px;
}
</style>
