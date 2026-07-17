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

function createFetchSseStream(data) {
  const controller = new AbortController()
  const stream = {
    onmessage: null,
    onerror: null,
    close() {
      controller.abort()
    }
  }

  const consume = async () => {
    try {
      const response = await fetch('/api/chat/send/stream', {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'text/event-stream',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data),
        signal: controller.signal
      })

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
  sendStream: (data) => createFetchSseStream(data)
}
