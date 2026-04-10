import client from './client'

export const profileApi = {
  getSummary: (studentId) => client.get(`/profile/summary/${studentId}`),
  getDetail: (studentId) => client.get(`/profile/detail/${studentId}`),
  aggregate: (studentId) => client.post(`/profile/aggregate/${studentId}`)
}
