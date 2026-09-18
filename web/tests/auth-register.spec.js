import { expect, test } from '@playwright/test'

test('login registration entry opens the form and successful registration enters chat', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'not authenticated' })
  }))
  await page.route('**/api/auth/register', route => route.fulfill({
    status: 201,
    contentType: 'application/json',
    json: { student_id: 'new_user', display_name: 'new_user' }
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: { sessions: [] } }))

  await page.goto('/login')
  await page.getByRole('button', { name: /立即注册/ }).click()
  await expect(page).toHaveURL(/\/register$/)
  await expect(page.getByRole('heading', { name: '创建账号' })).toBeVisible()
  await expect(page.locator('#register-username')).toBeFocused()

  await page.locator('#register-username').fill('new_user')
  await page.locator('#register-password').fill('correct-horse')
  await page.locator('#register-confirm-password').fill('correct-horse')
  await page.locator('#register-invite-code').fill('class-2026')
  const registerRequest = page.waitForRequest('**/api/auth/register')
  await page.getByRole('button', { name: '注册' }).click()

  expect((await registerRequest).postDataJSON()).toEqual({
    username: 'new_user',
    password: 'correct-horse',
    invite_code: 'class-2026'
  })
  await expect(page).toHaveURL(/\/chat$/)
})

test('duplicate username shows a clear conflict message', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'not authenticated' })
  }))
  await page.route('**/api/auth/register', route => route.fulfill({
    status: 409,
    contentType: 'application/json',
    json: { detail: '该用户名已存在' }
  }))

  await page.goto('/register')
  await page.locator('#register-username').fill('existing_user')
  await page.locator('#register-password').fill('correct-horse')
  await page.locator('#register-confirm-password').fill('correct-horse')
  await page.getByRole('button', { name: '注册' }).click()

  await expect(page.getByText('该用户名已被使用，请换一个试试。')).toBeVisible()
})

test('password mismatch shows a specific validation message', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'not authenticated' })
  }))
  await page.route('**/api/auth/register', route => route.fulfill({
    status: 201,
    contentType: 'application/json',
    json: { student_id: 'new_user', display_name: 'new_user' }
  }))

  await page.goto('/register')
  await page.locator('#register-username').fill('new_user')
  await page.locator('#register-password').fill('correct-horse')
  await page.locator('#register-confirm-password').fill('different-pass')
  await page.getByRole('button', { name: '注册' }).click()

  await expect(page.getByText('两次输入的密码不一致，请重新确认。')).toBeVisible()
  await expect(page).toHaveURL(/\/register$/)
})

test('invalid invite code shows a clear message', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'not authenticated' })
  }))
  await page.route('**/api/auth/register', route => route.fulfill({
    status: 403,
    contentType: 'application/json',
    json: { detail: '需要有效的班级邀请码才能注册。' }
  }))

  await page.goto('/register')
  await page.locator('#register-username').fill('new_user')
  await page.locator('#register-password').fill('correct-horse')
  await page.locator('#register-confirm-password').fill('correct-horse')
  await page.locator('#register-invite-code').fill('wrong-code')
  await page.getByRole('button', { name: '注册' }).click()

  await expect(page.getByText('请输入有效的班级邀请码，请向老师获取。')).toBeVisible()
  await expect(page).toHaveURL(/\/register$/)
})

test('registration capacity shows a clear message', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'not authenticated' })
  }))
  await page.route('**/api/auth/register', route => route.fulfill({
    status: 409,
    contentType: 'application/json',
    json: { detail: '本班级注册人数已达到上限，请联系管理员。' }
  }))

  await page.goto('/register')
  await page.locator('#register-username').fill('new_user')
  await page.locator('#register-password').fill('correct-horse')
  await page.locator('#register-confirm-password').fill('correct-horse')
  await page.locator('#register-invite-code').fill('class-2026')
  await page.getByRole('button', { name: '注册' }).click()

  await expect(page.getByText('本班级注册人数已达到上限，请联系管理员。')).toBeVisible()
  await expect(page).toHaveURL(/\/register$/)
})
