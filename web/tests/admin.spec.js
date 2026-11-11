import { expect, test } from '@playwright/test'
import { mockDefaultCourse } from './helpers/courses'

const baseUser = {
  id: 2,
  username: 'alice',
  student_id: 'alice',
  display_name: 'Alice',
  role: 'student',
  status: 'active',
  created_at: '2026-11-01T02:00:00Z',
  updated_at: '2026-11-01T02:00:00Z',
  last_login_at: null,
  registration_source: 'invite',
  invite_name: '秋季一班',
  last_learning_at: '2026-11-04T06:00:00Z',
  questions: 12,
  submissions: 3
}
const usage = {
  active_users: 8,
  questions: 42,
  sessions: 12,
  assessments_assigned: 10,
  assessments_submitted: 6,
  completion_rate: 0.6,
  accuracy: 0.8,
  answers_completed: 40,
  answers_stopped: 1,
  answers_error: 1
}
const statistics = {
  start: '2026-10-07',
  end: '2026-11-05',
  timezone: 'Asia/Shanghai',
  as_of: '2026-11-05T02:00:00Z',
  coverage_note: '基于已保存记录统计',
  accounts: { total: 24, active: 23, disabled: 1, new_users: 4, roles: { student: 22, observer: 1, admin: 1 } },
  usage,
  previous: {
    start: '2026-09-07',
    end: '2026-10-06',
    active_users: 6,
    new_users: 2,
    questions: 30,
    assessments_submitted: 5,
    completion_rate: 0.5
  },
  daily: [
    { date: '2026-11-04', new_users: 1, active_users: 3, questions: 15, submissions: 2 },
    { date: '2026-11-05', new_users: 3, active_users: 5, questions: 27, submissions: 4 }
  ],
  courses: [{ course_id: 'data-science-intro', display_name: '数据科学导论', ...usage }],
  sources: [{ name: '秋季一班', registered_users: 4, active_users: 3 }]
}
const signals = {
  capacity: { max_users: 60, total_users: 55, remaining: 5 },
  invitations: { total: 3, expiring: 2, exhausted: 1 },
  answers: { days: 7, errors: 2, previous_errors: 1, completed: 30 }
}
const invitation = {
  id: 1,
  name: '秋季一班',
  note: '班级注册',
  code_hint: 'abcd…1234',
  expires_at: null,
  max_uses: 60,
  used_count: 12,
  enabled: true,
  status: 'active',
  created_at: '2026-11-01T02:00:00Z'
}

async function mockAuth(page, role = 'admin') {
  await mockDefaultCourse(page)
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({ json: { student_id: 'manager', display_name: '课程管理员', role } })
  )
  await page.route('**/api/sessions?**', (route) => route.fulfill({ json: { sessions: [] } }))
  await page.route('**/api/profile/summary?**', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/admin/statistics?**', (route) => route.fulfill({ json: statistics }))
  await page.route('**/api/admin/signals**', (route) => route.fulfill({ json: signals }))
}

