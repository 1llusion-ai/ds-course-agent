<template>
  <router-view />
</template>

<script setup>
import { watch } from 'vue'

import { useAssessmentStore } from './stores/assessment'
import { useAuthStore } from './stores/auth'
import { useChatStore } from './stores/chat'
import { useProfileStore } from './stores/profile'
import { useSessionStore } from './stores/session'
import { useUiStore } from './stores/ui'

const authStore = useAuthStore()
const sessionStore = useSessionStore()
const chatStore = useChatStore()
const assessmentStore = useAssessmentStore()
const profileStore = useProfileStore()
const uiStore = useUiStore()

uiStore.initialize()

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
  },
  { immediate: true }
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
