<template>
  <div class="app-shell">
    <div
      class="app-shell__sidebar"
      :class="{
        'app-shell__sidebar--collapsed': sidebarCollapsed,
        'app-shell__sidebar--resizing': sidebarResizing
      }"
      :style="{ width: `${sidebarWidth}px` }"
    >
      <ChatSidebar
        :collapsed="sidebarCollapsed"
        style="width: 100%"
        @toggle-collapse="toggleSidebar"
        @new-chat="handleNewChat"
      />
      <PanelResizeHandle
        v-if="!sidebarCollapsed"
        side="start"
        label="调整导航栏宽度"
        :value="sidebarWidth"
        :min="SIDEBAR_MIN_WIDTH"
        :max="SIDEBAR_MAX_WIDTH"
        @resize-start="startSidebarResize"
        @resize-keydown="resizeSidebarFromKeyboard"
        @reset="resetSidebarWidth"
      />
    </div>

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
import PanelResizeHandle from '../components/PanelResizeHandle.vue'
import { useResizablePanel } from '../composables/useResizablePanel'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'

const APP_SHELL_CONTEXT_KEY = 'ds-course-agent.app-shell'
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'ds-course-agent.sidebarCollapsed'
const SIDEBAR_WIDTH_STORAGE_KEY = 'ds-course-agent.sidebarWidth'
const SIDEBAR_MIN_WIDTH = 224
const SIDEBAR_MAX_WIDTH = 380
const THEME_STORAGE_KEY = 'ds-course-agent.theme'

const router = useRouter()
const chatStore = useChatStore()
const sessionStore = useSessionStore()
const sidebarCollapsed = ref(readSidebarCollapsedPreference())
const {
  width: sidebarWidth,
  isResizing: sidebarResizing,
  startResize: startSidebarResize,
  resizeFromKeyboard: resizeSidebarFromKeyboard,
  resetWidth: resetSidebarWidth
} = useResizablePanel({
  storageKey: SIDEBAR_WIDTH_STORAGE_KEY,
  defaultWidth: 288,
  minWidth: SIDEBAR_MIN_WIDTH,
  maxWidth: SIDEBAR_MAX_WIDTH,
  side: 'start'
})
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

.app-shell__sidebar {
  position: relative;
  flex-shrink: 0;
  height: 100%;
  transition: width 0.18s ease;
}

.app-shell__sidebar--collapsed {
  width: 4rem !important;
}

.app-shell__sidebar--resizing {
  transition: none;
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
