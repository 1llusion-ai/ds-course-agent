import { expect, test } from '@playwright/test'

const DEFAULT_COURSE = 'data-science-intro'
const SECOND_COURSE = 'digital-literacy'
const FOURTH_COURSE = 'statistics'
const courses = [
  { course_id: DEFAULT_COURSE, display_name: '数据科学导论', is_ready: true },
  { course_id: SECOND_COURSE, display_name: '数字素养', is_ready: true },
  { course_id: FOURTH_COURSE, display_name: '统计学', is_ready: true }
]

function session(courseId) {
  return {
    id: 'shared-session',
    course_id: courseId,
    title: `${courseId} 会话`,
    created_at: '2026-10-20T00:00:00Z',
    updated_at: '2026-10-20T00:00:00Z',
    message_count: 1
  }
}

async function mockCourses(page) {
  await page.route('**/api/auth/me', route => route.fulfill({
    json: { student_id: 'student', display_name: '测试学生' }
  }))
  await page.route('**/api/courses', route => route.fulfill({ json: { courses } }))
  await page.route('**/api/profile/summary?**', route => route.fulfill({ json: {} }))
  await page.route('**/api/sessions?**', route => {
    const courseId = new URL(route.request().url()).searchParams.get('course_id')
    return route.fulfill({ json: { sessions: [session(courseId)] } })
  })
}

async function openCourseSettings(page) {
  await page.getByRole('button', { name: /^设置/ }).click()
  await expect(page).toHaveURL(/\/settings$/)
  return page.getByRole('combobox', { name: '切换课程' })
}

async function switchCourse(page, courseId) {
  const selector = await openCourseSettings(page)
  await selector.selectOption(courseId)
  await expect(page).toHaveURL(/\/chat$/)
}

test('switching courses isolates shared session IDs and ignores late history', async ({ page }) => {
  await mockCourses(page)
  let releaseLateHistory
  let secondCourseRequests = 0
  const historyCourses = []
  await page.route('**/api/chat/history/shared-session?**', async route => {
    const courseId = new URL(route.request().url()).searchParams.get('course_id')
    historyCourses.push(courseId)
    if (courseId === SECOND_COURSE && ++secondCourseRequests === 1) {
      await new Promise(resolve => { releaseLateHistory = resolve })
    }
    await route.fulfill({ json: {
      session_id: 'shared-session', course_id: courseId,
      messages: [{ role: 'assistant', content: `${courseId} 专属历史`, timestamp: '2026-10-20T00:00:00Z' }]
    } })
  })

  await page.goto('/chat/shared-session')
  await expect(page.getByRole('combobox', { name: '切换课程' })).toHaveCount(0)
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toBeVisible()
  await switchCourse(page, SECOND_COURSE)
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toHaveCount(0)
  await page.locator('.session-title').filter({ hasText: `${SECOND_COURSE} 会话` }).click()
  await expect.poll(() => historyCourses.filter(id => id === SECOND_COURSE).length).toBe(1)

  await switchCourse(page, DEFAULT_COURSE)
  await page.locator('.session-title').filter({ hasText: `${DEFAULT_COURSE} 会话` }).click()
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toBeVisible()
  releaseLateHistory()
  await expect(page.getByText(`${SECOND_COURSE} 专属历史`, { exact: true })).toHaveCount(0)

  await switchCourse(page, SECOND_COURSE)
  await page.locator('.session-title').filter({ hasText: `${SECOND_COURSE} 会话` }).click()
  await expect(page.getByText(`${SECOND_COURSE} 专属历史`, { exact: true })).toBeVisible()
  await expect(page.getByText(`${DEFAULT_COURSE} 专属历史`, { exact: true })).toHaveCount(0)
  expect(historyCourses).toEqual([DEFAULT_COURSE, SECOND_COURSE, DEFAULT_COURSE, SECOND_COURSE])
})

