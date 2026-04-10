import { defineStore } from 'pinia'
import { ref } from 'vue'
import { profileApi } from '../api/profile'
import { DEFAULT_STUDENT_ID } from '../config'

export const useProfileStore = defineStore('profile', () => {
  const summary = ref(null)
  const detail = ref(null)
  const loading = ref(false)

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

  return { summary, detail, loading, fetchSummary, fetchDetail }
})
