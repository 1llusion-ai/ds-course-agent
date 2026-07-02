import client from './client'
import { DEFAULT_STUDENT_ID } from '../config'

export const sessionsApi = {
  create: (data) => client.post('/sessions', { ...data, student_id: data.student_id || DEFAULT_STUDENT_ID }),
  list: (studentId = DEFAULT_STUDENT_ID) =>
    client.get(`/sessions?student_id=${studentId}`),
  get: (id, studentId = DEFAULT_STUDENT_ID) => client.get(`/sessions/${id}?student_id=${studentId}`),
  update: (id, data) => client.patch(`/sessions/${id}`, data),
  delete: (id, studentId = DEFAULT_STUDENT_ID) => client.delete(`/sessions/${id}?student_id=${studentId}`)
}
