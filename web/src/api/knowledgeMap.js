import client from './client'

export const knowledgeMapApi = {
  get: () => client.get('/knowledge-map')
}
