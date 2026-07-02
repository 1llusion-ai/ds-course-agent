import { defineStore } from 'pinia'
import { ref } from 'vue'
import { profileApi } from '../api/profile'
import { DEFAULT_STUDENT_ID } from '../config'

export const useProfileStore = defineStore('profile', () => {
  const summary = ref(null)
  const detail = ref(null)
  const conceptDetail = ref(null)
  const loading = ref(false)
  const conceptLoading = ref(false)

  async function fetchSummary(studentId = DEFAULT_STUDENT_ID) {
    loading.value = true
    try {
      summary.value = await profileApi.getSummary(studentId)
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(studentId = DEFAULT_STUDENT_ID) {
    loading.value = true
    try {
      detail.value = await profileApi.getDetail(studentId)
    } finally {
      loading.value = false
    }
  }

  async function fetchConceptDetail(conceptId) {
    if (!conceptId) return null
    conceptLoading.value = true
    try {
      conceptDetail.value = await profileApi.getConcept(conceptId)
      return conceptDetail.value
    } finally {
      conceptLoading.value = false
    }
  }

  function clearConceptDetail() {
    conceptDetail.value = null
  }

  async function resolveWeakSpot(studentId = DEFAULT_STUDENT_ID, conceptId) {
    if (!conceptId) return null
    return profileApi.resolveWeakSpot(studentId, conceptId)
  }

  return {
    summary,
    detail,
    conceptDetail,
    loading,
    conceptLoading,
    fetchSummary,
    fetchDetail,
    fetchConceptDetail,
    clearConceptDetail,
    resolveWeakSpot
  }
})
