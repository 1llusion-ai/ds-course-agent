export async function mockDefaultCourse(page) {
  await page.route('**/api/courses', route => route.fulfill({ json: {
    courses: [{
      course_id: 'data-science-intro',
      display_name: '数据科学导论',
      status: 'ready',
      is_ready: true
    }]
  } }))
}
