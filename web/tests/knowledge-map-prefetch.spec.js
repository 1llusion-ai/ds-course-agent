import { expect, test } from '@playwright/test'

test('knowledge map prefetch loads both modules before navigation', async ({ page }) => {
  await page.goto('/login')

  const viewRequest = page.waitForRequest(request => request.url().includes('/src/views/KnowledgeMapView.vue'))
  const canvasRequest = page.waitForRequest(request => request.url().includes('/src/components/KnowledgeMapCanvas.vue'))

  await page.evaluate(async () => {
    const { prefetchKnowledgeMap } = await import('/src/utils/prefetch.js')
    await prefetchKnowledgeMap()
  })
  await Promise.all([viewRequest, canvasRequest])
  await expect(page).toHaveURL(/\/login$/)
})
