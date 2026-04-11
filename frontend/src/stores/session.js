import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { DEFAULT_STUDENT_ID } from '../config'
import { sessionsApi } from '../api/sessions'

const DEFAULT_SESSION_TITLE = '新会话'
const SESSION_FETCH_RETRIES = 2
const SESSION_FETCH_RETRY_DELAY_MS = 450

function sleep(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

export const useSessionStore = defineStore('session', () => {
  const sessions = ref([])
  const currentSessionId = ref(null)
  const loading = ref(false)
  const loaded = ref(false)
  const unreadCounts = ref({})
  let fetchPromise = null

  const currentSession = computed(() =>
    sessions.value.find(session => session.id === currentSessionId.value)
  )

  const sortedSessions = computed(() =>
    [...sessions.value].sort((left, right) =>
      new Date(right.updated_at) - new Date(left.updated_at)
    )
  )

  async function runFetchSessions(studentId) {
    let lastError = null

    for (let attempt = 0; attempt <= SESSION_FETCH_RETRIES; attempt += 1) {
      try {
        const response = await sessionsApi.list(studentId)
        const nextSessions = Array.isArray(response.sessions) ? response.sessions : []
        sessions.value = nextSessions
        loaded.value = true
        return nextSessions
      } catch (error) {
        lastError = error
        if (attempt === SESSION_FETCH_RETRIES) {
          break
        }
        await sleep(SESSION_FETCH_RETRY_DELAY_MS * (attempt + 1))
      }
    }

    throw lastError
  }

  async function fetchSessions(studentId = DEFAULT_STUDENT_ID) {
    if (fetchPromise) {
      return fetchPromise
    }

    loading.value = true
    fetchPromise = runFetchSessions(studentId)
      .finally(() => {
        loading.value = false
        fetchPromise = null
      })

    return fetchPromise
  }

  async function createSession(title = DEFAULT_SESSION_TITLE, studentId = DEFAULT_STUDENT_ID) {
    const response = await sessionsApi.create({
      title,
      student_id: studentId
    })
    sessions.value.unshift(response)
    currentSessionId.value = response.id
    return response
  }

  async function updateSession(sessionId, data) {
    const response = await sessionsApi.update(sessionId, data)
    sessions.value = sessions.value.map(session =>
      session.id === sessionId ? { ...session, ...response } : session
    )
    return response
  }

  function syncSession(sessionId, data) {
    sessions.value = sessions.value.map(session =>
      session.id === sessionId ? { ...session, ...data } : session
    )
  }

  function shouldAutoTitle(sessionId) {
    const session = sessions.value.find(item => item.id === sessionId)
    if (!session) {
      return false
    }
    return session.title === DEFAULT_SESSION_TITLE && (session.message_count || 0) === 0
  }

  async function deleteSession(sessionId, studentId = DEFAULT_STUDENT_ID) {
    await sessionsApi.delete(sessionId, studentId)
    sessions.value = sessions.value.filter(session => session.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
    }
    delete unreadCounts.value[sessionId]
  }

  function setCurrentSession(sessionId) {
    currentSessionId.value = sessionId
  }

  function markRead(sessionId) {
    if (unreadCounts.value[sessionId]) {
      delete unreadCounts.value[sessionId]
    }
  }

  function incrementUnread(sessionId) {
    unreadCounts.value[sessionId] = (unreadCounts.value[sessionId] || 0) + 1
  }

  return {
    sessions,
    currentSessionId,
    loading,
    unreadCounts,
    loaded,
    currentSession,
    sortedSessions,
    fetchSessions,
    createSession,
    updateSession,
    syncSession,
    shouldAutoTitle,
    deleteSession,
    setCurrentSession,
    markRead,
    incrementUnread
  }
})
