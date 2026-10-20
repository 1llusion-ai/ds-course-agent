import client from './client'

export const profileApi = {
  getSummary: (courseId) => client.get('/profile/summary', { params: { course_id: courseId } }),
  getDetail: (days = 7, courseId) => client.get('/profile/detail', {
    params: { days, timezone_offset_minutes: new Date().getTimezoneOffset(), course_id: courseId }
  }),
  getConcept: (conceptId, courseId) => client.get(`/profile/concepts/${conceptId}`, {
    params: { course_id: courseId }
  }),
  aggregate: (courseId) => client.post('/profile/aggregate', null, { params: { course_id: courseId } }),
  resolveWeakSpot: (conceptId, courseId) =>
    client.post(`/profile/weak-spots/${encodeURIComponent(conceptId)}/resolve`, null, {
      params: { course_id: courseId }
    })
}
