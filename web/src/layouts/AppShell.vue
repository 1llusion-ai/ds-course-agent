<template>
  <div class="app-shell">
    <ChatSidebar
      :collapsed="sidebarCollapsed"
      @toggle-collapse="toggleSidebar"
      @new-chat="handleNewChat"
    />

    <main class="app-shell__workspace" aria-label="课程学习工作区">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ChatSidebar from '../components/ChatSidebar.vue'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'

const APP_SHELL_CONTEXT_KEY = 'ds-course-agent.app-shell'
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'ds-course-agent.sidebarCollapsed'
const THEME_STORAGE_KEY = 'ds-course-agent.theme'

const router = useRouter()
const chatStore = useChatStore()
const sessionStore = useSessionStore()
const sidebarCollapsed = ref(readSidebarCollapsedPreference())
const theme = ref(readThemePreference())
const sessionBootstrapPending = ref(!sessionStore.loaded)
const isDarkTheme = computed(() => theme.value === 'dark')

provide(APP_SHELL_CONTEXT_KEY, {
  isDarkTheme,
  sessionBootstrapPending,
  toggleTheme
})

watch(theme, applyThemePreference, { immediate: true })

function readSidebarCollapsedPreference() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === 'true'
}

function readThemePreference() {
  if (typeof window === 'undefined') return 'light'
  return window.localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light'
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(
      SIDEBAR_COLLAPSED_STORAGE_KEY,
      sidebarCollapsed.value ? 'true' : 'false'
    )
  }
}

function handleNewChat() {
  sessionStore.setCurrentSession(null)
  chatStore.setActiveSession(null)
  chatStore.clearMessages()
  router.push('/chat')
}

function applyThemePreference(value) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('theme-dark', value === 'dark')
  document.body?.classList.toggle('theme-dark', value === 'dark')
  document.getElementById('app')?.classList.toggle('theme-dark', value === 'dark')
  document.documentElement.style.colorScheme = value === 'dark' ? 'dark' : 'light'
}

function toggleTheme() {
  theme.value = isDarkTheme.value ? 'light' : 'dark'
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme.value)
  }
}

onMounted(async () => {
  if (sessionStore.loaded) {
    sessionBootstrapPending.value = false
    return
  }

  try {
    await sessionStore.fetchSessions()
  } catch (error) {
    console.error('加载会话列表失败:', error)
    ElMessage.error('加载会话列表失败，请稍后重试。')
  } finally {
    sessionBootstrapPending.value = false
  }
})
</script>

<style scoped>
.app-shell {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
  background: #f7f7f7;
}

.app-shell__workspace {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #ffffff;
}

.app-shell__workspace > :deep(*) {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
}

:global(html.theme-dark) .app-shell,
:global(html.theme-dark) .app-shell__workspace {
  background: var(--dark-bg) !important;
}
</style>
