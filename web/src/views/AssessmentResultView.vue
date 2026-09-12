<template>
  <main class="assessment-page assessment-result-page">
    <header class="assessment-page-toolbar">
      <div><small>测验结果</small><h1>{{ result?.title || '结果' }}</h1></div>
      <el-button plain @click="router.push('/assessments')"><el-icon><ArrowLeft /></el-icon>返回测验</el-button>
    </header>

    <div v-if="store.loading && !result" class="assessment-loading"><el-skeleton :rows="8" animated /></div>
    <div v-else-if="error" class="assessment-empty"><el-icon><Warning /></el-icon><h2>结果加载失败</h2><p>{{ error }}</p></div>
    <template v-else-if="result">
      <section class="assessment-scoreband">
        <div class="assessment-score"><strong>{{ Math.round(result.score_percent) }}</strong><span>分</span></div>
        <div><h2>{{ result.correct_count }} / {{ result.question_count }} 题正确</h2><p>用时 {{ formatDuration(result.duration_ms) }}</p></div>
        <el-progress type="circle" :percentage="result.score_percent" :width="82" :stroke-width="7" :show-text="false" />
      </section>

      <section class="assessment-review">
        <article v-for="(question, index) in result.questions" :key="question.id" class="assessment-review-item" :class="question.is_correct ? 'is-correct' : 'is-wrong'">
          <header><span>第 {{ index + 1 }} 题</span><strong>{{ question.is_correct ? '回答正确' : '回答错误' }}</strong></header>
          <h2>{{ question.stem }}</h2>
          <div class="assessment-review-options">
            <div v-for="option in question.options" :key="option.id" :class="{ correct: option.id === question.correct_option_id, selected: option.id === question.selected_option_id }">
              <span>{{ option.id }}</span><p>{{ option.text }}</p><small v-if="option.id === question.correct_option_id">正确答案</small><small v-else-if="option.id === question.selected_option_id">你的答案</small>
            </div>
          </div>
          <section class="assessment-explanation"><h3>解析</h3><p>{{ question.explanation }}</p></section>
          <section v-if="question.sources.length" class="assessment-sources"><h3>教材依据</h3><AssessmentSource v-for="source in question.sources" :key="source.id" :source="source" /></section>
        </article>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AssessmentSource from '../components/AssessmentSource.vue'
import { useAssessmentStore } from '../stores/assessment'
import { formatDuration } from '../utils/assessment'

const route = useRoute()
const router = useRouter()
const store = useAssessmentStore()
const result = computed(() => store.result)
const error = ref('')

onMounted(async () => {
  try { await store.fetchResult(route.params.assessmentId) }
  catch (requestError) { error.value = requestError.response?.data?.detail || '请稍后重试。' }
})
</script>

<style src="../styles/assessment.css"></style>
