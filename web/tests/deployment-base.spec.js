import { expect, test } from '@playwright/test'

const base = process.env.VITE_APP_BASE_PATH || '/'
const app = route => `${base}${route}`

async function mockApplication(page, { signedIn = false, streamUnauthorized = false } = {}) {
  const paths = []
  let sessionCreated = false
  const session = { id: 'deployment-session', course_id: 'data-science-intro', title: '部署测试', message_count: 0, created_at: '2026-11-19T00:00:00Z', updated_at: '2026-11-19T00:00:00Z' }
  await page.route(url => url.pathname.startsWith(app('api/')), route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    paths.push(path)
    const endpoint = path.slice(path.indexOf('/api/') + 4)
    const user = { student_id: 'deployment-test', display_name: '部署测试', role: 'student' }
    if (endpoint === '/auth/me') return route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? user : { detail: 'not authenticated' } })
    if (endpoint === '/auth/login') { signedIn = true; return route.fulfill({ json: user }) }
    if (endpoint === '/auth/registration-policy') return route.fulfill({ json: { mode: 'invite', registration_open: true, invite_required: true } })
    if (endpoint === '/courses') return route.fulfill({ json: { courses: [{ course_id: 'data-science-intro', display_name: '数据科学导论', is_ready: true }] } })
    if (endpoint === '/sessions' && request.method() === 'POST') { sessionCreated = true; return route.fulfill({ json: session }) }
    if (endpoint === '/sessions') return route.fulfill({ json: { sessions: sessionCreated ? [session] : [] } })
    if (endpoint.startsWith('/chat/history/')) return route.fulfill({ json: { messages: [] } })
    if (endpoint === '/chat/send/stream') {
      if (streamUnauthorized) { signedIn = false; return route.fulfill({ status: 401, json: { detail: 'expired' } }) }
      return route.fulfill({ contentType: 'text/event-stream', body: 'data: ' + JSON.stringify({ type: 'final', message: { role: 'assistant', content: '子路径流式回答成功', timestamp: '2026-11-19T00:00:00Z' } }) + String.fromCharCode(10, 10) })
    }
    if (endpoint.startsWith('/assessments')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  return paths
}

test('deep links, login and registration retain the deployment prefix', async ({ page }) => {
  const paths = await mockApplication(page)
  await page.goto(app('settings?section=account'))
  await expect(page).toHaveURL(new RegExp(`${base}login\\?redirect=`))
  const logo = page.locator('.login-brand img')
  await expect(logo).toHaveJSProperty('complete', true)
  expect(await logo.getAttribute('src')).toBe(app('icon/thought_mark.png'))
  await page.getByRole('button', { name: /立即注册/ }).click()
  expect(new URL(page.url()).pathname).toBe(app('register'))
  await page.goto(app('login'))
  await page.locator('#login-username').fill('deployment-test')
  await page.locator('#login-password').fill('valid-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`${base}chat$`))
  expect(paths.every(path => path.startsWith(app('api/')))).toBe(true)
})

test('SSE sends and receives below the deployment prefix', async ({ page }) => {
  const paths = await mockApplication(page, { signedIn: true })
  await page.goto(app('chat'))
  await page.locator('textarea').fill('介绍课程')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('子路径流式回答成功', { exact: true })).toBeVisible()
  expect(paths).toContain(app('api/chat/send/stream'))
  expect(paths.every(path => path.startsWith(app('api/')))).toBe(true)
})

test('expired streaming authentication redirects within the deployment prefix', async ({ page }) => {
  await mockApplication(page, { signedIn: true, streamUnauthorized: true })
  await page.goto(app('chat'))
  await page.locator('textarea').fill('介绍课程')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page).toHaveURL(new RegExp(`${base}login\\?redirect=`))
  expect(new URL(page.url()).searchParams.get('redirect')).toMatch(/^\/chat/)
})