test('admin overview matches shared theme and remains usable on mobile', async ({ page }) => {
  await mockAuth(page)
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '数据概览' })).toBeVisible()
  await expect(page.getByRole('link', { name: '注册与邀请码' })).toBeVisible()
  await expect(page.getByText('60.0%', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('23 / 1', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '待关注' })).toBeVisible()
  await expect(page.getByText('2 个邀请码将在 7 天内过期。')).toBeVisible()
  await expect(page.getByText('全站账号容量仅剩 5 个名额（已用 55/60）。')).toBeVisible()
  await expect(page.getByText('较上一周期 ↑ 40%')).toBeVisible()
  await expect(page.getByText('较上一周期 ↑ 10 个百分点')).toBeVisible()
  await page.screenshot({ path: '../var/artifacts/playwright/admin-overview-light.png', fullPage: true })
  await page.getByRole('button', { name: '切换深色模式' }).click()
  await expect(page.locator('html')).toHaveClass(/theme-dark/)
  await expect(page.locator('.admin-shell')).toHaveCSS('background-color', 'rgb(33, 33, 33)')
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/theme-dark/)
  await page.locator('.admin-brand__logo').evaluate((image) => image.decode())
  await page.screenshot({ path: '../var/artifacts/playwright/admin-overview-dark.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: '数据概览' })).toBeInViewport()
  expect(await page.locator('.admin-workspace').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
  await page.screenshot({ path: '../var/artifacts/playwright/admin-overview-mobile.png', fullPage: true })
  expect(errors).toEqual([])
})

test('observer can view statistics but cannot enter account management', async ({ page }) => {
  await mockAuth(page, 'observer')
  let userRequests = 0
  await page.route('**/api/admin/users**', (route) => {
    userRequests++
    return route.fulfill({ json: { items: [] } })
  })
  await page.goto('/admin/users')
  await expect(page).toHaveURL(/\/admin$/)
  await expect(page.getByRole('link', { name: '账号管理' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '注册与邀请码' })).toHaveCount(0)
  await page.getByRole('link', { name: '统计分析', exact: true }).click()
  await expect(page.getByRole('heading', { name: '统计分析' })).toBeVisible()
  expect(userRequests).toBe(0)
})

test('student cannot enter management pages or see the entry', async ({ page }) => {
  await mockAuth(page, 'student')
  await page.goto('/admin/registration')
  await expect(page).toHaveURL(/\/chat$/)
  await page.goto('/settings')
  await expect(page.getByRole('link', { name: /进入管理台/ })).toHaveCount(0)
})

test('account filters, pagination and permission changes send explicit payloads', async ({ page }) => {
  await mockAuth(page)
  let user = { ...baseUser }
  const requests = []
  let patch
  await page.route(/\/api\/admin\/users\?/, (route) => {
    requests.push(new URL(route.request().url()).searchParams)
    return route.fulfill({
      json: { items: [user], total: 21, page: Number(requests.at(-1).get('page')), page_size: 20 }
    })
  })
  await page.route('**/api/admin/users/2', (route) => {
    if (route.request().method() === 'PATCH') {
      patch = route.request().postDataJSON()
      user = { ...user, ...patch }
      return route.fulfill({ json: user })
    }
    return route.fulfill({ json: { user, courses: [] } })
  })
  await page.goto('/admin/users')
  await page.getByLabel('搜索账号').fill('alice')
  await page.getByRole('combobox', { name: '角色', exact: true }).selectOption('student')
  await page.getByRole('button', { name: '查询', exact: true }).click()
  await expect.poll(() => requests.at(-1)?.get('q')).toBe('alice')
  await page.getByRole('button', { name: '下一页' }).click()
  await expect.poll(() => requests.at(-1)?.get('page')).toBe('2')
  await expect(page.getByRole('link', { name: '查看详情' })).toBeVisible()
  await page.screenshot({ path: '../var/artifacts/playwright/admin-users.png', fullPage: true })
  await page.getByRole('link', { name: '查看详情' }).click()
  await expect(page.getByRole('heading', { name: 'Alice', exact: true })).toBeVisible()
  await page.getByLabel('账号角色').selectOption('observer')
  await page.getByRole('button', { name: '保存修改' }).click()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect.poll(() => patch).toEqual({ display_name: 'Alice', role: 'observer' })
  await expect(page.getByText('账号信息已更新。')).toBeVisible()
})

test('password mismatch prevents user creation and reset request', async ({ page }) => {
  await mockAuth(page)
  await page.route('**/api/admin/users?**', (route) =>
    route.fulfill({ json: { items: [baseUser], total: 1, page: 1, page_size: 20 } })
  )
  await page.route('**/api/admin/users/2', (route) => route.fulfill({ json: { user: baseUser, courses: [] } }))
  let writes = 0
  await page.route('**/api/admin/users', (route) => {
    writes++
    return route.fulfill({ json: baseUser })
  })
  await page.route('**/api/admin/users/2/reset-password', (route) => {
    writes++
    return route.fulfill({ json: { ok: true } })
  })
  await page.goto('/admin/users')
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.getByLabel('用户名', { exact: true }).fill('new-user')
  await page.getByLabel('显示名称', { exact: true }).fill('新同学')
  await page.getByLabel('登录密码', { exact: true }).fill('a-password')
  await page.getByLabel('确认密码', { exact: true }).fill('different-password')
  await page.getByRole('button', { name: '确认创建' }).click()
  await expect(page.getByText('两次输入的密码不一致。')).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('link', { name: '查看详情' }).click()
  await page.getByRole('button', { name: '重置密码', exact: true }).click()
  await page.getByLabel('新密码', { exact: true }).fill('a-password')
  await page.getByLabel('确认新密码', { exact: true }).fill('different-password')
  await page.getByRole('button', { name: '确认重置' }).click()
  await expect(page.getByText('两次输入的密码不一致。')).toBeVisible()
  expect(writes).toBe(0)
})

test('invitation is shown once, policy is editable and usage is linked to accounts', async ({ page }) => {
  await mockAuth(page)
  let policy = { mode: 'invite', max_users: 60, total_users: 12, remaining_capacity: 48 }
  let policyWrite
  let inviteWrite
  await page.route('**/api/admin/registration-policy', (route) => {
    if (route.request().method() === 'PUT') {
      policyWrite = route.request().postDataJSON()
      policy = { ...policy, ...policyWrite }
    }
    return route.fulfill({ json: policy })
  })
  await page.route('**/api/admin/invitations?**', (route) =>
    route.fulfill({ json: { items: [invitation], total: 1, page: 1, page_size: 20 } })
  )
  await page.route('**/api/admin/invitations', (route) => {
    inviteWrite = route.request().postDataJSON()
    return route.fulfill({ json: { invitation, code: 'one-time-secret-code' } })
  })
  await page.route('**/api/admin/invitations/1/uses?**', (route) =>
    route.fulfill({
      json: {
        items: [{ user_id: 2, username: 'alice', display_name: 'Alice', registered_at: baseUser.created_at }],
        total: 1,
        page: 1,
        page_size: 20
      }
    })
  )
  await page.goto('/admin/registration')
  await expect(page.getByRole('heading', { name: '邀请码', exact: true })).toBeVisible()
  await page.screenshot({ path: '../var/artifacts/playwright/admin-registration.png', fullPage: true })
  await page.getByLabel('注册方式').selectOption('closed')
  await page.getByRole('button', { name: '保存注册设置', exact: true }).click()
  await page.getByRole('button', { name: '确认保存', exact: true }).click()
  await expect.poll(() => policyWrite).toEqual({ mode: 'closed', max_users: 60 })
  await page.getByRole('button', { name: '创建邀请码', exact: true }).click()
  await page.getByLabel('名称', { exact: true }).fill('二班')
  await page.getByLabel('使用次数上限').fill('30')
  await page.getByRole('button', { name: '生成邀请码' }).click()
  await expect.poll(() => inviteWrite).toEqual({ name: '二班', note: '', expires_at: null, max_uses: 30 })
  await expect(page.getByTestId('created-invitation-code')).toHaveText('one-time-secret-code')
  await page.getByRole('button', { name: '已保存，关闭' }).click()
  await expect(page.getByText('one-time-secret-code')).toHaveCount(0)
  await page.getByRole('button', { name: '使用记录', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Alice', exact: true })).toHaveAttribute('href', '/admin/users/2')
})

test('statistics validates dates and export uses the displayed filters', async ({ page }) => {
  await mockAuth(page)
  let query
  let exportQuery
  await page.route('**/api/admin/statistics?**', (route) => {
    query = new URL(route.request().url()).searchParams
    return route.fulfill({ json: { ...statistics, start: query.get('start'), end: query.get('end') } })
  })
  await page.route('**/api/admin/statistics/export?**', (route) => {
    exportQuery = new URL(route.request().url()).searchParams
    return route.fulfill({ body: '日期,提问量\n2026-11-01,3', contentType: 'text/csv' })
  })
  await page.goto('/admin/statistics')
  await page.getByLabel('时间范围').selectOption('custom')
  await page.getByLabel('开始日期').fill('2026-11-05')
  await page.getByLabel('结束日期').fill('2026-11-01')
  await page.getByRole('button', { name: '应用筛选' }).click()
  await expect(page.getByRole('alert')).toContainText('开始日期不能晚于结束日期')
  await page.getByLabel('开始日期').fill('2026-11-01')
  await page.getByLabel('结束日期').fill('2026-11-05')
  await page.getByRole('button', { name: '应用筛选' }).click()
  await expect.poll(() => query?.get('start')).toBe('2026-11-01')
  await page.getByLabel('开始日期').fill('2026-10-01')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出汇总 CSV' }).click()
  await download
  expect(exportQuery.get('start')).toBe('2026-11-01')
  expect(exportQuery.get('end')).toBe('2026-11-05')
})

test('closed registration hides form and policy failure can be retried', async ({ page }) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({ status: 401, json: { detail: '未登录' } }))
  let failed = true
  await page.route('**/api/auth/registration-policy', (route) =>
    failed
      ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
      : route.fulfill({ json: { mode: 'closed', registration_open: false, invite_required: false } })
  )
  await page.goto('/register')
  await expect(page.getByText('暂时无法加载注册设置，请重试。')).toBeVisible()
  await expect(page.locator('#register-username')).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByText('当前暂未开放新账号注册')).toBeVisible()
  await expect(page.locator('#register-username')).toHaveCount(0)
})

