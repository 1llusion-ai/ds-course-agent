import { expect, test } from '@playwright/test'
import { mockDefaultCourse } from './helpers/courses'

const courseId = 'data-science-intro'
const timestamp = '2026-11-20T00:00:00Z'
const base = process.env.VITE_APP_BASE_PATH || '/'
const app = route => `${base}${route}`
const session = {
  id: 'quota-session', course_id: courseId, title: '容量测试', message_count: 0,
  created_at: timestamp, updated_at: timestamp
}

const busy = {
  status: 429,
  headers: { 'Retry-After': '15' },
  json: { detail: '当前生成请求较多，请稍后重试。' }
}

function streamReply(route, content) {
  const message = { role: 'assistant', content, timestamp }
  return route.fulfill({
    contentType: 'text/event-stream',
    body: `data: ${JSON.stringify({ type: 'final', message })}\n\n`
  })
}

async function mockChat(page, history = {}) {
  await mockDefaultCourse(page)
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'student', display_name: '测试学生' }
  }))
  await page.route('**/api/sessions?**', route => route.fulfill({ json: { sessions: [session] } }))
  await page.route('**/api/sessions/quota-session?**', route => route.fulfill({ json: session }))
  await page.route('**/api/profile/summary?**', route => route.fulfill({ json: {} }))
  await page.route('**/api/chat/history/quota-session?**', route => route.fulfill({
    json: { messages: [], ...history }
  }))
  await page.clock.install()
}

test('a rejected new question stays in the composer until the student retries', async ({ page }) => {
  await mockChat(page)
  let createdSessions = 0
  await page.route('**/api/sessions', route => {
    createdSessions += 1
    return route.fulfill({ json: session })
  })
  const requests = []
  await page.route('**/api/chat/send/stream', route => {
    requests.push(route.request().postDataJSON())
    return requests.length === 1 ? route.fulfill(busy) : streamReply(route, '课程回答')
  })

  await page.goto(app('chat'))
  const question = '请介绍课程中的聚类概念'
  const input = page.locator('textarea')
  const send = page.getByRole('button', { name: '发送消息' })
  await input.fill(question)
  await send.click()
  await expect(page.getByRole('status').filter({ hasText: /当前请求较多/ })).toBeVisible()
  await expect(page).toHaveURL(/\/chat\/quota-session$/)
  await expect(input).toHaveValue(question)
  await expect(page.getByText(question, { exact: true })).toHaveCount(0)
  await expect(send).toBeDisabled()
  await input.press('Enter')
  await page.clock.fastForward(5_000)
  await expect(send).toBeDisabled()
  expect(requests).toHaveLength(1)

  await page.clock.fastForward(15_000)
  await expect(send).toBeEnabled()
  expect(requests).toHaveLength(1)
  await send.click()
  await expect(page.getByText('课程回答', { exact: true })).toBeVisible()
  await expect(input).toHaveValue('')
  await expect(page.getByText(question, { exact: true })).toHaveCount(1)
  expect(createdSessions).toBe(1)
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
})

test('a rejected continuation preserves the stopped response and can retry after the HTTP date', async ({ page }) => {
  await mockChat(page, {
    messages: [{ role: 'assistant', content: '上一轮的部分回答', timestamp, generation_status: 'stopped' }]
  })
  const requests = []
  await page.route('**/api/chat/continue/stream', async route => {
    requests.push(route.request().postDataJSON())
    if (requests.length > 1) return streamReply(route, '完整回答')
    const deadline = await page.evaluate(() => new Date(Date.now() + 15_000).toUTCString())
    return route.fulfill({ ...busy, headers: { 'Retry-After': deadline } })
  })

  await page.goto(app('chat/quota-session'))
  const resume = page.getByRole('button', { name: '继续生成' })
  await resume.click()
  await expect(page.getByRole('status').filter({ hasText: /当前请求较多/ })).toBeVisible()
  await expect(page.getByText('上一轮的部分回答', { exact: true })).toBeVisible()
  await expect(resume).toBeDisabled()
  await page.clock.fastForward(5_000)
  await expect(resume).toBeDisabled()
  await page.clock.fastForward(15_000)
  await expect(resume).toBeEnabled()
  expect(requests).toHaveLength(1)
  await resume.click()
  await expect(page.getByText('完整回答', { exact: true })).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
})

test('a throttled resume waits before checking history and reconnects without a new POST', async ({ page }) => {
  const activeStream = { stream_id: 'generation', content: '正在生成', message_timestamp: timestamp }
  await mockChat(page, { active_stream: activeStream })
  let resumeRequests = 0
  let sendRequests = 0
  await page.route('**/api/chat/send/stream', route => {
    sendRequests += 1
    return route.fulfill(busy)
  })
  await page.route('**/api/chat/resume/quota-session?**', route => {
    resumeRequests += 1
    return resumeRequests === 1 ? route.fulfill(busy) : streamReply(route, '恢复后的回答')
  })

  await page.goto(app('chat/quota-session'))
  await expect.poll(() => resumeRequests).toBe(1)
  await expect(page.getByText('正在生成', { exact: true })).toBeVisible()
  await page.clock.fastForward(5_000)
  expect(resumeRequests).toBe(1)
  await page.clock.fastForward(15_000)
  await expect(page.getByText('恢复后的回答', { exact: true })).toBeVisible()
  expect(resumeRequests).toBe(2)
  expect(sendRequests).toBe(0)
})
