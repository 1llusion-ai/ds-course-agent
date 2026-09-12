let knowledgeMapPrefetchPromise

function canPrefetchKnowledgeMap() {
  if (typeof window === 'undefined') return false
  const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection
  if (!connection) return true
  if (connection.saveData) return false
  return !['slow-2g', '2g'].includes(connection.effectiveType)
}

export function prefetchKnowledgeMap() {
  if (!canPrefetchKnowledgeMap()) return Promise.resolve(false)
  if (!knowledgeMapPrefetchPromise) {
    knowledgeMapPrefetchPromise = Promise.all([
      import('../views/KnowledgeMapView.vue'),
      import('../components/KnowledgeMapCanvas.vue')
    ])
      .then(() => true)
      .catch(() => {
        knowledgeMapPrefetchPromise = undefined
        return false
      })
  }
  return knowledgeMapPrefetchPromise
}

export function scheduleKnowledgeMapPrefetch(delay = 6000) {
  if (!canPrefetchKnowledgeMap()) return () => {}

  let cancelled = false
  let delayTimer
  let idleCallbackId
  const start = () => {
    if (cancelled) return
    if ('requestIdleCallback' in window) {
      idleCallbackId = window.requestIdleCallback(
        () => { void prefetchKnowledgeMap() },
        { timeout: 4000 }
      )
      return
    }
    void prefetchKnowledgeMap()
  }

  delayTimer = window.setTimeout(start, delay)
  return () => {
    cancelled = true
    window.clearTimeout(delayTimer)
    if (idleCallbackId !== undefined && 'cancelIdleCallback' in window) {
      window.cancelIdleCallback(idleCallbackId)
    }
  }
}