test('last administrator error remains visible without pretending the account changed', async ({ page }) => {
  await mockAuth(page)
  const user = { ...baseUser, role: 'admin' }
  await page.route('**/api/admin/users/2', (route) =>
    route.request().method() === 'PATCH'
      ? route.fulfill({ status: 409, json: { detail: '不能停用最后一名有效管理员。' } })
      : route.fulfill({ json: { user, courses: [] } })
  )
  await page.goto('/admin/users/2')
  await page.getByRole('button', { name: '停用账号', exact: true }).click()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('不能停用最后一名有效管理员。')
  await expect(page.getByText('正常', { exact: true })).toBeVisible()
})

test('revoking own sessions returns the administrator to login', async ({ page }) => {
  await mockAuth(page)
  let revoked = false
  await page.route('**/api/auth/me', (route) =>
    revoked
      ? route.fulfill({ status: 401, json: { detail: '登录已失效' } })
      : route.fulfill({ json: { student_id: 'manager', display_name: '课程管理员', role: 'admin' } })
  )
  await page.route('**/api/admin/users/1', (route) =>
    route.fulfill({
      json: { user: { ...baseUser, id: 1, student_id: 'manager', username: 'manager', role: 'admin' }, courses: [] }
    })
  )
  await page.route('**/api/admin/users/1/revoke-sessions', (route) => {
    revoked = true
    return route.fulfill({ json: { ok: true } })
  })
  await page.goto('/admin/users/1')
  await page.getByRole('button', { name: '撤销所有登录', exact: true }).click()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
})

