import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'not authenticated' })
  }))
  await page.goto('/login')
})

test('untrusted answers cannot cover the application, submit forms or run active markup', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { renderMarkdownWithEnhancements } = await import('/src/utils/markdown.js')
    const payload = [
      '<div id="overlay" class="app-shell el-overlay" style="position:fixed;inset:0;z-index:2147483647">fake dialog</div>',
      '<form action="/api/auth/logout"><input name="password"><button formaction="/api/chat/send">submit</button></form>',
      '<img src="https://example.invalid/track" onerror="window.auditExecuted=true">',
      '<svg><a href="javascript:window.auditExecuted=true"><text>run</text></a></svg>',
      '<iframe srcdoc="<script>window.auditExecuted=true</script>"></iframe>',
      '<a href="javascript&#58;alert(1)">bad</a>',
      '<a href="data:text/html,spoof">data</a>',
      '<a href="/login">same origin</a>'
    ].join('\n')
    const root = document.createElement('div')
    root.innerHTML = renderMarkdownWithEnhancements(payload)
    document.body.append(root)
    const result = {
      forbidden: root.querySelectorAll('[style], [id], form, input, img, svg, iframe, script, [onerror], [formaction]').length,
      appClasses: root.querySelectorAll('.app-shell, .el-overlay').length,
      activeLinks: root.querySelectorAll('a[href]').length,
      submitButtons: Array.from(root.querySelectorAll('button')).filter(button => button.type !== 'button').length,
      executed: Boolean(window.auditExecuted),
      content: root.textContent
    }
    root.remove()
    return result
  })
  expect(result.forbidden).toBe(0)
  expect(result.appClasses).toBe(0)
  expect(result.activeLinks).toBe(0)
  expect(result.submitButtons).toBe(0)
  expect(result.executed).toBe(false)
  expect(result.content).toContain('fake dialog')
})

test('course math, syntax-highlighted code, tables and safe citations survive cleaning', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { renderMarkdownWithEnhancements } = await import('/src/utils/markdown.js')
    const text = [
      '行内公式 $x^2 + y^2$。',
      '$$\\frac{1}{n}\\sum_{i=1}^{n} x_i$$',
      '```python\nprint("<script>hello</script>")\n```',
      '| 指标 | 数值 |\n| --- | --- |\n| 准确率 | 0.9 |',
      '[课程资料](https://example.edu/course "课程")'
    ].join('\n\n')
    const root = document.createElement('div')
    root.innerHTML = renderMarkdownWithEnhancements(text)
    return {
      math: root.querySelectorAll('.katex').length,
      display: root.querySelectorAll('.katex-display').length,
      mathLayout: root.querySelectorAll('.katex [style]').length,
      code: root.querySelector('code')?.textContent,
      copy: root.querySelector('.code-copy')?.getAttribute('type'),
      table: root.querySelectorAll('table tr').length,
      href: root.querySelector('a')?.getAttribute('href'),
      rel: root.querySelector('a')?.getAttribute('rel'),
      scriptCount: root.querySelectorAll('script').length
    }
  })
  expect(result.math).toBe(2)
  expect(result.display).toBe(1)
  expect(result.mathLayout).toBeGreaterThan(0)
  expect(result.code).toContain('<script>hello</script>')
  expect(result.copy).toBe('button')
  expect(result.table).toBe(2)
  expect(result.href).toBe('https://example.edu/course')
  expect(result.rel).toBe('noopener noreferrer')
  expect(result.scriptCount).toBe(0)
})

test('math syntax in HTML attributes cannot inject markup and untrusted KaTeX extensions are disabled', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const { renderMarkdownWithEnhancements } = await import('/src/utils/markdown.js')
    const root = document.createElement('div')
    root.innerHTML = renderMarkdownWithEnhancements([
      '<a href="https://example.edu" title="$x^2$">link</a>',
      '$\\htmlStyle{position:fixed;inset:0}{x}$',
      '$\\href{javascript:alert(1)}{click}$',
      '`$code_is_not_math$`'
    ].join('\n\n'))
    return {
      linkCount: root.querySelectorAll('a').length,
      mathInsideLink: root.querySelector('a')?.querySelectorAll('.katex').length,
      code: root.querySelector('code')?.textContent,
      unsafeStyles: Array.from(root.querySelectorAll('[style]')).some(el => /fixed|inset|z-index/.test(el.getAttribute('style'))),
      unsafeLinks: Array.from(root.querySelectorAll('a[href]')).some(el => !el.href.startsWith('https:'))
    }
  })
  expect(result.linkCount).toBe(1)
  expect(result.mathInsideLink).toBe(0)
  expect(result.code).toBe('$code_is_not_math$')
  expect(result.unsafeStyles).toBe(false)
  expect(result.unsafeLinks).toBe(false)
})
