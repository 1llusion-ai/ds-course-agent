import { expect, test } from '@playwright/test'

test('a rejected continuation keeps the stopped question and partial answer visible', async ({ page }) => {
  const userQuestion = '请继续解释交叉验证为什么能估计泛化误差。'
  const partialAnswer = '交叉验证会把数据划分为多个折，并轮流使用验证折。'

  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (url.pathname === '/api/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ student_id: 'student-a', display_name: '学生甲' }) })
      return
    }
    if (url.pathname === '/api/sessions') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [{ id: 'session-1', title: '交叉验证复习', student_id: 'student-a', message_count: 2, updated_at: '2026-09-12T09:00:00Z' }] })
      })
      return
    }
    if (url.pathname === '/api/chat/history/session-1') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'session-1',
          messages: [
            { role: 'user', content: userQuestion, timestamp: '2026-09-12T09:00:00.000Z' },
            { role: 'assistant', content: partialAnswer, timestamp: '2026-09-12T09:00:01.000Z', generation_status: 'stopped' }
          ],
          active_stream: null
        })
      })
      return
    }
    if (url.pathname === '/api/chat/continue/stream') {
      await route.fulfill({ status: 429, headers: { 'Retry-After': '5' }, contentType: 'application/json', body: JSON.stringify({ detail: '当前生成任务较多，请稍后重试' }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  })

  await page.goto('/chat/session-1')
  await expect(page.getByText(userQuestion)).toBeVisible()
  await expect(page.getByText(partialAnswer)).toBeVisible()
  await page.getByRole('button', { name: '继续生成' }).click()

  await expect(page.getByText(userQuestion)).toBeVisible()
  await expect(page.getByText(partialAnswer)).toBeVisible()
  await expect(page.getByRole('button', { name: '继续生成' })).toBeVisible()
})