test('catalog additions appear automatically and ready courses can send', async ({ page }) => {
  await mockCourses(page)
  let streamPayload
  await page.route('**/api/sessions', route => {
    const data = route.request().postDataJSON()
    return route.fulfill({ json: session(data.course_id) })
  })
  await page.route('**/api/chat/history/shared-session?**', route => route.fulfill({ json: { messages: [] } }))
  await page.route('**/api/chat/send/stream', route => {
    streamPayload = route.request().postDataJSON()
    return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({
      type: 'final', message: { role: 'assistant', content: '统计学回答', timestamp: '2026-10-20T00:00:00Z' }
    })}\n\n` })
  })

  await page.goto('/chat')
  const selector = await openCourseSettings(page)
  await expect(selector.locator('option')).toHaveCount(3)
  await selector.selectOption(FOURTH_COURSE)
  await expect(page.locator('textarea')).toBeEnabled()
  await page.locator('textarea').fill('介绍统计推断')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('统计学回答', { exact: true })).toBeVisible()
  expect(streamPayload).toMatchObject({ session_id: 'shared-session', course_id: FOURTH_COURSE, message: '介绍统计推断' })
  await openCourseSettings(page)
  await page.reload()
  await expect(selector).toHaveValue(FOURTH_COURSE)
})

test('course map caches are isolated across the two course graphs', async ({ page }) => {
  await mockCourses(page)
  const requestedCourses = []
  await page.route('**/api/knowledge-map?**', route => {
    const courseId = new URL(route.request().url()).searchParams.get('course_id')
    requestedCourses.push(courseId)
    return route.fulfill({ json: courseId === SECOND_COURSE
      ? {
          course_name: '数字素养', version: '1',
          chapters: [{ chapter: '第5章', title: '数字技术通识' }],
          nodes: [{
            canonical_id: 'dl_5_4_4', display_name: 'AIGC、生成式人工智能与大语言模型', chapter: '第5章',
            node_type: 'kc', aliases: ['AIGC'], learning_state: 'unobserved', learning_points: []
          }],
          edges: [{ source: 'dl_5_4_4', target: 'chapter:5', relation_type: 'part_of' }]
        }
      : {
          course_name: '数据科学导论', version: '1',
          chapters: [{ chapter: '第1章', title: '数据科学基础' }],
          nodes: [{
            canonical_id: 'data_science', display_name: '数据科学', chapter: '第1章',
            node_type: 'kc', aliases: [], learning_state: 'unobserved', learning_points: []
          }],
          edges: []
        }
    })
  })

  await page.goto('/knowledge-map')
  await page.getByRole('button', { name: '打开知识目录' }).click()
  await expect(page.getByRole('button', { name: '数据科学基础' })).toBeVisible()

  await switchCourse(page, SECOND_COURSE)
  await page.getByRole('button', { name: /知识地图/ }).click()
  await expect(page.getByRole('heading', { name: '知识地图' })).toBeVisible()
  await expect(page.locator('.map-workspace')).toBeVisible()
  await page.getByRole('button', { name: '打开知识目录' }).click()
  await expect(page.getByRole('button', { name: '数字技术通识' })).toBeVisible()
  await expect(page.getByRole('button', { name: '数据科学基础' })).toHaveCount(0)
  await page.goto('/chat')
  await expect(page).toHaveURL(/\/chat$/)

  await switchCourse(page, DEFAULT_COURSE)
  await page.getByRole('button', { name: /知识地图/ }).click()
  await page.getByRole('button', { name: '打开知识目录' }).click()
  await expect(page.getByRole('button', { name: '数据科学基础' })).toBeVisible()
  await expect(page.getByRole('button', { name: '数字技术通识' })).toHaveCount(0)
  expect(requestedCourses).toEqual([DEFAULT_COURSE, SECOND_COURSE, DEFAULT_COURSE])
})

test('map explanation keeps the selected course identity through new chat and SSE', async ({ page }) => {
  await mockCourses(page)
  let streamPayload
  await page.route('**/api/knowledge-map?**', route => route.fulfill({ json: {
    course_name: '数字素养与技能导论', chapters: [{ chapter: '第7章', title: '数字社会' }],
    nodes: [{ canonical_id: 'dl_7_1_2', display_name: '数字命运共同体', chapter: '第7章', section: '7.1.2',
      node_type: 'kc', aliases: [], learning_state: 'unobserved', learning_points: [] }], edges: []
  } }))
  await page.route('**/api/sessions', route => route.fulfill({ json: session(route.request().postDataJSON().course_id) }))
  await page.route('**/api/chat/history/shared-session?**', route => route.fulfill({ json: { messages: [] } }))
  await page.route('**/api/chat/send/stream', route => {
    streamPayload = route.request().postDataJSON()
    return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({
      type: 'final', message: { role: 'assistant', content: '课程回答', timestamp: '2026-10-20T00:00:00Z' }
    })}\n\n` })
  })
  await page.goto('/chat')
  await switchCourse(page, SECOND_COURSE)
  await page.goto('/knowledge-map?concept=dl_7_1_2')
  await expect(page.getByRole('heading', { name: '数字命运共同体' })).toBeVisible()
  await page.getByRole('button', { name: '讨论这个概念' }).click()
  await expect(page.locator('textarea')).toHaveValue('请讲解《数字素养与技能导论》第7章 7.1.2 节的「数字命运共同体」，用一个简单例子帮助我理解。')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => streamPayload?.course_id).toBe(SECOND_COURSE)
  expect(streamPayload.message).toContain('《数字素养与技能导论》第7章 7.1.2 节')
})

