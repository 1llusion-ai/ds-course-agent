import client from './client'

export const sessionsApi = {
  create: (data, courseId) => client.post('/sessions', {
    ...data,
    course_id: courseId || data?.course_id
  }),
  list: (courseId) => client.get('/sessions', { params: { course_id: courseId } }),
  get: (id, courseId) => client.get(`/sessions/${id}`, { params: { course_id: courseId } }),
  update: (id, data, courseId) => client.patch(`/sessions/${id}`, data, {
    params: { course_id: courseId }
  }),
  delete: (id, courseId) => client.delete(`/sessions/${id}`, {
    params: { course_id: courseId }
  })
}
