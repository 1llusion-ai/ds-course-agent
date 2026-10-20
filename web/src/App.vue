<template>
  <router-view />
</template>

<script setup>
import { watch } from 'vue'

import { useAssessmentStore } from './stores/assessment'
import { useAuthStore } from './stores/auth'
import { useChatStore } from './stores/chat'
import { useCourseStore } from './stores/course'
import { useProfileStore } from './stores/profile'
import { useSessionStore } from './stores/session'

const authStore = useAuthStore()
const chatStore = useChatStore()
const courseStore = useCourseStore()
const sessionStore = useSessionStore()
const assessmentStore = useAssessmentStore()
const profileStore = useProfileStore()

watch(
  () => [
    authStore.user?.id,
    authStore.user?.student_id,
    authStore.user?.username,
    authStore.user?.email
  ].find(Boolean) || null,
  (accountId, previousAccountId) => {
    if (accountId === previousAccountId) return
    chatStore.resetForUser()
    sessionStore.resetForUser()
    assessmentStore.resetForUser()
    profileStore.resetForUser()
    courseStore.resetForUser()
  },
  { immediate: true }
)

watch(
  () => courseStore.selectedCourseId,
  () => {
    chatStore.resetForCourse()
    sessionStore.resetForCourse()
    assessmentStore.resetForUser()
    profileStore.resetForUser()
  },
  { flush: 'sync' }
)
</script>

<style>
@import './styles/main.scss';

html, body, #app {
  height: 100%;
  margin: 0;
  overflow: hidden;
}
</style>