test('alternating map explanation and practice actions use each course resource', async ({ page }) => {
  await mockCourses(page)
  const fixtures = {
    [DEFAULT_COURSE]: { name: '数据科学导论', chapter: '第1章', section: '1.1', concept: '数据思维' },
    [SECOND_COURSE]: { name: '数字素养与技能导论', chapter: '第7章', section: '7.1.2', concept: '数字命运共同体' },
    [FOURTH_COURSE]: { name: '统计学', chapter: '第3章', section: '3.2', concept: '抽样分布' }
  }
  const payloads = []
  await page.route('**/api/knowledge-map?**', route => {
    const id = new URL(route.request().url()).searchParams.get('course_id')
    const data = fixtures[id]
    return route.fulfill({ json: {
      course_name: data.name, chapters: [{ chapter: data.chapter, title: data.concept }],
      nodes: [{ canonical_id: 'same-concept-id', display_name: data.concept, chapter: data.chapter, section: data.section,
        node_type: 'kc', aliases: [], learning_state: 'unobserved', learning_points: [] }], edges: []
    } })
  })
  await page.route('**/api/sessions', route => route.fulfill({ json: session(route.request().postDataJSON().course_id) }))
  await page.route('**/api/chat/history/shared-session?**', route => route.fulfill({ json: { messages: [] } }))
  await page.route('**/api/chat/send/stream', route => {
    const data = route.request().postDataJSON()
    payloads.push(data)
    return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({
      type: 'final', message: { role: 'assistant', content: `${data.course_id} 回答`, timestamp: '2026-10-20T00:00:00Z' }
    })}\n\n` })
  })
  await page.goto('/chat')
  await expect(page.getByText('这门课程有哪些核心概念？', { exact: true })).toBeVisible()
  await expect(page.getByText('逻辑回归为什么能做分类？', { exact: true })).toHaveCount(0)
  for (const [index, id] of [SECOND_COURSE, DEFAULT_COURSE, FOURTH_COURSE, SECOND_COURSE].entries()) {
    await switchCourse(page, id)
    await page.goto(`/knowledge-map?concept=same-concept-id&course_id=${id}`)
    const data = fixtures[id]
    await expect(page.getByRole('heading', { name: data.concept })).toBeVisible()
    const practice = index % 2 === 1
    await page.getByRole('button', { name: practice ? '做一道理解题' : '讨论这个概念' }).click()
    await expect(page).toHaveURL(new RegExp(`course_id=${id}`))
    const context = `《${data.name}》${data.chapter} ${data.section} 节的「${data.concept}」`
    await expect(page.locator('textarea')).toHaveValue(practice
      ? `请围绕${context}出一道理解题，引导我思考，先不要给出答案。`
      : `请讲解${context}，用一个简单例子帮助我理解。`)
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect.poll(() => payloads.length).toBe(index + 1)
    expect(payloads[index]).toMatchObject({ course_id: id, session_id: 'shared-session' })
    expect(payloads[index].message).toContain(context)
    await expect(page.getByText(`${id} 回答`, { exact: true })).toBeVisible()
  }
  await switchCourse(page, DEFAULT_COURSE)
  await page.goto(`/chat?question=${encodeURIComponent('数字素养旧问题')}&course_id=${SECOND_COURSE}`)
  await expect(page.locator('textarea')).toHaveValue('')
})

test('late map responses cannot supply a question after switching courses', async ({ page }) => {
  await mockCourses(page)
  let releaseLateMap
  let lateMapStarted = false
  await page.route('**/api/knowledge-map?**', async route => {
    const courseId = new URL(route.request().url()).searchParams.get('course_id')
    if (courseId === SECOND_COURSE) {
      lateMapStarted = true
      await new Promise(resolve => { releaseLateMap = resolve })
    }
    const concept = courseId === SECOND_COURSE ? '数字命运共同体' : '数据思维'
    await route.fulfill({ json: { course_name: courseId === SECOND_COURSE ? '数字素养与技能导论' : '数据科学导论',
      chapters: [{ chapter: '第1章', title: concept }], nodes: [{ canonical_id: 'shared-node', display_name: concept,
        chapter: '第1章', section: '1.1', node_type: 'kc', aliases: [], learning_state: 'unobserved', learning_points: [] }], edges: []
    } })
  })
  await page.goto('/chat')
  await switchCourse(page, SECOND_COURSE)
  await page.getByRole('button', { name: /知识地图/ }).click()
  await expect.poll(() => lateMapStarted).toBe(true)
  await switchCourse(page, DEFAULT_COURSE)
  await page.goto('/knowledge-map?concept=shared-node')
  await expect(page.getByRole('heading', { name: '数据思维' })).toBeVisible()
  releaseLateMap()
  await page.getByRole('button', { name: '讨论这个概念' }).click()
  await expect(page.locator('textarea')).toHaveValue('请讲解《数据科学导论》第1章 1.1 节的「数据思维」，用一个简单例子帮助我理解。')
})
