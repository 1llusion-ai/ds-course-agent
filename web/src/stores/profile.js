import { defineStore } from 'pinia'
import { ref } from 'vue'
import { profileApi } from '../api/profile'

export const useProfileStore = defineStore('profile', () => {
  const summary = ref(null)
  const detail = ref(null)
  const conceptDetail = ref(null)
  const loading = ref(false)
  const conceptLoading = ref(false)
  let summaryVersion = 0
  let detailVersion = 0
  let conceptVersion = 0

  async function fetchSummary() {
    const version = ++summaryVersion
    loading.value = true
    try {
      const value = await profileApi.getSummary()
      if (version === summaryVersion) summary.value = value
    } finally {
      if (version === summaryVersion) loading.value = false
    }
  }

  async function fetchDetail() {
    const version = ++detailVersion
    loading.value = true
    try {
      const value = await profileApi.getDetail()
      if (version === detailVersion) detail.value = value
    } finally {
      if (version === detailVersion) loading.value = false
    }
  }

  async function fetchConceptDetail(conceptId) {
    if (!conceptId) return null
    const version = ++conceptVersion
    conceptLoading.value = true
    try {
      const value = await profileApi.getConcept(conceptId)
      if (version === conceptVersion) conceptDetail.value = value
      return conceptDetail.value
    } finally {
      if (version === conceptVersion) conceptLoading.value = false
    }
  }

  function clearConceptDetail() {
    conceptDetail.value = null
  }

  async function resolveWeakSpot(conceptId) {
    if (!conceptId) return null
    return profileApi.resolveWeakSpot(conceptId)
  }

  function resetForUser() {
    summaryVersion += 1
    detailVersion += 1
    conceptVersion += 1
    summary.value = null
    detail.value = null
    conceptDetail.value = null
    loading.value = false
    conceptLoading.value = false
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
    resolveWeakSpot,
    resetForUser
  }
})
