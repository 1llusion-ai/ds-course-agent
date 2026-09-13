import { expect, test } from '@playwright/test'

const graph = {
  chapters: [
    { chapter: '第1章', title: '数据科学基础' }
  ],
  nodes: [
    {
      canonical_id: 'data_science',
      display_name: '数据科学',
      aliases: [],
      node_type: 'kc',
      chapter: '第1章',
      section: '1.1',
      summary: '从数据中提取知识的方法体系。',
      learning_state: 'unobserved',
      learning_points: []
    },
    {
      canonical_id: 'data_analysis',
      display_name: '数据分析',
      aliases: [],
      node_type: 'kc',
      chapter: '第1章',
      section: '1.2',
      summary: '检查、清理和解释数据的过程。',
      learning_state: 'unobserved',
      learning_points: []
    }
  ],
  edges: [
    { source: 'data_science', target: 'data_analysis', relation_type: 'related_to' }
  ]
}

async function stageWidth(page) {
  return page.locator('.map-stage').evaluate(element => element.getBoundingClientRect().width)
}

test('directory overlays the graph while the KC inspector resizes it and remains collapsible', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'student', display_name: '测试学生' }
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: { sessions: [] } }))
  await page.route('**/api/profile/summary', route => route.fulfill({ json: {} }))
  await page.route('**/api/knowledge-map', route => route.fulfill({ json: graph }))

  await page.goto('/knowledge-map')
  await expect(page.getByRole('heading', { name: '知识地图' })).toBeVisible()

  const rotationButton = page.getByRole('button', { name: '自动旋转' })
  await rotationButton.click()
  await expect(page.getByRole('button', { name: '暂停旋转' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '重置视角' }).click()
  await expect(page.getByRole('button', { name: '自动旋转' })).toHaveAttribute('aria-pressed', 'false')

  await page.getByRole('button', { name: '已学' }).click()
  await expect(page.getByRole('button', { name: '已学' })).toHaveAttribute('aria-pressed', 'true')

  const fullWidth = await stageWidth(page)
  await page.getByRole('button', { name: '打开知识目录' }).click()
  await expect(page.locator('#knowledge-map-directory')).toBeVisible()
  await expect.poll(() => stageWidth(page)).toBe(fullWidth)

  await page.getByRole('button', { name: '数据科学基础' }).click()
  await page.getByRole('button', { name: '数据科学', exact: true }).click()
  await expect(page.locator('#knowledge-map-inspector')).toHaveAttribute('aria-hidden', 'false')
  await expect(page.locator('#knowledge-map-directory')).toBeVisible()
  await expect.poll(() => stageWidth(page)).toBeLessThan(fullWidth - 250)

  await page.locator('.map-neighbors').getByRole('button', { name: /数据分析/ }).click()
  await expect(page.getByRole('heading', { name: '数据分析' })).toBeVisible()
  await expect(page.locator('#knowledge-map-directory')).toBeVisible()

  await page.getByRole('button', { name: '收起知识点详情面板' }).click()
  await expect(page.locator('#knowledge-map-inspector')).toHaveAttribute('aria-hidden', 'true')
  await expect.poll(() => stageWidth(page)).toBe(fullWidth)
  await expect(page.locator('#knowledge-map-directory')).toBeVisible()
})
