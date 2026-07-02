import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { DEFAULT_STUDENT_ID } from '../config'
import { chatApi } from '../api/chat'
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

function buildErrorMessage(content) {
  return {
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
    isError: true
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

  function appendPendingMessageDelta(sessionId, requestId, delta) {
    const currentMessages = messagesBySession.value[sessionId] || []
    const nextMessages = currentMessages.map(message => {
      if (message.requestId !== requestId) {
        return message
      }

      return {
        ...message,
        content: `${message.content || ''}${delta}`,
        timestamp: new Date().toISOString(),
        isLoading: true
      }
    })

    setSessionMessages(sessionId, nextMessages)
  }

  function getPendingMessage(sessionId, requestId) {
    return (messagesBySession.value[sessionId] || []).find(message => message.requestId === requestId) || null
  }

  function finalizeSessionMessage(sessionId, requestId, nextMessage) {
    const nextMessages = replacePendingMessage(sessionId, requestId, nextMessage)
    setSessionMessages(sessionId, nextMessages)
    return nextMessages
  }

  function syncSessionAfterReply(sessionId, message) {
    const sessionStore = useSessionStore()
    const nextMessages = messagesBySession.value[sessionId] || []

    sessionStore.syncSession(sessionId, {
      message_count: nextMessages.filter(item => !item.isLoading).length,
      updated_at: message?.timestamp || new Date().toISOString()
    })

    if (activeSessionId.value !== sessionId) {
      sessionStore.incrementUnread(sessionId)
    }
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

  async function sendMessageViaHttp(sessionId, message, studentId, requestId, options = {}) {
    const response = await chatApi.send({
      session_id: sessionId,
      message,
      student_id: studentId
    })

    const nextMessage = {
      ...response.message,
      isLoading: false
    }

    finalizeSessionMessage(sessionId, requestId, nextMessage)
    syncSessionAfterReply(sessionId, nextMessage)
    options.onProgress?.()
    return nextMessage
  }

  function sendMessageViaStream(sessionId, message, studentId, requestId, options = {}) {
    return new Promise((resolve, reject) => {
      const source = chatApi.sendStream({
        session_id: sessionId,
        message,
        student_id: studentId
      })

      let settled = false

      const finishWithError = (content, error) => {
        if (settled) return
        settled = true
        source.close()

        const errorMessage = buildErrorMessage(content)
        finalizeSessionMessage(sessionId, requestId, errorMessage)
        syncSessionAfterReply(sessionId, errorMessage)
        options.onProgress?.()
        reject(error)
      }

      source.onmessage = (event) => {
        let payload = null

        try {
          payload = JSON.parse(event.data)
        } catch (error) {
          finishWithError('⚠️ 流式响应解析失败，请重试。', error)
          return
        }

        if (payload.type === 'delta') {
          if (payload.delta) {
            appendPendingMessageDelta(sessionId, requestId, payload.delta)
            options.onProgress?.()
          }
          return
        }

        if (payload.type === 'final') {
          settled = true
          source.close()

          const nextMessage = {
            ...(payload.message || {}),
            isLoading: false
          }

          finalizeSessionMessage(sessionId, requestId, nextMessage)
          syncSessionAfterReply(sessionId, nextMessage)
          options.onProgress?.()
          resolve(nextMessage)
        }
      }

      source.onerror = () => {
        if (settled) {
          return
        }

        const pendingMessage = getPendingMessage(sessionId, requestId)
        const partialContent = pendingMessage?.content?.trim()
        const fallbackContent = partialContent
          ? `${partialContent}\n\n⚠️ 流式连接中断，回答可能不完整。`
          : '⚠️ 发送失败：流式连接已中断，请稍后重试。'

        finishWithError(fallbackContent, new Error('stream connection interrupted'))
      }
    })
  }

  async function sendMessage(sessionId, message, studentId = DEFAULT_STUDENT_ID, options = {}) {
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
    options.onProgress?.()

    try {
      const supportsStream = typeof window !== 'undefined' && 'EventSource' in window

      if (supportsStream) {
        return await sendMessageViaStream(sessionId, message, studentId, requestId, options)
      }

      return await sendMessageViaHttp(sessionId, message, studentId, requestId, options)
    } catch (error) {
      if (getPendingMessage(sessionId, requestId)?.isLoading) {
        const timeoutMessage = error?.code === 'ECONNABORTED'
          ? '⚠️ 本次回答生成时间过长，前端等待超时，请稍后查看会话或重试。'
          : `⚠️ 发送失败：${error.message || '网络错误'}`
        const errorMessage = buildErrorMessage(timeoutMessage)
        finalizeSessionMessage(sessionId, requestId, errorMessage)
        syncSessionAfterReply(sessionId, errorMessage)
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
