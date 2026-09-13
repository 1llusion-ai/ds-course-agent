import client from './client'

export const profileApi = {
  getSummary: () => client.get('/profile/summary'),
  getDetail: (days = 7) => client.get('/profile/detail', { params: { days } }),
  getConcept: (conceptId) => client.get(`/profile/concepts/${conceptId}`),
  aggregate: () => client.post('/profile/aggregate'),
  resolveWeakSpot: (conceptId) =>
    client.post(`/profile/weak-spots/${encodeURIComponent(conceptId)}/resolve`)
}
