import client from './client'

export const profileApi = {
  getSummary: () => client.get('/profile/summary'),
  getDetail: () => client.get('/profile/detail'),
  getConcept: (conceptId) => client.get(`/profile/concepts/${conceptId}`),
  aggregate: () => client.post('/profile/aggregate'),
  resolveWeakSpot: (conceptId) =>
    client.post(`/profile/weak-spots/${encodeURIComponent(conceptId)}/resolve`)
}
