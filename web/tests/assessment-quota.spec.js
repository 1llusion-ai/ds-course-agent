import { expect, test } from '@playwright/test'

test('assessment polling respects Retry-After after a quota response', async ({ page }) => {
  await page.addInitScript(() => {
    const originalSetTimeout = window.setTimeout.bind(window)
    window.setTimeout = (handler, timeout, ...args) => {
      const effectiveTimeout = timeout === 15_000 ? 50 : timeout === 20_000 ? 1_000 : timeout
      return originalSetTimeout(handler, effectiveTimeout, ...args)
    }
  })
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'student', display_name: '测试学生' }
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: { sessions: [] } }))
  await page.route('**/api/profile/summary', route => route.fulfill({ json: {} }))

  let preparationRequests = 0
  await page.route('**/api/assessments/preparations', route => {
    preparationRequests += 1
    if (preparationRequests === 1) {
      return route.fulfill({ json: [{
        id: 'preparation-1',
        display_name: '欠拟合',
        status: 'generating',
        session_id: null
      }] })
    }
    return route.fulfill({
      status: 429,
      headers: { 'Retry-After': '20' },
      json: { detail: '请求过于频繁，请稍后重试。' }
    })
  })
  await page.route('**/api/assessments?**', route => route.fulfill({ json: [] }))

  await page.goto('/assessments')
  await expect.poll(() => preparationRequests).toBe(2)

  await page.waitForTimeout(100)
  expect(preparationRequests).toBe(2)

  await expect.poll(() => preparationRequests, { timeout: 1_000 }).toBe(3)
})
