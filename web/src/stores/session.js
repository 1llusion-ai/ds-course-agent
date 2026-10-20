import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { sessionsApi } from '../api/sessions'
import { DEFAULT_COURSE_ID } from '../api/courses'
import { useAuthStore } from './auth'
import { useCourseStore } from './course'
import { accountStorageKey, readLocalStorage, writeLocalStorage } from '../utils/storage'

const DEFAULT_SESSION_TITLE = '新会话'
const SESSION_FETCH_RETRIES = 2
const SESSION_FETCH_RETRY_DELAY_MS = 450
const PINNED_SESSIONS_STORAGE_KEY = 'ds-course-agent.pinnedSessions'

function sleep(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function pinnedStorageKey(user, courseId) {
  const key = accountStorageKey(PINNED_SESSIONS_STORAGE_KEY, user)
  return courseId === DEFAULT_COURSE_ID ? key : `${key}:${courseId}`
}

function readPinnedSessionIds(user, courseId) {
  if (typeof window === 'undefined') {
    return []
  }

  try {
    const key = pinnedStorageKey(user, courseId)
    const value = JSON.parse(readLocalStorage(key) || '[]')
    return Array.isArray(value) ? value.filter(Boolean) : []
  } catch (error) {
    return []
  }
}

function persistPinnedSessionIds(ids, user, courseId) {
  if (typeof window === 'undefined') {
    return
  }
  const key = pinnedStorageKey(user, courseId)
  writeLocalStorage(key, JSON.stringify(ids))
}

export const useSessionStore = defineStore('session', () => {
  const authStore = useAuthStore()
  const courseStore = useCourseStore()
  const sessions = ref([])
  const currentSessionId = ref(null)
  const loading = ref(false)
  const loaded = ref(false)
  const unreadCounts = ref({})
  const pinnedSessionIds = ref(readPinnedSessionIds(authStore.user, courseStore.selectedCourseId))
  let fetchPromise = null
  let stateVersion = 0

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

  async function runFetchSessions(courseId = courseStore.selectedCourseId) {
    const requestStateVersion = stateVersion
    let lastError = null

    for (let attempt = 0; attempt <= SESSION_FETCH_RETRIES; attempt += 1) {
      try {
        const response = await sessionsApi.list(courseId)
        const nextSessions = Array.isArray(response.sessions) ? response.sessions : []
        if (requestStateVersion !== stateVersion) {
          return nextSessions
        }
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

  async function fetchSessions(courseId = courseStore.selectedCourseId) {
    if (fetchPromise) {
      return fetchPromise
    }

    loading.value = true
    const request = runFetchSessions(courseId)
    fetchPromise = request
    return request.finally(() => {
      if (fetchPromise === request) {
        loading.value = false
        fetchPromise = null
      }
    })
  }

  async function createSession(title = DEFAULT_SESSION_TITLE) {
    const requestStateVersion = stateVersion
    const response = await sessionsApi.create({ title }, courseStore.selectedCourseId)
    if (requestStateVersion !== stateVersion) return null
    sessions.value.unshift(response)
    currentSessionId.value = response.id
    return response
  }

  async function updateSession(sessionId, data) {
    const requestStateVersion = stateVersion
    const response = await sessionsApi.update(sessionId, data, courseStore.selectedCourseId)
    if (requestStateVersion !== stateVersion) return response
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
      persistPinnedSessionIds(nextPinned, authStore.user, courseStore.selectedCourseId)
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
    persistPinnedSessionIds(nextPinned, authStore.user, courseStore.selectedCourseId)
  }

  function shouldAutoTitle(sessionId) {
    const session = sessions.value.find(item => item.id === sessionId)
    if (!session) {
      return false
    }
    return session.title === DEFAULT_SESSION_TITLE && (session.message_count || 0) === 0
  }

  async function deleteSession(sessionId) {
    const requestStateVersion = stateVersion
    await sessionsApi.delete(sessionId, courseStore.selectedCourseId)
    if (requestStateVersion !== stateVersion) return
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

  function resetForUser() {
    stateVersion += 1
    fetchPromise = null
    sessions.value = []
    currentSessionId.value = null
    unreadCounts.value = {}
    pinnedSessionIds.value = readPinnedSessionIds(authStore.user, courseStore.selectedCourseId)
    loading.value = false
    loaded.value = false
  }

  function resetForCourse() {
    resetForUser()
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
    incrementUnread,
    resetForUser,
    resetForCourse
  }
})
