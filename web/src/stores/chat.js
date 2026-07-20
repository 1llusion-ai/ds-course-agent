import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { chatApi } from '../api/chat'
import { useSessionStore } from './session'

const STREAM_LONG_WAIT_MS = 15_000
const STREAM_IDLE_TIMEOUT_MS = 120_000

function buildPendingMessage(requestId) {
  const startedAt = new Date().toISOString()
  return {
    role: 'assistant',
    content: '',
    timestamp: startedAt,
    isLoading: true,
    requestId,
    progress: null,
    progressEvents: []
  }
}

function buildBackendPendingMessage(sessionId, response = {}) {
  const startedAt = response.pending_started_at || new Date().toISOString()
  return {
    role: 'assistant',
    content: '',
    timestamp: startedAt,
    isLoading: true,
    requestId: `backend_pending_${sessionId}`,
    progress: {
      phase: 'generation',
      message: '刷新后继续生成中，请稍候…',
      timestamp: startedAt
    },
    progressEvents: [
      {
        phase: 'generation',
        message: '刷新后继续生成中，请稍候…',
        timestamp: startedAt
      }
    ]
  }
}

function buildErrorMessage(content, extra = {}) {
  return {
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
    isError: true,
    ...extra
  }
}

function normalizeProgressEvent(progress = {}) {
  return {
    phase: progress.phase || progress.status || progress.type || '',
    message: progress.message || '',
    route: progress.route || '',
    tool: progress.tool || '',
    stream_id: progress.stream_id || '',
    resuming: Boolean(progress.resuming),
    details: progress.details || null,
    timestamp: progress.timestamp || new Date().toISOString()
  }
}

function sourcesFromProgressDetails(details = {}) {
  const results = Array.isArray(details?.results) ? details.results : []
  return results
    .map((item, index) => {
      const sourceId = Number(item.source_id || item.sourceId || item.index || index + 1)
      const safeSourceId = Number.isFinite(sourceId) && sourceId > 0 ? sourceId : index + 1
      return {
        source_id: safeSourceId,
        reference: item.title ? `[${safeSourceId}] ${item.title}` : `联网来源 ${safeSourceId}`,
        title: item.title || item.domain || item.url || `网页 ${safeSourceId}`,
        snippet: item.snippet || item.summary || item.description || '',
        domain: item.domain || '',
        url: item.url || '',
        provider: details.provider || item.provider || '',
        published_at: item.published_at || null,
        source: 'web'
      }
    })
    .filter(item => item.url)
}

function latestRouteFromProgress(events = []) {
  const reversed = [...events].reverse()
  const event = reversed.find(item => item?.route)
  return event?.route || ''
}

function progressEventList(message = {}) {
  if (Array.isArray(message.progressEvents)) return message.progressEvents
  if (Array.isArray(message.progress_events)) return message.progress_events
  return []
}

function hasProgressDetails(message = {}) {
  return Boolean(message.progress || progressEventList(message).length)
}

function isSameStoredMessage(left = {}, right = {}) {
  return left.role === right.role && (left.content || '') === (right.content || '')
}

