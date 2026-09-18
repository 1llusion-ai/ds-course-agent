import client from './client'

export const authApi = {
  login: (credentials) => client.post('/auth/login', credentials, { skipAuthRedirect: true }),
  register: (credentials) => client.post('/auth/register', credentials, { skipAuthRedirect: true }),
  changePassword: (credentials) => client.post('/auth/change-password', credentials),
  logout: () => client.post('/auth/logout', {}, { skipAuthRedirect: true }),
  me: () => client.get('/auth/me', { skipAuthRedirect: true })
}
