import client from './client'

export const DEFAULT_COURSE_ID = 'data-science-intro'

export const coursesApi = {
  list: () => client.get('/courses')
}
