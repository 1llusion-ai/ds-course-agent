import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { sessionsApi } from '../api/sessions'

const DEFAULT_SESSION_TITLE = '新会话'
const SESSION_FETCH_RETRIES = 2
const SESSION_FETCH_RETRY_DELAY_MS = 450
const PINNED_SESSIONS_STORAGE_KEY = 'ds-course-agent.pinnedSessions'

function sleep(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function readPinnedSessionIds() {
  if (typeof window === 'undefined') {
    return []
  }

  try {
    const value = JSON.parse(window.localStorage.getItem(PINNED_SESSIONS_STORAGE_KEY) || '[]')
    return Array.isArray(value) ? value.filter(Boolean) : []
  } catch (error) {
    return []
  }
}

function persistPinnedSessionIds(ids) {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(PINNED_SESSIONS_STORAGE_KEY, JSON.stringify(ids))
}

export const useSessionStore = defineStore('session', () => {
  const sessions = ref([])
  const currentSessionId = ref(null)
  const loading = ref(false)
  const loaded = ref(false)
  const unreadCounts = ref({})
  const pinnedSessionIds = ref(readPinnedSessionIds())
  let fetchPromise = null

  const currentSession = computed(() =>
    sessions.value.find(session => session.id === currentSessionId.value)
  )

  const sortedSessions = computed(() =>
    [...sessions.value].sort((left, right) => {
      const leftPinned = isPinned(left.id)
      const rightPinned = isPinned(right.id)
      if (leftPinned !== rightPinned) {
        return leftPinned ? -1 : 1
      }
      return new Date(right.updated_at) - new Date(left.updated_at)
    })
  )

  async function runFetchSessions() {
    let lastError = null

    for (let attempt = 0; attempt <= SESSION_FETCH_RETRIES; attempt += 1) {
      try {
        const response = await sessionsApi.list()
        const nextSessions = Array.isArray(response.sessions) ? response.sessions : []
        sessions.value = nextSessions
        prunePinnedSessions(nextSessions)
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

  async function fetchSessions() {
    if (fetchPromise) {
      return fetchPromise
    }

    loading.value = true
    fetchPromise = runFetchSessions()
      .finally(() => {
        loading.value = false
        fetchPromise = null
      })

    return fetchPromise
  }

  async function createSession(title = DEFAULT_SESSION_TITLE) {
    const response = await sessionsApi.create({ title })
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

  function prunePinnedSessions(nextSessions = sessions.value) {
    const validIds = new Set(nextSessions.map(session => session.id))
    const nextPinned = pinnedSessionIds.value.filter(id => validIds.has(id))
    if (nextPinned.length !== pinnedSessionIds.value.length) {
      pinnedSessionIds.value = nextPinned
      persistPinnedSessionIds(nextPinned)
    }
  }

  function isPinned(sessionId) {
    return pinnedSessionIds.value.includes(sessionId)
  }

  function togglePin(sessionId) {
    if (!sessionId) return
    const exists = isPinned(sessionId)
    const nextPinned = exists
      ? pinnedSessionIds.value.filter(id => id !== sessionId)
      : [sessionId, ...pinnedSessionIds.value]
    pinnedSessionIds.value = nextPinned
    persistPinnedSessionIds(nextPinned)
  }

  function shouldAutoTitle(sessionId) {
    const session = sessions.value.find(item => item.id === sessionId)
    if (!session) {
      return false
    }
    return session.title === DEFAULT_SESSION_TITLE && (session.message_count || 0) === 0
  }

  async function deleteSession(sessionId) {
    await sessionsApi.delete(sessionId)
    sessions.value = sessions.value.filter(session => session.id !== sessionId)
    if (isPinned(sessionId)) {
      togglePin(sessionId)
    }
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
    pinnedSessionIds,
    loaded,
    currentSession,
    sortedSessions,
    fetchSessions,
    createSession,
    updateSession,
    syncSession,
    isPinned,
    togglePin,
    shouldAutoTitle,
    deleteSession,
    setCurrentSession,
    markRead,
    incrementUnread
  }
})
