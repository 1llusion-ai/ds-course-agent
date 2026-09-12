<template>
  <div class="app-shell">
    <aside
      v-if="!narrowViewport"
      class="app-shell__sidebar"
      :class="{
        'app-shell__sidebar--collapsed': sidebarCollapsed,
        'app-shell__sidebar--resizing': sidebarResizing
      }"
      :style="{ width: `${sidebarWidth}px` }"
    >
      <ChatSidebar
        :collapsed="sidebarCollapsed"
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
    </aside>

    <button
      v-if="narrowViewport"
      ref="mobileMenuButtonRef"
      type="button"
      class="app-shell__mobile-menu"
      :aria-expanded="mobileDrawerOpen"
      aria-controls="mobile-navigation-drawer"
      aria-label="打开课程导航"
      title="课程导航"
      @click="openMobileDrawer"
    >
      <el-icon><Menu /></el-icon>
    </button>

    <div
      v-if="narrowViewport && mobileDrawerOpen"
      class="app-shell__drawer-backdrop"
      aria-hidden="true"
      @click="closeMobileDrawer"
    />

    <aside
      v-if="narrowViewport && mobileDrawerOpen"
      id="mobile-navigation-drawer"
      ref="mobileDrawerRef"
      class="app-shell__mobile-drawer"
      aria-label="课程导航"
      aria-modal="true"
      role="dialog"
      @keydown="handleMobileDrawerKeydown"
    >
      <ChatSidebar
        mobile
        @new-chat="handleNewChat"
        @mobile-close="closeMobileDrawer"
      />
    </aside>

    <main
      class="app-shell__workspace"
      :inert="narrowViewport && mobileDrawerOpen"
      aria-label="课程学习工作区"
    >
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Menu } from '@element-plus/icons-vue'

import ChatSidebar from '../components/ChatSidebar.vue'
import PanelResizeHandle from '../components/PanelResizeHandle.vue'
import { useResizablePanel } from '../composables/useResizablePanel'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'
import { readLocalStorage, writeLocalStorage } from '../utils/storage'

const APP_SHELL_CONTEXT_KEY = 'ds-course-agent.app-shell'
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'ds-course-agent.sidebarCollapsed'
const SIDEBAR_WIDTH_STORAGE_KEY = 'ds-course-agent.sidebarWidth'
const SIDEBAR_MIN_WIDTH = 224
const SIDEBAR_MAX_WIDTH = 380

const router = useRouter()
const chatStore = useChatStore()
const sessionStore = useSessionStore()
const sidebarCollapsed = ref(readSidebarCollapsedPreference())
const narrowViewport = ref(false)
const mobileDrawerOpen = ref(false)
const mobileMenuButtonRef = ref(null)
const mobileDrawerRef = ref(null)
const mobileDrawerReturnFocus = ref(null)
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
const sessionBootstrapPending = ref(!sessionStore.loaded)

provide(APP_SHELL_CONTEXT_KEY, { sessionBootstrapPending, openMobileDrawer })

function readSidebarCollapsedPreference() {
  if (typeof window === 'undefined') return false
  return readLocalStorage(SIDEBAR_COLLAPSED_STORAGE_KEY) === 'true'
}

function updateViewport() {
  narrowViewport.value = window.innerWidth <= 760
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  if (typeof window !== 'undefined') {
    writeLocalStorage(
      SIDEBAR_COLLAPSED_STORAGE_KEY,
      sidebarCollapsed.value ? 'true' : 'false'
    )
  }
}

function handleNewChat() {
  sessionStore.setCurrentSession(null)
  chatStore.setActiveSession(null)
  chatStore.clearMessages()
  closeMobileDrawer({ restoreFocus: false })
  router.push('/chat')
}

function openMobileDrawer() {
  if (!narrowViewport.value) return
  mobileDrawerReturnFocus.value = document.activeElement
  mobileDrawerOpen.value = true
}

function closeMobileDrawer({ restoreFocus = true } = {}) {
  if (!mobileDrawerOpen.value) return
  mobileDrawerOpen.value = false
  if (restoreFocus) {
    nextTick(() => {
      const focusTarget = mobileDrawerReturnFocus.value || mobileMenuButtonRef.value
      focusTarget?.focus?.()
    })
  }
}

function focusMobileDrawer() {
  const drawer = mobileDrawerRef.value
  const focusTarget = drawer?.querySelector('[data-mobile-drawer-focus], button, input, [href], [tabindex]:not([tabindex="-1"])')
  focusTarget?.focus?.()
}

function handleMobileDrawerKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMobileDrawer()
    return
  }

  if (event.key !== 'Tab') return
  const focusable = [...mobileDrawerRef.value?.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
  ) || []]
  if (!focusable.length) {
    event.preventDefault()
    return
  }

  const first = focusable[0]
  const last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(mobileDrawerOpen, open => {
  if (open) nextTick(focusMobileDrawer)
})

watch(narrowViewport, narrow => {
  if (!narrow) closeMobileDrawer({ restoreFocus: false })
})

onMounted(async () => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
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

onBeforeUnmount(() => window.removeEventListener('resize', updateViewport))
</script>

<style scoped>
.app-shell {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 100dvh;
  overflow: hidden;
  color: var(--text);
  background: var(--app-bg);
}

.app-shell__workspace {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--surface);
}

.app-shell__sidebar {
  position: relative;
  flex-shrink: 0;
  height: 100%;
  overflow: hidden;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  transition: width 160ms ease;
}

.app-shell__sidebar--collapsed {
  width: 64px !important;
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

.app-shell__mobile-menu {
  position: fixed;
  z-index: 24;
  top: 10px;
  left: 10px;
  display: grid;
  width: 40px;
  height: 40px;
  padding: 0;
  place-items: center;
  color: var(--text);
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
}

.app-shell__mobile-menu:hover {
  background: var(--surface-hover);
}

.app-shell__drawer-backdrop {
  position: fixed;
  z-index: 30;
  inset: 0;
  background: var(--overlay);
}

.app-shell__mobile-drawer {
  position: fixed;
  z-index: 31;
  top: 0;
  bottom: 0;
  left: 0;
  width: min(332px, calc(100vw - 40px));
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  box-shadow: var(--shadow-md);
}

@media (max-width: 760px) {
  .app-shell__workspace {
    width: 100%;
  }
}
</style>
