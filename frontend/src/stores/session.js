import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { sessionsApi } from '../api/sessions'
import { DEFAULT_STUDENT_ID } from '../config'

const DEFAULT_SESSION_TITLE = '新会话'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref([])
  const currentSessionId = ref(null)
  const loading = ref(false)
  const unreadCounts = ref({})

  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value)
  )

  const sortedSessions = computed(() =>
    [...sessions.value].sort((a, b) =>
      new Date(b.updated_at) - new Date(a.updated_at)
    )
  )

  async function fetchSessions(studentId = DEFAULT_STUDENT_ID) {
    loading.value = true
    try {
      const response = await sessionsApi.list(studentId)
      sessions.value = response.sessions
      return response.sessions
    } finally {
      loading.value = false
    }
  }

  async function createSession(title = DEFAULT_SESSION_TITLE, studentId = DEFAULT_STUDENT_ID) {
    const response = await sessionsApi.create({
      title, student_id: studentId
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
    if (!session) return false
    return session.title === DEFAULT_SESSION_TITLE && (session.message_count || 0) === 0
  }

  async function deleteSession(sessionId, studentId = DEFAULT_STUDENT_ID) {
    await sessionsApi.delete(sessionId, studentId)
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
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
    sessions, currentSessionId, loading, unreadCounts,
    currentSession, sortedSessions,
    fetchSessions, createSession, updateSession, syncSession, shouldAutoTitle,
    deleteSession, setCurrentSession, markRead, incrementUnread
  }
})
