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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, Check, Warning } from '@element-plus/icons-vue'

import AssessmentQuestion from '../components/AssessmentQuestion.vue'
import { useAssessmentStore } from '../stores/assessment'
import { useAuthStore } from '../stores/auth'
import { workspaceConfirmOptions } from '../utils/feedback'
import { accountStorageKey, readLocalStorage, removeLocalStorage, writeLocalStorage } from '../utils/storage'

const route = useRoute()
const router = useRouter()
const store = useAssessmentStore()
const authStore = useAuthStore()
const assessment = computed(() => store.current)
const currentIndex = ref(0)
const answers = ref({})
const timings = ref({})
const changeCounts = ref({})
const questionStartedAt = ref(performance.now())
const error = ref('')
const submitted = ref(false)
const activeDraftKey = ref('')
let loadVersion = 0
const currentQuestion = computed(() => assessment.value.questions[currentIndex.value])
const answeredCount = computed(() => Object.values(answers.value).filter(Boolean).length)
const draftKey = computed(() => accountStorageKey(
  `ds-course-agent.assessment-draft.${route.params.assessmentId}`,
  authStore.user
))

function clearLocalAnswerState() {
  answers.value = {}
  timings.value = {}
  changeCounts.value = {}
  currentIndex.value = 0
  submitted.value = false
}

function saveDraft() {
  if (typeof window === 'undefined' || !assessment.value || activeDraftKey.value !== draftKey.value) return
  try {
    writeLocalStorage(activeDraftKey.value, JSON.stringify({
      questionIds: assessment.value.questions.map(question => question.id),
      currentIndex: currentIndex.value,
      answers: answers.value,
      timings: timings.value,
      changeCounts: changeCounts.value
    }))
  } catch {
    // Draft persistence is optional; answering remains usable if storage is unavailable.
  }
}

function restoreDraft(key) {
  if (typeof window === 'undefined' || !assessment.value || key !== draftKey.value) return
  try {
    const draft = JSON.parse(readLocalStorage(key) || 'null')
    const questionIds = assessment.value.questions.map(question => question.id)
    if (!draft || JSON.stringify(draft.questionIds) !== JSON.stringify(questionIds)) return
    answers.value = draft.answers || {}
    timings.value = draft.timings || {}
    changeCounts.value = draft.changeCounts || {}
    currentIndex.value = Math.min(Math.max(Number(draft.currentIndex) || 0, 0), questionIds.length - 1)
  } catch {
    removeLocalStorage(key)
  }
}

function clearDraft() {
  if (activeDraftKey.value) removeLocalStorage(activeDraftKey.value)
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
    await ElMessageBox.confirm(
      '提交后不能修改答案，确认提交本次测验？',
      '提交测验',
      {
        type: 'warning',
        ...workspaceConfirmOptions,
        confirmButtonText: '确认提交',
        cancelButtonText: '继续检查'
      }
    )
  } catch {
    return
  }

  const payload = assessment.value.questions.map(question => ({
    question_id: question.id,
    selected_option_id: answers.value[question.id],
    response_time_ms: Math.min(86_400_000, Math.round(timings.value[question.id] || 0)),
    answer_change_count: changeCounts.value[question.id] || 0
  }))
  try {
    const result = await store.submitAssessment(route.params.assessmentId, payload)
    if (!result || activeDraftKey.value !== draftKey.value) return
    submitted.value = true
    clearDraft()
    router.replace(`/assessments/${route.params.assessmentId}/result`)
  } catch (requestError) {
    ElMessage.error(requestError.response?.data?.detail || '提交失败，请重试')
  }
}

async function loadAssessment() {
  const version = ++loadVersion
  const requestedDraftKey = draftKey.value
  error.value = ''
  activeDraftKey.value = ''
  clearLocalAnswerState()
  try {
    store.current = null
    await store.openAssessment(route.params.assessmentId)
    if (version !== loadVersion || requestedDraftKey !== draftKey.value || !assessment.value) return
    activeDraftKey.value = requestedDraftKey
    restoreDraft(requestedDraftKey)
    questionStartedAt.value = performance.now()
  } catch (requestError) {
    if (version !== loadVersion || requestedDraftKey !== draftKey.value) return
    if (requestError.response?.status === 409) {
      router.replace(`/assessments/${route.params.assessmentId}/result`)
      return
    }
    error.value = requestError.response?.data?.detail || '请返回列表后重试。'
  }
}

onMounted(loadAssessment)
watch(() => route.params.assessmentId, loadAssessment)
watch(draftKey, (nextKey, previousKey) => {
  if (!previousKey || nextKey === previousKey) return
  loadVersion += 1
  activeDraftKey.value = ''
  clearLocalAnswerState()
})

onBeforeUnmount(() => {
  if (submitted.value) return
  recordElapsed()
  saveDraft()
})
</script>

<style src="../styles/assessment.css"></style>
