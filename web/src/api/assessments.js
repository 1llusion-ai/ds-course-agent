import client from './client'

export const assessmentsApi = {
  list: (statuses = ['ready', 'in_progress']) =>
    client.get('/assessments', { params: { status: statuses.join(',') } }),
  open: (assessmentId) => client.post(`/assessments/${assessmentId}/open`),
  get: (assessmentId) => client.get(`/assessments/${assessmentId}`),
  submit: (assessmentId, answers) => client.post(`/assessments/${assessmentId}/submit`, { answers }),
  result: (assessmentId) => client.get(`/assessments/${assessmentId}/result`)
}
