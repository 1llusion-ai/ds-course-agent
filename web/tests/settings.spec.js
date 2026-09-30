import { expect, test } from '@playwright/test'

test('settings lets an authenticated learner change password and toggle theme', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'alice', display_name: 'alice' }
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: { sessions: [] } }))
  await page.route('**/api/profile/summary', route => route.fulfill({ json: {} }))

  let requestPayload
  await page.route('**/api/auth/change-password', async route => {
    requestPayload = JSON.parse(route.request().postData())
    await route.fulfill({
      json: { student_id: 'alice', display_name: 'alice' }
    })
  })

  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '设置' })).toBeVisible()
  await expect(page.getByText('alice', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.el-dialog')).toBeHidden()

  await page.getByRole('button', { name: '更改' }).click()
  await expect(page.locator('.el-dialog')).toBeVisible()

  await page.locator('#settings-current-password').fill('old-password')
  await page.locator('#settings-new-password').fill('new-password')
  await page.locator('#settings-confirm-password').fill('new-password')
  await page.getByRole('button', { name: '更新密码' }).click()

  await expect.poll(() => requestPayload).toEqual({
    current_password: 'old-password',
    new_password: 'new-password'
  })
  await expect(page.getByText('密码已修改成功。')).toBeVisible()
  await page.locator('.el-dialog__headerbtn').click()
  await expect(page.locator('.el-dialog')).toBeHidden()

  const themeSwitch = page.locator('.el-switch')
  await themeSwitch.click()
  await expect(page.locator('html')).toHaveClass(/theme-dark/)
  await expect(page.locator('.settings-page')).toHaveCSS('background-color', 'rgb(33, 33, 33)')
  await expect(page.locator('.settings-list').nth(2)).toHaveCSS('background-color', 'rgb(42, 42, 42)')
  await expect(page.locator('.settings-row__copy strong').nth(2)).toHaveCSS('color', 'rgb(236, 236, 236)')
})

test('settings gives a specific message when new passwords differ', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'alice', display_name: 'alice' }
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: { sessions: [] } }))
  await page.route('**/api/profile/summary', route => route.fulfill({ json: {} }))

  await page.goto('/settings')
  await page.getByRole('button', { name: '更改' }).click()
  await page.locator('#settings-current-password').fill('old-password')
  await page.locator('#settings-new-password').fill('new-password')
  await page.locator('#settings-confirm-password').fill('different-pass')
  await page.getByRole('button', { name: '更新密码' }).click()

  await expect(page.getByText('两次输入的新密码不一致，请重新确认。')).toBeVisible()
})
