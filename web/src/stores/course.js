import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { coursesApi, DEFAULT_COURSE_ID } from '../api/courses'
import { readLocalStorage, writeLocalStorage } from '../utils/storage'

const COURSE_STORAGE_KEY = 'ds-course-agent.selectedCourse'

function readSelectedCourseId() {
  if (typeof window === 'undefined') {
    return DEFAULT_COURSE_ID
  }
  return readLocalStorage(COURSE_STORAGE_KEY) || DEFAULT_COURSE_ID
}

function persistSelectedCourseId(courseId) {
  if (typeof window !== 'undefined') {
    writeLocalStorage(COURSE_STORAGE_KEY, courseId)
  }
}

export const useCourseStore = defineStore('course', () => {
  const courses = ref([])
  const selectedCourseId = ref(readSelectedCourseId())
  const loading = ref(false)
  const loaded = ref(false)
  const currentCourse = computed(() => (
    courses.value.find(course => course.course_id === selectedCourseId.value) || null
  ))

  async function fetchCourses() {
    if (loading.value) return courses.value
    loading.value = true
    try {
      const response = await coursesApi.list()
      courses.value = Array.isArray(response?.courses) ? response.courses : []
      const selected = courses.value.find(course => course.course_id === selectedCourseId.value)
      const fallback = courses.value.find(course => course.course_id === DEFAULT_COURSE_ID)
        || courses.value.find(course => course.is_ready)
        || courses.value[0]
      if (!selected && fallback?.course_id) {
        selectCourse(fallback.course_id)
      }
      loaded.value = true
      return courses.value
    } finally {
      loading.value = false
    }
  }

  function selectCourse(courseId) {
    const normalized = String(courseId || '').trim().toLowerCase()
    if (!normalized || normalized === selectedCourseId.value) {
      return false
    }
    selectedCourseId.value = normalized
    persistSelectedCourseId(normalized)
    return true
  }

  function resetForUser() {
    courses.value = []
    loaded.value = false
    loading.value = false
  }

  return {
    courses,
    selectedCourseId,
    currentCourse,
    loading,
    loaded,
    fetchCourses,
    selectCourse,
    resetForUser
  }
})
