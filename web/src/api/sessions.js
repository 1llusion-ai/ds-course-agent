import client from './client'

export const sessionsApi = {
  create: (data) => client.post('/sessions', data),
  list: () => client.get('/sessions'),
  get: (id) => client.get(`/sessions/${id}`),
  update: (id, data) => client.patch(`/sessions/${id}`, data),
  delete: (id) => client.delete(`/sessions/${id}`)
}