test('audit shows human readable actions and before-after details', async ({ page }) => {
  await mockAuth(page)
  await page.route('**/api/admin/audit?**', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 1,
            actor: 'manager',
            action: 'account.update',
            target: 'alice',
            created_at: '2026-11-05T02:00:00Z',
            before: { role: 'student' },
            after: { role: 'observer' }
          }
        ],
        total: 1,
        page: 1,
        page_size: 20
      }
    })
  )
  await page.goto('/admin/audit')
  await expect(page.getByText('修改账号', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看变更' }).click()
  await expect(page.locator('.admin-audit-changes')).toContainText('学生')
  await expect(page.locator('.admin-audit-changes')).toContainText('统计查看者')
})

for (const destination of ['/admin', '/admin/users?role=student']) {
  test(`login returns administrator to ${destination}`, async ({ page }) => {
    await mockAuth(page)
    let signedIn = false
    const admin = { student_id: 'manager', display_name: '课程管理员', role: 'admin' }
    await page.route('**/api/auth/me', (route) =>
      signedIn ? route.fulfill({ json: admin }) : route.fulfill({ status: 401, json: { detail: '未登录' } })
    )
    await page.route('**/api/auth/login', (route) => {
      signedIn = true
      return route.fulfill({ json: admin })
    })
    await page.route('**/api/admin/users?**', (route) =>
      route.fulfill({ json: { items: [baseUser], total: 1, page: 1, page_size: 20 } })
    )
    await page.goto(`/login?redirect=${encodeURIComponent(destination)}`)
    await page.locator('#login-username').fill('manager')
    await page.locator('#login-password').fill('correct-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page).toHaveURL(`http://127.0.0.1:4173${destination}`)
    await expect(
      page.getByRole('heading', { name: destination === '/admin' ? '数据概览' : '账号管理', exact: true })
    ).toBeVisible()
  })
}

for (const destination of [
  'https://external.example/admin',
  '//external.example/admin',
  '/\\external.example/admin',
  '/admin/../../login'
]) {
  test(`login rejects unsafe redirect ${JSON.stringify(destination)}`, async ({ page }) => {
    await mockAuth(page, 'student')
    await page.route('**/api/auth/me', (route) => route.fulfill({ status: 401, json: { detail: '未登录' } }))
    await page.route('**/api/auth/login', (route) =>
      route.fulfill({ json: { student_id: 'alice', display_name: 'Alice', role: 'student' } })
    )
    await page.goto(`/login?redirect=${encodeURIComponent(destination)}`)
    await page.locator('#login-username').fill('alice')
    await page.locator('#login-password').fill('correct-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page).toHaveURL('http://127.0.0.1:4173/chat')
  })
}
