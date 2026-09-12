import { defineStore } from 'pinia'
import { ref } from 'vue'

import { assessmentsApi } from '../api/assessments'

export const useAssessmentStore = defineStore('assessment', () => {
  const assessments = ref([])
  const current = ref(null)
  const result = ref(null)
  const loading = ref(false)
  const submitting = ref(false)

  async function fetchAssessments(statuses) {
    loading.value = true
    try {
      assessments.value = await assessmentsApi.list(statuses)
      return assessments.value
    } finally {
      loading.value = false
    }
  }

  async function openAssessment(assessmentId) {
    loading.value = true
    try {
      current.value = await assessmentsApi.open(assessmentId)
      return current.value
    } finally {
      loading.value = false
    }
  }

  async function submitAssessment(assessmentId, answers) {
    if (submitting.value) return result.value
    submitting.value = true
    try {
      result.value = await assessmentsApi.submit(assessmentId, answers)
      return result.value
    } finally {
      submitting.value = false
    }
  }

  async function fetchResult(assessmentId) {
    loading.value = true
    try {
      result.value = await assessmentsApi.result(assessmentId)
      return result.value
    } finally {
      loading.value = false
    }
  }

  return {
    assessments,
    current,
    result,
    loading,
    submitting,
    fetchAssessments,
    openAssessment,
    submitAssessment,
    fetchResult
  }
})
