import client from './client'
import { DEFAULT_STUDENT_ID } from '../config'

export const chatApi = {
  send: (data) => client.post('/chat/send', {
    ...data,
    student_id: data.student_id || DEFAULT_STUDENT_ID
  }),
  getHistory: (sessionId, studentId = DEFAULT_STUDENT_ID) =>
    client.get(`/chat/history/${sessionId}?student_id=${studentId}`),
  clearHistory: (sessionId) => client.delete(`/chat/history/${sessionId}`),
  sendStream: (data) => {
    const params = new URLSearchParams({
      ...data,
      student_id: data.student_id || DEFAULT_STUDENT_ID
    })
    return new EventSource(`/api/chat/send/stream?${params}`)
  }
}
