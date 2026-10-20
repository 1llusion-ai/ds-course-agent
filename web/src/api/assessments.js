import client from './client'

export const assessmentsApi = {
  preparations: (courseId) => client.get('/assessments/preparations', {
    params: { course_id: courseId }
  }),
  retryPreparation: (preparationId, courseId) => client.post(`/assessments/preparations/${preparationId}/retry`, null, {
    params: { course_id: courseId }
  }),
  list: (statuses = ['ready', 'in_progress'], courseId) =>
    client.get('/assessments', { params: { status: statuses.join(','), course_id: courseId } }),
  open: (assessmentId, courseId) => client.post(`/assessments/${assessmentId}/open`, null, {
    params: { course_id: courseId }
  }),
  get: (assessmentId, courseId) => client.get(`/assessments/${assessmentId}`, {
    params: { course_id: courseId }
  }),
  submit: (assessmentId, answers, courseId) => client.post(`/assessments/${assessmentId}/submit`, { answers }, {
    params: { course_id: courseId }
  }),
  result: (assessmentId, courseId) => client.get(`/assessments/${assessmentId}/result`, {
    params: { course_id: courseId }
  })
}
