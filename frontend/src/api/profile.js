import client from './client'

export const profileApi = {
  getSummary: (studentId) => client.get(`/profile/summary/${studentId}`),
  getDetail: (studentId) => client.get(`/profile/detail/${studentId}`),
  getConcept: (conceptId) => client.get(`/profile/concepts/${conceptId}`),
  aggregate: (studentId) => client.post(`/profile/aggregate/${studentId}`),
  resolveWeakSpot: (studentId, conceptId) =>
    client.post(`/profile/weak-spots/${encodeURIComponent(studentId)}/${encodeURIComponent(conceptId)}/resolve`)
}
