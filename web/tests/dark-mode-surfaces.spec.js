import { expect, test } from '@playwright/test'

const DARK_BG = 'rgb(33, 33, 33)'
const DARK_PANEL = 'rgb(42, 42, 42)'
const DARK_PANEL_SOFT = 'rgb(47, 47, 47)'

const graph = {
  chapters: [{ chapter: '第1章', title: '数据科学基础' }],
  nodes: [{
    canonical_id: 'data_science',
    display_name: '数据科学',
    aliases: [],
    node_type: 'kc',
    chapter: '第1章',
    section: '1.1',
    summary: '从数据中提取知识的方法体系。',
    learning_state: 'unobserved',
    learning_points: []
  }],
  edges: []
}

async function mockShell(page) {
  await page.addInitScript(() => window.localStorage.setItem('ds-course-agent.theme', 'dark'))
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'student', display_name: '测试学生' }
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: { sessions: [] } }))
  await page.route('**/api/profile/summary', route => route.fulfill({ json: {} }))
}

async function expectBackground(page, selector, color) {
  await expect(page.locator(selector)).toHaveCSS('background-color', color)
}

test.beforeEach(async ({ page }) => {
  await mockShell(page)
})

test('assessment list uses dark surfaces', async ({ page }) => {
  await page.route('**/api/assessments/preparations', route => route.fulfill({ json: [{
    id: 'preparation-1',
    display_name: '欠拟合',
    status: 'failed',
    session_id: null
  }] }))
  await page.route('**/api/assessments?**', route => route.fulfill({ json: [{
    id: 'assessment-1',
    title: '分类基础测验',
    status: 'ready',
    question_count: 3,
    assigned_at: '2026-09-13T08:00:00Z',
    session_id: null
  }] }))

  await page.goto('/assessments')

  await expectBackground(page, '.assessment-page', DARK_BG)
  await expectBackground(page, '.assessment-tabs', DARK_PANEL_SOFT)
  await expectBackground(page, '.assessment-list-item:first-child', 'rgba(0, 0, 0, 0)')
  await expect(page.locator('.assessment-list-item:first-child')).toHaveCSS('border-bottom-color', 'rgb(58, 58, 58)')
  await expectBackground(page, '.assessment-retry-button', 'rgba(0, 0, 0, 0)')
  await expect(page.locator('.assessment-retry-button')).toHaveCSS('border-radius', '999px')
})

test('knowledge map and directory use dark surfaces', async ({ page }) => {
  await page.route('**/api/knowledge-map', route => route.fulfill({ json: graph }))

  await page.goto('/knowledge-map')

  await expectBackground(page, '.knowledge-map-page', DARK_BG)
  await expectBackground(page, '.map-stage', DARK_BG)
  await page.getByRole('button', { name: '打开知识目录' }).click()
  await expectBackground(page, '.map-directory-popover', DARK_PANEL)
})

test('learning profile uses dark surfaces', async ({ page }) => {
  await page.route('**/api/profile/detail?**', route => route.fulfill({ json: {
    recent_concepts: [{ concept_id: 'data_science', display_name: '数据科学', mention_count: 2 }],
    pending_weak_spots: [],
    weak_spots: [{ concept_id: 'classification', display_name: '分类', evidence_count: 2 }],
    resolved_weak_spots: [],
    chapter_stats: { '第1章': 3 },
    daily_activity: { '2026-09-13': 2 },
    progress: { current_chapter: '第1章' },
    stats: {}
  } }))

  await page.goto('/profile')

  await expectBackground(page, '.profile-page', DARK_BG)
  await expectBackground(page, '.profile-overview__copy', DARK_PANEL)
  await expectBackground(page, '.profile-content', DARK_PANEL)
  await expectBackground(page, '.profile-sidebar__section:first-child', DARK_PANEL_SOFT)
})
