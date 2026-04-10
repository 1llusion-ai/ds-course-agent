import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatApi } from '../api/chat'
import { DEFAULT_STUDENT_ID } from '../config'
import { useSessionStore } from './session'

function buildPendingMessage(requestId) {
  return {
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
    isLoading: true,
    requestId
  }
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref([])
  const activeSessionId = ref(null)
  const messagesBySession = ref({})
  const pendingCountsBySession = ref({})

  const loading = computed(() => {
    const sessionId = activeSessionId.value
    if (!sessionId) return false
    return (pendingCountsBySession.value[sessionId] || 0) > 0
  })

  function isSessionPending(sessionId) {
    if (!sessionId) return false
    return (pendingCountsBySession.value[sessionId] || 0) > 0
  }

  function setSessionMessages(sessionId, nextMessages) {
    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: nextMessages
    }

    if (activeSessionId.value === sessionId) {
      messages.value = nextMessages
    }
  }

  function updatePendingCount(sessionId, delta) {
    const current = pendingCountsBySession.value[sessionId] || 0
    const next = Math.max(0, current + delta)
    pendingCountsBySession.value = {
      ...pendingCountsBySession.value,
      [sessionId]: next
    }
  }

  function replacePendingMessage(sessionId, requestId, nextMessage) {
    const currentMessages = messagesBySession.value[sessionId] || []
    let replaced = false

    const nextMessages = currentMessages.map(message => {
      if (message.requestId === requestId) {
        replaced = true
        return nextMessage
      }
      return message
    })

    return replaced ? nextMessages : [...currentMessages, nextMessage]
  }

  async function fetchHistory(sessionId, studentId = DEFAULT_STUDENT_ID) {
    activeSessionId.value = sessionId
    const response = await chatApi.getHistory(sessionId, studentId)
    const history = Array.isArray(response.messages) ? response.messages : []
    const localMessages = messagesBySession.value[sessionId] || []

    const shouldKeepLocal =
      localMessages.some(message => message.isLoading) ||
      localMessages.length > history.length

    const nextMessages = shouldKeepLocal ? localMessages : history
    setSessionMessages(sessionId, nextMessages)
    return response
  }

  async function sendMessage(sessionId, message, studentId = DEFAULT_STUDENT_ID) {
    const requestId = `pending_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const userMessage = {
      role: 'user',
      content: message,
      timestamp: new Date().toISOString()
    }
    const optimisticMessages = [
      ...(messagesBySession.value[sessionId] || []),
      userMessage,
      buildPendingMessage(requestId)
    ]

    updatePendingCount(sessionId, 1)
    setSessionMessages(sessionId, optimisticMessages)

    try {
      const response = await chatApi.send({
        session_id: sessionId,
        message,
        student_id: studentId
      })
      const sessionStore = useSessionStore()
      const nextMessages = replacePendingMessage(sessionId, requestId, response.message)

      setSessionMessages(sessionId, nextMessages)
      sessionStore.syncSession(sessionId, {
        message_count: nextMessages.filter(item => !item.isLoading).length,
        updated_at: response.message.timestamp
      })

      if (activeSessionId.value !== sessionId) {
        sessionStore.incrementUnread(sessionId)
      }

      return response.message
    } catch (error) {
      const sessionStore = useSessionStore()
      const errorMessage = {
        role: 'assistant',
        content: `⚠️ 发送失败：${error.message || '网络错误'}`,
        timestamp: new Date().toISOString(),
        isError: true
      }
      const nextMessages = replacePendingMessage(sessionId, requestId, errorMessage)

      setSessionMessages(sessionId, nextMessages)

      if (activeSessionId.value !== sessionId) {
        sessionStore.incrementUnread(sessionId)
      }

      throw error
    } finally {
      updatePendingCount(sessionId, -1)
    }
  }

  function setActiveSession(sessionId) {
    activeSessionId.value = sessionId

    if (!messagesBySession.value[sessionId]) {
      setSessionMessages(sessionId, [])
    } else {
      messages.value = messagesBySession.value[sessionId]
    }

    const sessionStore = useSessionStore()
    sessionStore.markRead(sessionId)
  }

  function clearMessages(sessionId = activeSessionId.value) {
    if (!sessionId) {
      messages.value = []
      return
    }

    setSessionMessages(sessionId, [])
  }

  return {
    messages,
    loading,
    activeSessionId,
    isSessionPending,
    fetchHistory,
    sendMessage,
    setActiveSession,
    clearMessages
  }
})
