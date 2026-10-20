import { expect, test } from '@playwright/test'

const DEFAULT_COURSE = 'data-science-intro'
const SECOND_COURSE = 'digital-literacy'
const FOURTH_COURSE = 'statistics'
const courses = [
  { course_id: DEFAULT_COURSE, display_name: '数据科学导论', is_ready: true },
  { course_id: SECOND_COURSE, display_name: '数字素养', is_ready: true },
  { course_id: FOURTH_COURSE, display_name: '统计学', is_ready: true }
]

function session(courseId) {
  return {
    id: 'shared-session',
    course_id: courseId,
    title: `${courseId} 会话`,
    created_at: '2026-10-20T00:00:00Z',
    updated_at: '2026-10-20T00:00:00Z',
    message_count: 1
  }
}

async function mockCourses(page) {
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'student', display_name: '测试学生' }
  }))
  await page.route('**/api/courses', route => route.fulfill({ json: { courses } }))
  await page.route('**/api/profile/summary?**', route => route.fulfill({ json: {} }))
  await page.route('**/api/sessions?**', route => {
    const courseId = new URL(route.request().url()).searchParams.get('course_id')
    return route.fulfill({ json: { sessions: [session(courseId)] } })
  })
}

test('switching courses isolates shared session IDs and ignores late history', async ({ page }) => {
  await mockCourses(page)
  let releaseLateHistory
  let secondCourseRequests = 0
  const historyCourses = []
  await page.route('**/api/chat/history/shared-session?**', async route => {
    const courseId = new URL(route.request().url()).searchParams.get('course_id')
    historyCourses.push(courseId)
    if (courseId === SECOND_COURSE && ++secondCourseRequests === 1) {
      await new Promise(resolve => { releaseLateHistory = resolve })
    }
    await route.fulfill({ json: {
      session_id: 'shared-session', course_id: courseId,
      messages: [{ role: 'assistant', content: `${courseId} 专属历史`, timestamp: '2026-10-20T00:00:00Z' }]
    } })
  })

  await page.goto('/chat/shared-session')
  const selector = page.getByRole('combobox', { name: '切换课程' })
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toBeVisible()
  await selector.selectOption(SECOND_COURSE)
  await expect(page).toHaveURL(/\/chat$/)
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toHaveCount(0)
  await page.locator('.session-title').filter({ hasText: `${SECOND_COURSE} 会话` }).click()
  await expect.poll(() => historyCourses.filter(id => id === SECOND_COURSE).length).toBe(1)

  await selector.selectOption(DEFAULT_COURSE)
  await expect(page).toHaveURL(/\/chat$/)
  await page.locator('.session-title').filter({ hasText: `${DEFAULT_COURSE} 会话` }).click()
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toBeVisible()
  releaseLateHistory()
  await expect(page.getByText(`${SECOND_COURSE} 专属历史`, { exact: true })).toHaveCount(0)

  await selector.selectOption(SECOND_COURSE)
  await page.locator('.session-title').filter({ hasText: `${SECOND_COURSE} 会话` }).click()
  await expect(page.getByText(`${SECOND_COURSE} 专属历史`, { exact: true })).toBeVisible()
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toHaveCount(0)
  expect(historyCourses).toEqual([DEFAULT_COURSE, SECOND_COURSE, DEFAULT_COURSE, SECOND_COURSE])
})

test('catalog additions appear automatically and ready courses can send', async ({ page }) => {
  await mockCourses(page)
  let streamPayload
  await page.route('**/api/sessions', route => {
    const data = route.request().postDataJSON()
    return route.fulfill({ json: session(data.course_id) })
  })
  await page.route('**/api/chat/history/shared-session?**', route => route.fulfill({ json: { messages: [] } }))
  await page.route('**/api/chat/send/stream', route => {
    streamPayload = route.request().postDataJSON()
    return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({
      type: 'final', message: { role: 'assistant', content: '统计学回答', timestamp: '2026-10-20T00:00:00Z' }
    })}\n\n` })
  })

  await page.goto('/chat')
  const selector = page.getByRole('combobox', { name: '切换课程' })
  await expect(selector.locator('option')).toHaveCount(3)
  await selector.selectOption(FOURTH_COURSE)
  await expect(page.locator('textarea')).toBeEnabled()
  await page.locator('textarea').fill('介绍统计推断')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('统计学回答', { exact: true })).toBeVisible()
  expect(streamPayload).toMatchObject({ session_id: 'shared-session', course_id: FOURTH_COURSE, message: '介绍统计推断' })
  await page.reload()
  await expect(selector).toHaveValue(FOURTH_COURSE)
})
