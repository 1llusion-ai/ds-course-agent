import { defineStore } from 'pinia'
import { ref } from 'vue'

import { assessmentsApi } from '../api/assessments'

export const useAssessmentStore = defineStore('assessment', () => {
  const assessments = ref([])
  const current = ref(null)
  const result = ref(null)
  const loading = ref(false)
  const submitting = ref(false)
  const preparations = ref([])
  let overviewVersion = 0
  let submitPromise = null
  let assessmentVersion = 0
  let resultVersion = 0

  async function fetchOverview(statuses, silent = false) {
    const version = ++overviewVersion
    if (!silent) loading.value = true
    try {
      const [items, jobs] = await Promise.all([
        assessmentsApi.list(statuses), assessmentsApi.preparations()
      ])
      if (version === overviewVersion) {
        assessments.value = items
        preparations.value = jobs
      }
    } finally {
      if (version === overviewVersion) loading.value = false
    }
  }

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
    const version = ++assessmentVersion
    loading.value = true
    try {
      const value = await assessmentsApi.open(assessmentId)
      if (version === assessmentVersion) current.value = value
      return current.value
    } finally {
      loading.value = false
    }
  }

  async function submitAssessment(assessmentId, answers) {
    if (submitPromise) return submitPromise
    submitting.value = true
    submitPromise = assessmentsApi.submit(assessmentId, answers)
      .then(value => { result.value = value; return value })
      .finally(() => { submitting.value = false; submitPromise = null })
    return submitPromise
  }

  async function fetchResult(assessmentId) {
    const version = ++resultVersion
    loading.value = true
    try {
      const value = await assessmentsApi.result(assessmentId)
      if (version === resultVersion) result.value = value
      return result.value
    } finally {
      loading.value = false
    }
  }

  return {
    assessments,
    preparations,
    current,
    result,
    loading,
    submitting,
    fetchAssessments,
    fetchOverview,
    openAssessment,
    submitAssessment,
    fetchResult
  }
})
