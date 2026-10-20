import client from './client'

export const knowledgeMapApi = {
  get: (courseId) => client.get('/knowledge-map', { params: { course_id: courseId } })
}
