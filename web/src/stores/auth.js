import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '../api/auth'

function normalizeUser(payload) {
  return payload?.user || payload?.student || payload || null
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const loading = ref(false)
  const initialized = ref(false)

  const isAuthenticated = computed(() => Boolean(user.value))

  function setUser(nextUser) {
    user.value = normalizeUser(nextUser)
    initialized.value = true
  }

  function clearUser() {
    user.value = null
    initialized.value = true
  }

  async function fetchMe() {
    loading.value = true
    try {
      const response = await authApi.me()
      setUser(response)
      return user.value
    } catch (error) {
      clearUser()
      throw error
    } finally {
      loading.value = false
    }
  }

  async function login(credentials) {
    loading.value = true
    try {
      const response = await authApi.login(credentials)
      const nextUser = normalizeUser(response)
      if (nextUser) {
        setUser(nextUser)
      } else {
        await fetchMe()
      }
      return user.value
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    loading.value = true
    try {
      await authApi.logout()
    } finally {
      clearUser()
      loading.value = false
    }
  }

  return {
    user,
    loading,
    initialized,
    isAuthenticated,
    setUser,
    clearUser,
    fetchMe,
    login,
    logout
  }
})
