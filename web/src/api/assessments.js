import client from './client'

export const assessmentsApi = {
  preparations: () => client.get('/assessments/preparations'),
  retryPreparation: (preparationId) => client.post(`/assessments/preparations/${preparationId}/retry`),
  list: (statuses = ['ready', 'in_progress']) =>
    client.get('/assessments', { params: { status: statuses.join(',') } }),
  open: (assessmentId) => client.post(`/assessments/${assessmentId}/open`),
  get: (assessmentId) => client.get(`/assessments/${assessmentId}`),
  submit: (assessmentId, answers) => client.post(`/assessments/${assessmentId}/submit`, { answers }),
  result: (assessmentId) => client.get(`/assessments/${assessmentId}/result`)
}
