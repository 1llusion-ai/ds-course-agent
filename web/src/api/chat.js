import client from './client'

export const chatApi = {
  send: (data) => client.post('/chat/send', data, { timeout: 600000 }),
  getHistory: (sessionId) => client.get(`/chat/history/${sessionId}`),
  clearHistory: (sessionId) => client.delete(`/chat/history/${sessionId}`),
  sendStream: (data) => {
    const params = new URLSearchParams(data)
    return new EventSource(`/api/chat/send/stream?${params}`, { withCredentials: true })
  }
}