function mergeHistoryWithLocalProgress(history = [], localMessages = []) {
  if (!history.length || !localMessages.length) return history

  const usedLocalIndexes = new Set()

  return history.map((remoteMessage, index) => {
    let localMessage = localMessages[index]
    let localIndex = index

    if (!isSameStoredMessage(remoteMessage, localMessage)) {
      localIndex = localMessages.findIndex((candidate, candidateIndex) => (
        !usedLocalIndexes.has(candidateIndex) &&
        isSameStoredMessage(remoteMessage, candidate)
      ))
      localMessage = localIndex >= 0 ? localMessages[localIndex] : null
    }

    if (localIndex >= 0) {
      usedLocalIndexes.add(localIndex)
    }

    if (!localMessage || hasProgressDetails(remoteMessage) || !hasProgressDetails(localMessage)) {
      return remoteMessage
    }

    const localProgressEvents = progressEventList(localMessage)

    return {
      ...remoteMessage,
      route: remoteMessage.route || localMessage.route,
      metadata: {
        ...(localMessage.metadata || {}),
        ...(remoteMessage.metadata || {})
      },
      progress: remoteMessage.progress || localMessage.progress || null,
      progressEvents: remoteMessage.progressEvents || localMessage.progressEvents,
      progress_events: remoteMessage.progress_events || localMessage.progress_events || localProgressEvents
    }
  })
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref([])
  const activeSessionId = ref(null)
  const messagesBySession = ref({})
  const pendingCountsBySession = ref({})
  const activeRequestsBySession = new Map()
  const pendingHistoryPollTimers = new Map()

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

  function setPendingCount(sessionId, count) {
    pendingCountsBySession.value = {
      ...pendingCountsBySession.value,
      [sessionId]: Math.max(0, count)
    }
  }

  function ensureBackendPendingMessage(sessionId, nextMessages, response = {}) {
    if (!response.pending_generation) return nextMessages
    if (nextMessages.some(message => message.isLoading)) return nextMessages
    return [...nextMessages, buildBackendPendingMessage(sessionId, response)]
  }

  function stopPendingHistoryPoll(sessionId) {
    const timerId = pendingHistoryPollTimers.get(sessionId)
    if (timerId) {
      window.clearInterval(timerId)
      pendingHistoryPollTimers.delete(sessionId)
    }
  }

  function startPendingHistoryPoll(sessionId) {
    if (!sessionId || pendingHistoryPollTimers.has(sessionId) || typeof window === 'undefined') return
    const timerId = window.setInterval(() => {
      fetchHistory(sessionId).catch(error => {
        console.warn('轮询生成结果失败:', error)
      })
    }, 2_000)
    pendingHistoryPollTimers.set(sessionId, timerId)
  }

  function syncBackendPendingState(sessionId, response = {}) {
    if (response.pending_generation) {
      setPendingCount(sessionId, Math.max(1, pendingCountsBySession.value[sessionId] || 0))
      startPendingHistoryPoll(sessionId)
      return
    }

    stopPendingHistoryPoll(sessionId)
    if (!activeRequestsBySession.has(sessionId)) {
      setPendingCount(sessionId, 0)
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

  function updatePendingMessageProgress(sessionId, requestId, progress) {
    const currentMessages = messagesBySession.value[sessionId] || []
    const nextProgress = normalizeProgressEvent(progress)
    const nextMessages = currentMessages.map(message => {
      if (message.requestId !== requestId) {
        return message
      }

      const progressEvents = Array.isArray(message.progressEvents)
        ? [...message.progressEvents, nextProgress]
        : [nextProgress]
      const progressSources = sourcesFromProgressDetails(nextProgress.details)

      return {
        ...message,
        sources: message.sources || (progressSources.length ? progressSources : undefined),
        progress: nextProgress,
        progressEvents,
        route: message.route || nextProgress.route || undefined,
        timestamp: new Date().toISOString(),
        isLoading: true
      }
    })

    setSessionMessages(sessionId, nextMessages)
  }

  function getPendingMessage(sessionId, requestId) {
    return (messagesBySession.value[sessionId] || []).find(message => message.requestId === requestId) || null
  }

  function clearActiveRequest(sessionId, requestId) {
    const activeRequest = activeRequestsBySession.get(sessionId)
    if (activeRequest?.requestId === requestId) {
      activeRequestsBySession.delete(sessionId)
    }
  }

  function finalizeSessionMessage(sessionId, requestId, nextMessage) {
    const pendingMessage = getPendingMessage(sessionId, requestId)
    const progressEvents = pendingMessage?.progressEvents || nextMessage.progressEvents || []
    const latestRoute = nextMessage.route || pendingMessage?.route || latestRouteFromProgress(progressEvents)
    const mergedMessage = {
      ...nextMessage,
      // Preserve the pending message's requestId so the chat list can keep a
      // stable v-for :key across the pending -> final transition. Without this,
      // the timestamp-based key mutates on every streaming delta and Vue
      // remounts the message component, collapsing the "查看执行过程" disclosure.
      requestId: pendingMessage?.requestId || nextMessage.requestId || undefined,
      route: latestRoute || nextMessage.route,
      metadata: {
        ...(pendingMessage?.metadata || {}),
        ...(nextMessage.metadata || {}),
        ...(latestRoute ? { route: latestRoute } : {})
      },
      progress: nextMessage.progress || pendingMessage?.progress || null,
      progressEvents
    }
    const nextMessages = replacePendingMessage(sessionId, requestId, mergedMessage)
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

  async function fetchHistory(sessionId) {
    activeSessionId.value = sessionId
    const response = await chatApi.getHistory(sessionId)
    const history = Array.isArray(response.messages) ? response.messages : []
    const localMessages = messagesBySession.value[sessionId] || []
    const hasLocalLoading = localMessages.some(message => message.isLoading)
    const hasActiveRequest = activeRequestsBySession.has(sessionId)

    const shouldKeepLocal =
      ((response.pending_generation || hasActiveRequest) && hasLocalLoading) ||
      (!hasLocalLoading && localMessages.length > history.length)

    const baseMessages = shouldKeepLocal
      ? localMessages
      : mergeHistoryWithLocalProgress(history, localMessages)
    const nextMessages = ensureBackendPendingMessage(sessionId, baseMessages, response)
    setSessionMessages(sessionId, nextMessages)
    syncBackendPendingState(sessionId, response)
    return response
  }

  async function sendMessageViaHttp(sessionId, message, requestId, options = {}) {
    const response = await chatApi.send({
      session_id: sessionId,
      message,
      web_search: Boolean(options.webSearch)
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

  function sendMessageViaStream(sessionId, message, requestId, options = {}) {
    return new Promise((resolve, reject) => {
      const source = chatApi.sendStream({
        session_id: sessionId,
        message,
        web_search: Boolean(options.webSearch)
      })

      let settled = false
      let longWaitTimer = null
      let idleTimeoutTimer = null

      const clearStreamTimers = () => {
        if (longWaitTimer !== null) {
          window.clearTimeout(longWaitTimer)
          longWaitTimer = null
        }
        if (idleTimeoutTimer !== null) {
          window.clearTimeout(idleTimeoutTimer)
          idleTimeoutTimer = null
        }
      }

      const armStreamTimers = () => {
        clearStreamTimers()
        longWaitTimer = window.setTimeout(() => {
          updatePendingMessageProgress(sessionId, requestId, {
            phase: 'long_wait',
            message: '生成时间较长，可继续等待或停止重试。'
          })
          options.onProgress?.()
        }, STREAM_LONG_WAIT_MS)
        idleTimeoutTimer = window.setTimeout(() => {
          const timeoutError = new Error('stream generation timed out')
          timeoutError.code = 'ECONNABORTED'
          finishWithError(
            '⚠️ 本次生成超时，请关闭联网搜索或重试。',
            timeoutError,
            {
              web_search_requested: Boolean(options.webSearch),
              web_search_used: false,
              web_search_status: Boolean(options.webSearch) ? 'error' : 'not_requested',
              web_search_reason: Boolean(options.webSearch) ? '本次流式生成超时。' : null
            }
          )
        }, STREAM_IDLE_TIMEOUT_MS)
      }

      const finishWithError = (content, error, extra = {}) => {
        if (settled) return
        settled = true
        clearStreamTimers()
        clearActiveRequest(sessionId, requestId)
        source.close()

        const errorMessage = buildErrorMessage(content, extra)
        finalizeSessionMessage(sessionId, requestId, errorMessage)
        syncSessionAfterReply(sessionId, errorMessage)
        options.onProgress?.()
        reject(error)
      }

      activeRequestsBySession.set(sessionId, {
        requestId,
        cancel: async () => {
          try {
            await chatApi.cancelStream(sessionId)
          } catch (error) {
            console.warn('通知后端停止生成失败:', error)
          }
          const cancelError = new Error('request cancelled')
          cancelError.code = 'REQUEST_CANCELLED'
          finishWithError('⚠️ 已停止本次回答。', cancelError)
        }
      })
      armStreamTimers()

      source.onmessage = (event) => {
        armStreamTimers()
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

        if (payload.type === 'progress') {
          updatePendingMessageProgress(sessionId, requestId, {
            phase: payload.phase,
            message: payload.message,
            route: payload.route,
            tool: payload.tool,
            stream_id: payload.stream_id,
            resuming: Boolean(payload.resuming),
            details: payload.details || null,
            timestamp: payload.timestamp
          })
          options.onProgress?.()
          return
        }

        if (payload.type === 'final') {
          settled = true
          clearStreamTimers()
          clearActiveRequest(sessionId, requestId)
          source.close()

          const nextMessage = {
            ...(payload.message || {}),
            isLoading: false,
            stream_id: payload.stream_id
          }

          finalizeSessionMessage(sessionId, requestId, nextMessage)
          syncSessionAfterReply(sessionId, nextMessage)
          options.onProgress?.()
          resolve(nextMessage)
        }
      }

      source.onerror = (error) => {
        if (settled) {
          return
        }

        const pendingMessage = getPendingMessage(sessionId, requestId)
        const partialContent = pendingMessage?.content?.trim()
        const fallbackContent = partialContent
          ? `${partialContent}\n\n⚠️ 流式连接中断，回答可能不完整。`
          : '⚠️ 发送失败：流式连接已中断，请稍后重试。'

        finishWithError(fallbackContent, error || new Error('stream connection interrupted'))
      }
    })
  }

  async function sendMessage(sessionId, message, options = {}) {
    const requestId = `pending_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const userMessage = {
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      metadata: options.webSearch ? { web_search: true } : undefined
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
      const supportsStream = typeof fetch !== 'undefined' && typeof window !== 'undefined' && 'ReadableStream' in window

      if (supportsStream) {
        return await sendMessageViaStream(sessionId, message, requestId, options)
      }

      return await sendMessageViaHttp(sessionId, message, requestId, options)
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

    if (!sessionId) {
      messages.value = []
      return
    }

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

    stopPendingHistoryPoll(sessionId)
    setSessionMessages(sessionId, [])
    setPendingCount(sessionId, 0)
  }

  async function cancelActiveRequest(sessionId = activeSessionId.value) {
    if (!sessionId) return false
    const activeRequest = activeRequestsBySession.get(sessionId)
    if (activeRequest) {
      await activeRequest.cancel()
      return true
    }

    if (pendingCountsBySession.value[sessionId]) {
      await chatApi.cancelStream(sessionId)
      stopPendingHistoryPoll(sessionId)
      setPendingCount(sessionId, 0)
      const pendingMessage = (messagesBySession.value[sessionId] || []).find(message => message.isLoading)
      if (pendingMessage?.requestId) {
        finalizeSessionMessage(sessionId, pendingMessage.requestId, buildErrorMessage('⚠️ 已停止本次回答。'))
      }
      return true
    }
    return false
  }

  return {
    messages,
    loading,
    activeSessionId,
    isSessionPending,
    fetchHistory,
    sendMessage,
    setActiveSession,
    clearMessages,
    cancelActiveRequest
  }
})
