import client from './client'

function redirectToLogin() {
  if (typeof window === 'undefined') {
    return
  }

  window.dispatchEvent(new CustomEvent('auth:unauthorized'))
  const { pathname, search, hash } = window.location
  if (pathname === '/login') {
    return
  }
  const redirect = `${pathname}${search}${hash}`
  window.location.assign(`/login?redirect=${encodeURIComponent(redirect)}`)
}

function dispatchSseFrame(target, frame) {
  const dataLines = frame
    .split('\n')
    .filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).replace(/^ /, ''))

  if (!dataLines.length) {
    return
  }

  const data = dataLines.join('\n')
  target.onmessage?.({ data })
}

function createFetchSseStream(url, { method = 'GET', data } = {}) {
  const controller = new AbortController()
  let closedByClient = false
  const stream = {
    onmessage: null,
    onerror: null,
    close() {
      closedByClient = true
      controller.abort()
    }
  }

  const consume = async () => {
    try {
      const headers = {
        Accept: 'text/event-stream'
      }
      const request = {
        method,
        credentials: 'include',
        headers,
        signal: controller.signal
      }
      if (data !== undefined) {
        headers['Content-Type'] = 'application/json'
        request.body = JSON.stringify(data)
      }

      const response = await fetch(url, request)

      if (!response.ok) {
        if (response.status === 401) {
          redirectToLogin()
        }
        throw new Error(`stream request failed with status ${response.status}`)
      }

      if (!response.body) {
        throw new Error('stream response body is not readable')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const drainFrames = () => {
        buffer = buffer.replace(/\r\n/g, '\n')
        let separatorIndex = buffer.indexOf('\n\n')
        while (separatorIndex !== -1) {
          const frame = buffer.slice(0, separatorIndex)
          buffer = buffer.slice(separatorIndex + 2)
          dispatchSseFrame(stream, frame)
          separatorIndex = buffer.indexOf('\n\n')
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }
        buffer += decoder.decode(value, { stream: true })
        drainFrames()
      }

      buffer += decoder.decode()
      if (buffer.trim()) {
        dispatchSseFrame(stream, buffer)
      }
      if (!closedByClient) {
        throw new Error('stream closed before final event')
      }
    } catch (error) {
      if (controller.signal.aborted) {
        return
      }
      stream.onerror?.(error)
    }
  }

  consume()
  return stream
}

export const chatApi = {
  send: (data) => client.post('/chat/send', data, { timeout: 600000 }),
  getHistory: (sessionId) => client.get(`/chat/history/${sessionId}`),
  clearHistory: (sessionId) => client.delete(`/chat/history/${sessionId}`),
  cancelStream: (sessionId) => client.post(`/chat/cancel/${sessionId}`),
  sendStream: (data) => createFetchSseStream('/api/chat/send/stream', { method: 'POST', data }),
  continueStream: (data) => createFetchSseStream('/api/chat/continue/stream', { method: 'POST', data }),
  resumeStream: (sessionId) => createFetchSseStream(`/api/chat/resume/${sessionId}`)
}
