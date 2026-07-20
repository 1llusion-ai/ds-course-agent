import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { chatApi } from '../api/chat'
import {
  buildActiveStreamMessage,
  buildErrorMessage,
  buildPendingMessage,
  buildStoppedMessage,
  latestRouteFromProgress,
  mergeHistoryWithLocalProgress,
  normalizeHistoryMessage,
  normalizeProgressEvent,
  sourcesFromProgressDetails
} from './chatMessages'
import { useSessionStore } from './session'

const STREAM_LONG_WAIT_MS = 15_000
const STREAM_IDLE_TIMEOUT_MS = 120_000
const STREAM_RECONNECT_DELAY_MS = 1_000

export const useChatStore = defineStore('chat', () => {
  const messages = ref([])
  const activeSessionId = ref(null)
  const messagesBySession = ref({})
  const pendingCountsBySession = ref({})
  const activeRequestsBySession = new Map()
  const reconnectTimersBySession = new Map()

  const loading = computed(() => {
    const sessionId = activeSessionId.value
    return Boolean(sessionId && (pendingCountsBySession.value[sessionId] || 0) > 0)
  })

  function isSessionPending(sessionId) {
    return Boolean(sessionId && (pendingCountsBySession.value[sessionId] || 0) > 0)
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

  function setPendingCount(sessionId, count) {
    pendingCountsBySession.value = {
      ...pendingCountsBySession.value,
      [sessionId]: Math.max(0, count)
    }
  }

  function updatePendingCount(sessionId, delta) {
    setPendingCount(sessionId, (pendingCountsBySession.value[sessionId] || 0) + delta)
  }

  function clearReconnectTimer(sessionId) {
    const timerId = reconnectTimersBySession.get(sessionId)
    if (timerId && typeof window !== 'undefined') {
      window.clearTimeout(timerId)
    }
    reconnectTimersBySession.delete(sessionId)
  }

  function scheduleHistoryReconnect(sessionId) {
    if (!sessionId || reconnectTimersBySession.has(sessionId) || typeof window === 'undefined') return
    const timerId = window.setTimeout(() => {
      reconnectTimersBySession.delete(sessionId)
      fetchHistory(sessionId).catch(error => {
        console.warn('恢复生成流失败:', error)
        scheduleHistoryReconnect(sessionId)
      })
    }, STREAM_RECONNECT_DELAY_MS)
    reconnectTimersBySession.set(sessionId, timerId)
  }

  function replacePendingMessage(sessionId, requestId, nextMessage) {
    const currentMessages = messagesBySession.value[sessionId] || []
    let replaced = false
    const nextMessages = currentMessages.map(message => {
      if (message.requestId !== requestId) return message
      replaced = true
      return nextMessage
    })
    return replaced ? nextMessages : [...currentMessages, nextMessage]
  }

  function getPendingMessage(sessionId, requestId) {
    return (messagesBySession.value[sessionId] || []).find(message => message.requestId === requestId) || null
  }

  function getLoadingMessage(sessionId) {
    return (messagesBySession.value[sessionId] || []).find(message => message.isLoading) || null
  }

  function clearActiveRequest(sessionId, requestId) {
    const activeRequest = activeRequestsBySession.get(sessionId)
    if (activeRequest?.requestId === requestId) {
      activeRequestsBySession.delete(sessionId)
    }
  }

  function replacePendingWithSnapshot(sessionId, requestId, snapshot = {}) {
    const currentMessages = messagesBySession.value[sessionId] || []
    const nextMessages = currentMessages.map(message => {
      if (message.requestId !== requestId) return message

      const progressEvents = Array.isArray(snapshot.progress_events)
        ? snapshot.progress_events.map(normalizeProgressEvent)
        : message.progressEvents || []
      const progress = snapshot.progress
        ? normalizeProgressEvent(snapshot.progress)
        : (progressEvents.at(-1) || message.progress || null)
      const progressSources = sourcesFromProgressDetails(progress?.details)

      return {
        ...message,
        content: snapshot.content ?? message.content ?? '',
        timestamp: snapshot.message_timestamp || message.timestamp,
        sources: message.sources || (progressSources.length ? progressSources : undefined),
        progress,
        progressEvents,
        stream_id: snapshot.stream_id || message.stream_id,
        streamEventId: Number(snapshot.event_id || snapshot.last_event_id || message.streamEventId || 0),
        generation_status: 'generating',
        isLoading: true
      }
    })
    setSessionMessages(sessionId, nextMessages)
  }

  function appendPendingMessageDelta(sessionId, requestId, payload = {}) {
    const currentMessages = messagesBySession.value[sessionId] || []
    const eventId = Number(payload.event_id || 0)
    const nextMessages = currentMessages.map(message => {
      if (message.requestId !== requestId) return message
      if (eventId && eventId <= Number(message.streamEventId || 0)) return message

      return {
        ...message,
        content: `${message.content || ''}${payload.delta || ''}`,
        stream_id: payload.stream_id || message.stream_id,
        streamEventId: eventId || message.streamEventId,
        generation_status: 'generating',
        isLoading: true
      }
    })
    setSessionMessages(sessionId, nextMessages)
  }

  function updatePendingMessageProgress(sessionId, requestId, payload = {}) {
    const currentMessages = messagesBySession.value[sessionId] || []
    const eventId = Number(payload.event_id || 0)
    const nextProgress = normalizeProgressEvent(payload)
    const nextMessages = currentMessages.map(message => {
      if (message.requestId !== requestId) return message
      if (eventId && eventId <= Number(message.streamEventId || 0)) return message

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
        stream_id: payload.stream_id || message.stream_id,
        streamEventId: eventId || message.streamEventId,
        generation_status: 'generating',
        isLoading: true
      }
    })
    setSessionMessages(sessionId, nextMessages)
  }

  function finalizeSessionMessage(sessionId, requestId, nextMessage) {
    const pendingMessage = getPendingMessage(sessionId, requestId)
    const progressEvents = pendingMessage?.progressEvents || nextMessage.progressEvents || []
    const latestRoute = nextMessage.route || pendingMessage?.route || latestRouteFromProgress(progressEvents)
    const normalizedMessage = normalizeHistoryMessage(nextMessage)
    const mergedMessage = {
      ...pendingMessage,
      ...normalizedMessage,
      requestId: pendingMessage?.requestId || normalizedMessage.requestId || undefined,
      route: latestRoute || normalizedMessage.route,
      metadata: {
        ...(pendingMessage?.metadata || {}),
        ...(normalizedMessage.metadata || {}),
        ...(latestRoute ? { route: latestRoute } : {})
      },
      progress: normalizedMessage.progress || pendingMessage?.progress || null,
      progressEvents
    }
    const nextMessages = replacePendingMessage(sessionId, requestId, mergedMessage)
    setSessionMessages(sessionId, nextMessages)
    return mergedMessage
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

  function markMessageAsGenerating(sessionId, targetMessage) {
    const requestId = targetMessage.requestId || `continue_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const nextMessages = (messagesBySession.value[sessionId] || []).map(message => {
      if (message !== targetMessage && message.timestamp !== targetMessage.timestamp) return message
      return {
        ...message,
        requestId,
        isLoading: true,
        isError: false,
        generation_status: 'generating',
        generation_error: null
      }
    })
    setSessionMessages(sessionId, nextMessages)
    return requestId
  }

  function consumeStream(sessionId, requestId, source, options = {}) {
    return new Promise((resolve, reject) => {
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

      const finishStopped = error => {
        if (settled) return
        settled = true
        clearStreamTimers()
        clearActiveRequest(sessionId, requestId)
        source.close()

        const pendingMessage = getPendingMessage(sessionId, requestId)
        if (pendingMessage) {
          const stoppedMessage = buildStoppedMessage(pendingMessage)
          finalizeSessionMessage(sessionId, requestId, stoppedMessage)
          syncSessionAfterReply(sessionId, stoppedMessage)
        }
        options.onProgress?.()
        reject(error)
      }

      const finishWithError = (content, error, extra = {}) => {
        if (settled) return
        settled = true
        clearStreamTimers()
        clearActiveRequest(sessionId, requestId)
        source.close()

        const pendingMessage = getPendingMessage(sessionId, requestId)
        const errorMessage = buildErrorMessage(content, {
          ...pendingMessage,
          ...extra,
          content,
          isLoading: false,
          isError: true,
          generation_status: 'error'
        })
        finalizeSessionMessage(sessionId, requestId, errorMessage)
        syncSessionAfterReply(sessionId, errorMessage)
        options.onProgress?.()
        reject(error)
      }

      const armStreamTimers = () => {
        clearStreamTimers()
        longWaitTimer = window.setTimeout(() => {
          updatePendingMessageProgress(sessionId, requestId, {
            phase: 'long_wait',
            message: '生成时间较长，可继续等待或停止。'
          })
          options.onProgress?.()
        }, STREAM_LONG_WAIT_MS)
        idleTimeoutTimer = window.setTimeout(() => {
          const timeoutError = new Error('stream generation timed out')
          timeoutError.code = 'ECONNABORTED'
          chatApi.cancelStream(sessionId).catch(() => {})
          const partialContent = getPendingMessage(sessionId, requestId)?.content?.trim()
          finishWithError(
            partialContent
              ? `${partialContent}\n\n⚠️ 本次生成超时，回答可能不完整。`
              : '⚠️ 本次生成超时，请稍后重试。',
            timeoutError
          )
        }, STREAM_IDLE_TIMEOUT_MS)
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
          finishStopped(cancelError)
        }
      })
      armStreamTimers()

      source.onmessage = event => {
        armStreamTimers()
        let payload
        try {
          payload = JSON.parse(event.data)
        } catch (error) {
          finishWithError('⚠️ 流式响应解析失败，请重试。', error)
          return
        }

        if (payload.type === 'snapshot') {
          replacePendingWithSnapshot(sessionId, requestId, payload)
          options.onProgress?.()
          return
        }

        if (payload.type === 'delta') {
          if (payload.delta) {
            appendPendingMessageDelta(sessionId, requestId, payload)
            options.onProgress?.()
          }
          return
        }

        if (payload.type === 'progress') {
          updatePendingMessageProgress(sessionId, requestId, payload)
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
          const mergedMessage = finalizeSessionMessage(sessionId, requestId, nextMessage)
          syncSessionAfterReply(sessionId, mergedMessage)
          options.onProgress?.()
          resolve(mergedMessage)
        }
      }

      source.onerror = error => {
        if (settled) return

        if (options.resuming) {
          settled = true
          clearStreamTimers()
          clearActiveRequest(sessionId, requestId)
          source.close()
          scheduleHistoryReconnect(sessionId)
          reject(error || new Error('resume stream connection interrupted'))
          return
        }

        const partialContent = getPendingMessage(sessionId, requestId)?.content?.trim()
        finishWithError(
          partialContent
            ? `${partialContent}\n\n⚠️ 流式连接中断，回答可能不完整。`
            : '⚠️ 发送失败：流式连接已中断，请稍后重试。',
          error || new Error('stream connection interrupted')
        )
      }
    })
  }

  function resumeActiveStream(sessionId) {
    if (!sessionId || activeRequestsBySession.has(sessionId)) return
    const pendingMessage = getLoadingMessage(sessionId)
    if (!pendingMessage?.requestId) return

    clearReconnectTimer(sessionId)
    setPendingCount(sessionId, 1)
    const source = chatApi.resumeStream(sessionId)
    consumeStream(sessionId, pendingMessage.requestId, source, { resuming: true })
      .catch(error => {
        console.warn('生成流重连中断:', error)
      })
      .finally(() => {
        if (!activeRequestsBySession.has(sessionId) && !getLoadingMessage(sessionId)) {
          setPendingCount(sessionId, 0)
        }
      })
  }

  async function fetchHistory(sessionId) {
    activeSessionId.value = sessionId
    const response = await chatApi.getHistory(sessionId)
    const history = Array.isArray(response.messages)
      ? response.messages.map(normalizeHistoryMessage)
      : []
    const localMessages = messagesBySession.value[sessionId] || []
    const hasLocalLoading = localMessages.some(message => message.isLoading)
    const hasActiveRequest = activeRequestsBySession.has(sessionId)
    const activeStream = response.active_stream || null

    let nextMessages
    if (activeStream && hasActiveRequest && hasLocalLoading) {
      nextMessages = localMessages
    } else {
      nextMessages = mergeHistoryWithLocalProgress(history, localMessages)
      if (activeStream) {
        nextMessages = [
          ...nextMessages.filter(message => !message.isLoading),
          buildActiveStreamMessage(sessionId, activeStream)
        ]
      }
    }

    setSessionMessages(sessionId, nextMessages)
    if (activeStream) {
      setPendingCount(sessionId, 1)
      resumeActiveStream(sessionId)
    } else if (!hasActiveRequest) {
      clearReconnectTimer(sessionId)
      setPendingCount(sessionId, 0)
    }
    return response
  }

  async function sendMessageViaHttp(sessionId, message, requestId, options = {}) {
    const response = await chatApi.send({
      session_id: sessionId,
      message,
      web_search: Boolean(options.webSearch)
    })
    const nextMessage = finalizeSessionMessage(sessionId, requestId, response.message)
    syncSessionAfterReply(sessionId, nextMessage)
    options.onProgress?.()
    return nextMessage
  }

  function sendMessageViaStream(sessionId, message, requestId, options = {}) {
    const source = chatApi.sendStream({
      session_id: sessionId,
      message,
      web_search: Boolean(options.webSearch)
    })
    return consumeStream(sessionId, requestId, source, options)
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
          ? '⚠️ 本次回答生成时间过长，请稍后重试。'
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

  async function continueMessage(sessionId, targetMessage, options = {}) {
    if (!sessionId || !targetMessage?.timestamp || isSessionPending(sessionId)) return null

    const requestId = markMessageAsGenerating(sessionId, targetMessage)
    updatePendingCount(sessionId, 1)
    options.onProgress?.()

    try {
      const source = chatApi.continueStream({
        session_id: sessionId,
        message_timestamp: targetMessage.timestamp
      })
      return await consumeStream(sessionId, requestId, source, options)
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
    useSessionStore().markRead(sessionId)
  }

  function clearMessages(sessionId = activeSessionId.value) {
    if (!sessionId) {
      messages.value = []
      return
    }
    clearReconnectTimer(sessionId)
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

    const pendingMessage = getLoadingMessage(sessionId)
    if (!pendingMessage) return false

    await chatApi.cancelStream(sessionId)
    clearReconnectTimer(sessionId)
    setPendingCount(sessionId, 0)
    const stoppedMessage = buildStoppedMessage(pendingMessage)
    finalizeSessionMessage(sessionId, pendingMessage.requestId, stoppedMessage)
    syncSessionAfterReply(sessionId, stoppedMessage)
    return true
  }

  return {
    messages,
    loading,
    activeSessionId,
    isSessionPending,
    fetchHistory,
    sendMessage,
    continueMessage,
    setActiveSession,
    clearMessages,
    cancelActiveRequest
  }
})
