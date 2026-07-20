export function buildPendingMessage(requestId) {
  const startedAt = new Date().toISOString()
  return {
    role: 'assistant',
    content: '',
    timestamp: startedAt,
    isLoading: true,
    requestId,
    progress: null,
    progressEvents: [],
    generation_status: 'generating'
  }
}

export function buildActiveStreamMessage(sessionId, snapshot = {}) {
  const startedAt = snapshot.message_timestamp || snapshot.started_at || new Date().toISOString()
  const progressEvents = Array.isArray(snapshot.progress_events)
    ? snapshot.progress_events.map(normalizeProgressEvent)
    : []

  return {
    role: 'assistant',
    content: snapshot.content || '',
    timestamp: startedAt,
    isLoading: true,
    requestId: `active_stream_${sessionId}`,
    progress: snapshot.progress ? normalizeProgressEvent(snapshot.progress) : (progressEvents.at(-1) || null),
    progressEvents,
    stream_id: snapshot.stream_id || '',
    streamEventId: Number(snapshot.last_event_id || 0),
    generation_status: 'generating'
  }
}

export function buildErrorMessage(content, extra = {}) {
  return {
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
    isError: true,
    generation_status: 'error',
    ...extra
  }
}

export function buildStoppedMessage(message = {}) {
  return {
    ...message,
    isLoading: false,
    isError: false,
    generation_status: 'stopped',
    generation_error: null
  }
}

export function normalizeHistoryMessage(message = {}) {
  const generationStatus = message.generation_status || 'completed'
  return {
    ...message,
    isLoading: false,
    isError: generationStatus === 'error',
    generation_status: generationStatus
  }
}

export function normalizeProgressEvent(progress = {}) {
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

export function sourcesFromProgressDetails(details = {}) {
  const courseSources = Array.isArray(details?.sources)
    ? details.sources
      .filter(item => item && typeof item === 'object')
      .map(item => ({ ...item, source: item.source || 'course' }))
    : []
  const results = Array.isArray(details?.results) ? details.results : []
  const webSources = results
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

  return [...courseSources, ...webSources]
}

export function latestRouteFromProgress(events = []) {
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

export function mergeHistoryWithLocalProgress(history = [], localMessages = []) {
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
