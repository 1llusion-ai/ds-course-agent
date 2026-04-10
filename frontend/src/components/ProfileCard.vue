<template>
  <div class="bg-white rounded-2xl p-4 border border-stone-100" style="box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.04);">
    <div class="flex items-center justify-between mb-4">
      <h3 class="font-bold text-stone-800 flex items-center gap-2">
        <span class="w-7 h-7 rounded-lg bg-indigo-100 flex items-center justify-center text-indigo-600">📊</span>
        学习快照
      </h3>
      <el-button link type="primary" size="small" @click="$router.push('/profile')">查看完整 →</el-button>
    </div>

    <el-skeleton v-if="profileStore.loading" :rows="3" />

    <template v-else-if="profileStore.summary">
      <div class="mb-4">
        <div class="text-xs text-stone-500 mb-2">🔥 最近关注</div>
        <div class="flex flex-wrap gap-2">
          <el-tag v-for="c in profileStore.summary.recent_concepts?.slice(0, 5)" :key="c.concept_id" type="primary" effect="light" round size="small">
            {{ c.display_name }}
          </el-tag>
          <span v-if="!profileStore.summary.recent_concepts?.length" class="text-xs text-stone-400">暂无数据</span>
        </div>
      </div>

      <div v-if="profileStore.summary.weak_spots?.length">
        <div class="text-xs text-stone-500 mb-2">⚠️ 需要巩固</div>
        <div class="flex flex-wrap gap-2">
          <el-tag v-for="w in profileStore.summary.weak_spots.slice(0, 3)" :key="w.concept_id" type="warning" effect="light" round size="small">
            {{ w.display_name }} {{ Math.round(w.confidence * 100) }}%
          </el-tag>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useProfileStore } from '../stores/profile'

const profileStore = useProfileStore()
onMounted(() => profileStore.fetchSummary())
</script>
