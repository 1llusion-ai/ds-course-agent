import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi } from '../api/chat'
import { DEFAULT_STUDENT_ID } from '../config'
import { useSessionStore } from './session'

export const useChatStore = defineStore('chat', () => {
  const messages = ref([])
  const loading = ref(false)
  const activeSessionId = ref(null)
  const loadingSessionId = ref(null)
  const messagesBySession = ref({})

  function ensureSessionMessages(sessionId) {
    if (!messagesBySession.value[sessionId]) {
      messagesBySession.value[sessionId] = []
    }
    return messagesBySession.value[sessionId]
  }

  async function fetchHistory(sessionId, studentId = DEFAULT_STUDENT_ID) {
    activeSessionId.value = sessionId
    const response = await chatApi.getHistory(sessionId, studentId)
    const history = Array.isArray(response.messages) ? response.messages : []
    // 整体替换对象以触发Vue响应式更新
    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: history
    }

    // 仅在会话仍然活跃时更新 visuals
    if (activeSessionId.value === sessionId) {
      const localMessages = messagesBySession.value[sessionId] || []
      // 如果当前正在发送消息，且本地已有乐观消息，但后端历史尚未包含它，则保护本地状态
      if (loadingSessionId.value === sessionId && localMessages.length > history.length) {
        // 不覆盖，保持本地乐观更新
      } else {
        messages.value = history
      }
    }
    return response
  }

  async function sendMessage(sessionId, message, studentId = DEFAULT_STUDENT_ID) {
    loading.value = true
    loadingSessionId.value = sessionId

    // 创建新数组触发响应式更新 - 必须整体替换对象才能触发Vue响应式
    const userMessage = {
      role: 'user', content: message, timestamp: new Date().toISOString()
    }
    const currentMessages = messagesBySession.value[sessionId] || []
    const messagesWithUser = [...currentMessages, userMessage]
    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: messagesWithUser
    }
    if (activeSessionId.value === sessionId) {
      messages.value = messagesBySession.value[sessionId]
    }

    try {
      const response = await chatApi.send({
        session_id: sessionId, message, student_id: studentId
      })

      // 使用本地快照合并回复，避免 fetchHistory 并发覆盖导致用户消息消失
      const messagesWithResponse = [...messagesWithUser, response.message]
      messagesBySession.value = {
        ...messagesBySession.value,
        [sessionId]: messagesWithResponse
      }
      if (activeSessionId.value === sessionId) {
        messages.value = messagesWithResponse
      } else {
        const sessionStore = useSessionStore()
        sessionStore.incrementUnread(sessionId)
      }
      return response.message
    } catch (error) {
      const sessionStore = useSessionStore()
      if (activeSessionId.value !== sessionId) {
        sessionStore.incrementUnread(sessionId)
      }
      // 添加错误消息到对话
      const errorResponse = {
        role: 'assistant',
        content: `⚠️ 发送失败：${error.message || '网络错误'}`,
        timestamp: new Date().toISOString(),
        isError: true
      }
      messagesBySession.value = {
        ...messagesBySession.value,
        [sessionId]: [...messagesBySession.value[sessionId], errorResponse]
      }
      if (activeSessionId.value === sessionId) {
        messages.value = messagesBySession.value[sessionId]
      }
      throw error
    } finally {
      if (loadingSessionId.value === sessionId) {
        loadingSessionId.value = null
      }
      loading.value = false
    }
  }

  function setActiveSession(sessionId) {
    activeSessionId.value = sessionId
    // 确保会话消息数组存在
    if (!messagesBySession.value[sessionId]) {
      messagesBySession.value = {
        ...messagesBySession.value,
        [sessionId]: []
      }
    }
    messages.value = messagesBySession.value[sessionId] || []

    if (loadingSessionId.value) {
      if (loadingSessionId.value === sessionId) {
        loading.value = true
      } else {
        loading.value = false
      }
    }

    const sessionStore = useSessionStore()
    sessionStore.markRead(sessionId)
  }

  function clearMessages(sessionId = activeSessionId.value) {
    if (!sessionId) {
      messages.value = []
      return
    }

    messagesBySession.value = {
      ...messagesBySession.value,
      [sessionId]: []
    }
    if (activeSessionId.value === sessionId) {
      messages.value = []
    }
  }

  return {
    messages,
    loading,
    activeSessionId,
    fetchHistory,
    sendMessage,
    setActiveSession,
    clearMessages
  }
})
