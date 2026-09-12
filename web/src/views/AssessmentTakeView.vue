<template>
  <main class="assessment-page assessment-take-page">
    <header class="assessment-header assessment-header--take">
      <button type="button" class="assessment-icon-button" aria-label="返回测验列表" title="返回测验列表" @click="router.push('/assessments')">
        <el-icon><ArrowLeft /></el-icon>
      </button>
      <div class="assessment-take-title"><small>正在作答</small><h1>{{ assessment?.title || '测验' }}</h1></div>
      <span v-if="assessment" class="assessment-progress-text">{{ answeredCount }} / {{ assessment.questions.length }} 已答</span>
    </header>

    <div v-if="store.loading && !assessment" class="assessment-loading"><el-skeleton :rows="8" animated /></div>
    <div v-else-if="error" class="assessment-empty"><el-icon><Warning /></el-icon><h2>无法打开测验</h2><p>{{ error }}</p><el-button @click="router.push('/assessments')">返回列表</el-button></div>
    <div v-else-if="assessment" class="assessment-workspace">
      <aside class="assessment-index" aria-label="题目导航">
        <p>题目</p>
        <div class="assessment-index__grid">
          <button v-for="(question, index) in assessment.questions" :key="question.id" type="button" :class="{ active: index === currentIndex, answered: answers[question.id] }" @click="goTo(index)">{{ index + 1 }}</button>
        </div>
        <div class="assessment-index__legend"><span><i></i>未作答</span><span><i class="answered"></i>已作答</span></div>
      </aside>

      <section class="assessment-stage">
        <AssessmentQuestion
          :question="currentQuestion"
          :number="currentIndex + 1"
          :model-value="answers[currentQuestion.id] || ''"
          @update:model-value="selectAnswer"
        />
        <footer class="assessment-stage__footer">
          <el-button :disabled="currentIndex === 0" @click="goTo(currentIndex - 1)"><el-icon><ArrowLeft /></el-icon>上一题</el-button>
          <el-button v-if="currentIndex < assessment.questions.length - 1" type="primary" @click="goTo(currentIndex + 1)">下一题<el-icon><ArrowRight /></el-icon></el-button>
          <el-button v-else type="primary" :loading="store.submitting" @click="confirmSubmit"><el-icon><Check /></el-icon>提交测验</el-button>
        </footer>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import AssessmentQuestion from '../components/AssessmentQuestion.vue'
import { useAssessmentStore } from '../stores/assessment'

const route = useRoute()
const router = useRouter()
const store = useAssessmentStore()
const assessment = computed(() => store.current)
const currentIndex = ref(0)
const answers = ref({})
const timings = ref({})
const changeCounts = ref({})
const questionStartedAt = ref(performance.now())
const error = ref('')
const currentQuestion = computed(() => assessment.value.questions[currentIndex.value])
const answeredCount = computed(() => Object.values(answers.value).filter(Boolean).length)
const draftKey = computed(() => `ds-course-agent.assessment-draft.${route.params.assessmentId}`)

function saveDraft() {
  if (typeof window === 'undefined' || !assessment.value) return
  try {
    window.localStorage.setItem(draftKey.value, JSON.stringify({
      questionIds: assessment.value.questions.map(question => question.id),
      currentIndex: currentIndex.value,
      answers: answers.value,
      timings: timings.value,
      changeCounts: changeCounts.value
    }))
  } catch {
    // Draft persistence is best-effort; answering must remain usable if storage is unavailable.
  }
}

function restoreDraft() {
  if (typeof window === 'undefined' || !assessment.value) return
  try {
    const draft = JSON.parse(window.localStorage.getItem(draftKey.value) || 'null')
    const questionIds = assessment.value.questions.map(question => question.id)
    if (!draft || JSON.stringify(draft.questionIds) !== JSON.stringify(questionIds)) return
    answers.value = draft.answers || {}
    timings.value = draft.timings || {}
    changeCounts.value = draft.changeCounts || {}
    currentIndex.value = Math.min(Math.max(Number(draft.currentIndex) || 0, 0), questionIds.length - 1)
  } catch {
    window.localStorage.removeItem(draftKey.value)
  }
}

function clearDraft() {
  if (typeof window !== 'undefined') window.localStorage.removeItem(draftKey.value)
}

function recordElapsed() {
  const question = currentQuestion.value
  if (!question) return
  timings.value[question.id] = (timings.value[question.id] || 0) + Math.max(0, performance.now() - questionStartedAt.value)
  questionStartedAt.value = performance.now()
}

function goTo(index) {
  recordElapsed()
  currentIndex.value = index
  saveDraft()
}

function selectAnswer(optionId) {
  const questionId = currentQuestion.value.id
  const previous = answers.value[questionId]
  if (previous && previous !== optionId) changeCounts.value[questionId] = (changeCounts.value[questionId] || 0) + 1
  answers.value[questionId] = optionId
  saveDraft()
}

async function confirmSubmit() {
  recordElapsed()
  const unanswered = assessment.value.questions.length - answeredCount.value
  if (unanswered) {
    ElMessage.warning(`还有 ${unanswered} 题未作答`)
    return
  }
  try {
    await ElMessageBox.confirm('提交后不能修改答案，确认提交本次测验？', '提交测验', { confirmButtonText: '确认提交', cancelButtonText: '继续检查', type: 'warning' })
  } catch { return }

  const payload = assessment.value.questions.map(question => ({
    question_id: question.id,
    selected_option_id: answers.value[question.id],
    response_time_ms: Math.round(timings.value[question.id] || 0),
    answer_change_count: changeCounts.value[question.id] || 0
  }))
  try {
    await store.submitAssessment(route.params.assessmentId, payload)
    clearDraft()
    router.replace(`/assessments/${route.params.assessmentId}/result`)
  } catch (requestError) {
    ElMessage.error(requestError.response?.data?.detail || '提交失败，请重试')
  }
}

onMounted(async () => {
  try {
    await store.openAssessment(route.params.assessmentId)
    restoreDraft()
    questionStartedAt.value = performance.now()
  } catch (requestError) {
    if (requestError.response?.status === 409) {
      router.replace(`/assessments/${route.params.assessmentId}/result`)
      return
    }
    error.value = requestError.response?.data?.detail || '请返回列表后重试。'
  }
})

onBeforeUnmount(() => {
  recordElapsed()
  saveDraft()
})
</script>

<style src="../styles/assessment.css"></style>
