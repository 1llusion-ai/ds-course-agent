<template>
  <main class="assessment-page assessment-list-page">
    <section class="assessment-list-toolbar">
      <div>
        <small>我的测验</small>
        <h1>{{ activeTab === 'active' ? '待完成测验' : '完成记录' }}</h1>
        <p>{{ activeTab === 'active' ? 'Agent 分配的新测验会出现在这里。' : '查看已经提交的测验结果。' }}</p>
      </div>
      <el-segmented v-model="activeTab" :options="tabs" />
    </section>

    <section class="assessment-list-content" aria-live="polite">
      <el-skeleton v-if="store.loading" :rows="6" animated />
      <div v-else-if="error" class="assessment-empty">
        <el-icon><Warning /></el-icon><h2>测验加载失败</h2><p>{{ error }}</p>
        <el-button plain @click="load">重新加载</el-button>
      </div>
      <div v-else-if="!store.assessments.length" class="assessment-empty">
        <el-icon><DocumentChecked /></el-icon>
        <h2>{{ activeTab === 'active' ? '暂时没有待完成测验' : '还没有完成记录' }}</h2>
        <p v-if="activeTab === 'active'">在对话中告诉 Agent“开始做题”，它会根据你的学习状态安排测验。</p>
      </div>
      <div v-else class="assessment-list">
        <article v-for="item in store.assessments" :key="item.id" class="assessment-list-item">
          <div class="assessment-list-item__status" :data-status="item.status">
            {{ assessmentStatusText[item.status] }}
          </div>
          <div class="assessment-list-item__body">
            <h3>{{ item.title }}</h3>
            <p>{{ item.question_count }} 题 · {{ formatAssessmentTime(item.assigned_at) }}</p>
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
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useAssessmentStore } from '../stores/assessment'
import { assessmentStatusText, formatAssessmentTime } from '../utils/assessment'

const router = useRouter()
const store = useAssessmentStore()
const activeTab = ref('active')
const error = ref('')
const tabs = [{ label: '待完成', value: 'active' }, { label: '已完成', value: 'completed' }]

async function load() {
  error.value = ''
  try {
    await store.fetchAssessments(activeTab.value === 'active' ? ['ready', 'in_progress'] : ['submitted'])
  } catch (requestError) {
    error.value = requestError.response?.data?.detail || '请稍后重试。'
  }
}

function open(item) {
  router.push(item.status === 'submitted' ? `/assessments/${item.id}/result` : `/assessments/${item.id}`)
}

watch(activeTab, load)
onMounted(load)
</script>

<style src="../styles/assessment.css"></style>
