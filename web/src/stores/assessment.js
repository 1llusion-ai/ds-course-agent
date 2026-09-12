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
  let stateVersion = 0

  function isCurrentState(version) {
    return version === stateVersion
  }

  async function fetchOverview(statuses, silent = false) {
    const requestVersion = ++overviewVersion
    const requestStateVersion = stateVersion
    if (!silent) loading.value = true
    try {
      const [items, jobs] = await Promise.all([
        assessmentsApi.list(statuses), assessmentsApi.preparations()
      ])
      if (isCurrentState(requestStateVersion) && requestVersion === overviewVersion) {
        assessments.value = items
        preparations.value = jobs
        return { assessments: items, preparations: jobs }
      }
      return null
    } finally {
      if (isCurrentState(requestStateVersion) && requestVersion === overviewVersion) {
        loading.value = false
      }
    }
  }

  async function fetchAssessments(statuses) {
    const requestVersion = ++overviewVersion
    const requestStateVersion = stateVersion
    loading.value = true
    try {
      const value = await assessmentsApi.list(statuses)
      if (isCurrentState(requestStateVersion) && requestVersion === overviewVersion) {
        assessments.value = value
        return value
      }
      return null
    } finally {
      if (isCurrentState(requestStateVersion) && requestVersion === overviewVersion) {
        loading.value = false
      }
    }
  }

  async function openAssessment(assessmentId) {
    const requestVersion = ++assessmentVersion
    const requestStateVersion = stateVersion
    loading.value = true
    try {
      const value = await assessmentsApi.open(assessmentId)
      if (isCurrentState(requestStateVersion) && requestVersion === assessmentVersion) {
        current.value = value
        return value
      }
      return null
    } finally {
      if (isCurrentState(requestStateVersion) && requestVersion === assessmentVersion) {
        loading.value = false
      }
    }
  }

  async function submitAssessment(assessmentId, answers) {
    if (submitPromise) return submitPromise

    const requestStateVersion = stateVersion
    submitting.value = true
    let request
    request = assessmentsApi.submit(assessmentId, answers)
      .then(value => {
        if (isCurrentState(requestStateVersion)) {
          result.value = value
          return value
        }
        return null
      })
      .finally(() => {
        if (isCurrentState(requestStateVersion) && submitPromise === request) {
          submitting.value = false
          submitPromise = null
        }
      })
    submitPromise = request
    return request
  }

  async function fetchResult(assessmentId) {
    const requestVersion = ++resultVersion
    const requestStateVersion = stateVersion
    loading.value = true
    try {
      const value = await assessmentsApi.result(assessmentId)
      if (isCurrentState(requestStateVersion) && requestVersion === resultVersion) {
        result.value = value
        return value
      }
      return null
    } finally {
      if (isCurrentState(requestStateVersion) && requestVersion === resultVersion) {
        loading.value = false
      }
    }
  }

  function resetForUser() {
    stateVersion += 1
    overviewVersion += 1
    assessmentVersion += 1
    resultVersion += 1
    assessments.value = []
    preparations.value = []
    current.value = null
    result.value = null
    loading.value = false
    submitting.value = false
    submitPromise = null
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
    fetchResult,
    resetForUser
  }
})
