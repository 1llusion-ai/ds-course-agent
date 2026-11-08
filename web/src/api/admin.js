import client from './client'

export const adminApi = {
  users: (params) => client.get('/admin/users', { params }),
  user: (id) => client.get(`/admin/users/${id}`),
  createUser: (data) => client.post('/admin/users', data),
  updateUser: (id, data) => client.patch(`/admin/users/${id}`, data),
  resetPassword: (id, password) => client.post(`/admin/users/${id}/reset-password`, { password }),
  revokeSessions: (id) => client.post(`/admin/users/${id}/revoke-sessions`, {}),
  registrationPolicy: () => client.get('/admin/registration-policy'),
  updateRegistrationPolicy: (data) => client.put('/admin/registration-policy', data),
  invitations: (params) => client.get('/admin/invitations', { params }),
  createInvitation: (data) => client.post('/admin/invitations', data),
  updateInvitation: (id, data) => client.patch(`/admin/invitations/${id}`, data),
  invitationUses: (id, params) => client.get(`/admin/invitations/${id}/uses`, { params }),
  audit: (params) => client.get('/admin/audit', { params }),
  statistics: (params) => client.get('/admin/statistics', { params }),
  exportStatistics: (params) => client.get('/admin/statistics/export', { params, responseType: 'blob' })
}
