<template>
  <div class="chat-layout">
    <ChatSidebar :collapsed="sidebarCollapsed" @toggle-collapse="toggleSidebar" />

    <div class="chat-main">
      <header class="chat-header">
        <div class="thread-header-left">
          <input
            v-if="headerRenaming"
            ref="headerRenameInputRef"
            v-model="headerRenameTitle"
            class="thread-title-input"
            type="text"
            aria-label="重命名当前会话"
            autocomplete="off"
            @keydown.enter.prevent="commitHeaderRename"
            @keydown.esc.prevent.stop="cancelHeaderRename"
            @blur="commitHeaderRename"
          />
          <button
            v-else
            type="button"
            class="thread-title-button"
            :class="{ 'thread-title-button--disabled': !canRenameCurrentSession }"
            :disabled="!canRenameCurrentSession"
            :title="canRenameCurrentSession ? '点击重命名' : undefined"
            @click="startHeaderRename"
          >
            <span class="thread-title">{{ headerTitle }}</span>
            <el-icon v-if="canRenameCurrentSession" class="thread-title-edit-icon"><EditPen /></el-icon>
          </button>
        </div>
        <div class="header-status">
          <button
            type="button"
            class="theme-toggle"
            :aria-label="isDarkTheme ? '切换到日间模式' : '切换到夜间模式'"
            :title="isDarkTheme ? '日间模式' : '夜间模式'"
            @click="toggleTheme"
          >
            <svg v-if="isDarkTheme" class="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v2m0 14v2m9-9h-2M5 12H3m15.36-6.36-1.42 1.42M7.06 16.94l-1.42 1.42m12.72 0-1.42-1.42M7.06 7.06 5.64 5.64" />
              <circle cx="12" cy="12" r="4" stroke-width="2" />
            </svg>
            <svg v-else class="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12.79A8.5 8.5 0 1 1 11.21 3 6.7 6.7 0 0 0 21 12.79Z" />
            </svg>
          </button>
        </div>
      </header>

      <div class="chat-content">
        <div ref="messagesContainer" class="messages-area" @scroll.passive="handleMessagesScroll">
          <div v-if="chatStore.messages.length === 0" class="empty-state">
            <div class="empty-content">
              <div class="empty-kicker">DATA SCIENCE COURSE AGENT</div>
              <h1>今天想解决什么数据科学问题？</h1>
              <p>
                可以直接提问课程概念、公式推导、案例理解，
                也可以让我帮你梳理最近卡住的知识点。
              </p>
              <ChatInput
                hero
                :loading="chatStore.loading"
                :web-search-enabled="webSearchEnabled"
                class="empty-composer"
                @send="handleSend"
                @toggle-web-search="toggleWebSearch"
              />
              <div class="prompt-grid">
                <button
                  v-for="prompt in starterPrompts"
                  :key="prompt"
                  class="prompt-card"
                  type="button"
                  @click="handleStarterPrompt(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </div>
          </div>

          <div v-else ref="messagesList" class="messages-list">
            <ChatMessage
              v-for="(message, index) in chatStore.messages"
              :key="message.requestId || `${message.timestamp || index}-${index}`"
              :message="message"
              @open-sources="openSourcesPanel"
            />
            <div ref="bottomAnchor" class="messages-bottom-anchor" aria-hidden="true"></div>
          </div>
        </div>

        <div v-if="chatStore.messages.length > 0" class="input-area">
          <ChatInput
            :loading="chatStore.loading"
            :web-search-enabled="webSearchEnabled"
            @send="handleSend"
            @toggle-web-search="toggleWebSearch"
          />
        </div>
      </div>
    </div>

    <aside v-if="sourcesPanelOpen" class="sources-panel" aria-label="搜索来源">
      <div class="sources-panel__header">
        <div>
          <div class="sources-panel__kicker">WEB SOURCES</div>
          <h2>{{ sourcesPanelTitle }}</h2>
        </div>
        <button type="button" class="sources-panel__close" aria-label="关闭来源面板" @click="closeSourcesPanel">
          ×
        </button>
      </div>

      <div class="sources-panel__list">
        <component
          :is="source.isExternal ? 'a' : 'div'"
          v-for="source in sourcesPanelSources"
          :key="source.key"
          class="sources-panel__card"
          :href="source.isExternal ? source.url : undefined"
          :target="source.isExternal ? '_blank' : undefined"
          :rel="source.isExternal ? 'noopener noreferrer' : undefined"
          :title="source.title"
        >
          <span class="sources-panel__favicon-wrap">
            <span class="sources-panel__favicon-fallback" aria-hidden="true">🌐</span>
            <img
              v-if="source.favicon"
              class="sources-panel__favicon"
              :src="source.favicon"
              :alt="source.domain || source.label"
              @error="$event.target.style.display = 'none'"
            />
          </span>
          <span class="sources-panel__body">
            <span class="sources-panel__title">{{ source.label }}</span>
            <span class="sources-panel__domain">{{ source.domain || source.url }}</span>
            <span v-if="source.snippet" class="sources-panel__snippet">{{ source.snippet }}</span>
            <span v-if="source.provider || source.published_at" class="sources-panel__meta">
              {{ [source.provider, source.published_at].filter(Boolean).join(' · ') }}
            </span>
          </span>
        </component>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ChatInput from '../components/ChatInput.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatSidebar from '../components/ChatSidebar.vue'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'
import { useSessionStore } from '../stores/session'
import { domainFromUrl, faviconUrl, isExternalUrl } from '../utils/url'

const route = useRoute()
const router = useRouter()
const messagesContainer = ref(null)
const messagesList = ref(null)
const bottomAnchor = ref(null)
const stickToBottom = ref(true)

const sessionStore = useSessionStore()
const chatStore = useChatStore()
const profileStore = useProfileStore()
const sidebarCollapsed = ref(readSidebarCollapsedPreference())
const theme = ref(readThemePreference())
const webSearchEnabled = ref(readWebSearchPreference())
const sourcesPanelOpen = ref(false)
const sourcesPanelTitle = ref('搜索来源')
const sourcesPanelSources = ref([])
const headerRenameInputRef = ref(null)
const headerRenaming = ref(false)
const headerRenameTitle = ref('')
const headerRenameSaving = ref(false)
let scrollFrameId = null
let messagesResizeObserver = null

const headerTitle = computed(() => sessionStore.currentSession?.title || '新对话')
const canRenameCurrentSession = computed(() => Boolean(sessionStore.currentSessionId && sessionStore.currentSession))
const isDarkTheme = computed(() => theme.value === 'dark')

const starterPrompts = [
  '逻辑回归为什么能做分类？',
  'K-means 的基本步骤是什么？',
  '帮我区分过拟合和欠拟合',
  '请用 Python 演示一次交叉验证'
]

watch(
  [() => route.params.sessionId, () => sessionStore.loaded, () => sessionStore.sortedSessions.length],
  ([newId, isLoaded, sessionCount]) => {
    if (!isLoaded) {
      return
    }

    if (newId) {
      const exists = sessionStore.sessions.some(session => session.id === newId)
      if (!exists) {
        if (sessionCount > 0) {
          const first = sessionStore.sortedSessions[0]
          if (first && route.params.sessionId !== first.id) {
            sessionStore.setCurrentSession(first.id)
            router.replace(`/chat/${first.id}`)
          }
        } else {
          sessionStore.setCurrentSession(null)
          chatStore.clearMessages()
          if (route.path !== '/chat') {
            router.replace('/chat')
          }
        }
        return
      }

      if (sessionStore.currentSessionId !== newId) {
        sessionStore.setCurrentSession(newId)
      }
      return
    }

    sessionStore.setCurrentSession(null)
    chatStore.setActiveSession(null)
  },
  { immediate: true }
)

watch(() => sessionStore.currentSessionId, (newId) => {
  cancelHeaderRename()
  if (!newId) return
  const exists = sessionStore.sessions.some(session => session.id === newId)
  if (!exists) return
  if (chatStore.activeSessionId !== newId) {
    loadSession(newId)
  }
})

async function loadSession(sessionId) {
  sessionStore.setCurrentSession(sessionId)
  chatStore.setActiveSession(sessionId)

  try {
    await chatStore.fetchHistory(sessionId)
  } catch (error) {
    console.error('加载会话历史失败:', error)
    const status = error?.response?.status

    if (status === 404 || status === 403) {
      const first = sessionStore.sortedSessions[0]
      if (first && first.id !== sessionId) {
        sessionStore.setCurrentSession(first.id)
        router.replace(`/chat/${first.id}`)
        ElMessage.warning('当前会话不可用，已切换到最近会话。')
      } else {
        sessionStore.setCurrentSession(null)
        chatStore.clearMessages(sessionId)
        router.replace('/chat')
      }
    } else {
      ElMessage.error('加载会话历史失败，请稍后重试。')
    }
  }

  scrollToBottom(true)
}

async function handleSend(message, sendOptions = {}) {
  const useWebSearch = Boolean(sendOptions?.webSearch ?? webSearchEnabled.value)
  const streamOptions = { onProgress: scrollToBottom, webSearch: useWebSearch }
  const currentSessionId = sessionStore.currentSessionId
  let targetSessionId = currentSessionId
  let shouldRefreshTitle = false
  stickToBottom.value = true

  if (!currentSessionId) {
    const newSession = await sessionStore.createSession()
    targetSessionId = newSession.id
    shouldRefreshTitle = true
    chatStore.setActiveSession(newSession.id)
    await router.push(`/chat/${newSession.id}`)
    await chatStore.sendMessage(newSession.id, message, streamOptions)
  } else {
    shouldRefreshTitle = sessionStore.shouldAutoTitle(currentSessionId)
    chatStore.setActiveSession(currentSessionId)
    await chatStore.sendMessage(currentSessionId, message, streamOptions)
  }

  if (shouldRefreshTitle) {
    try {
      await sessionStore.fetchSessions()
      const stillOnTargetSession = (
        targetSessionId &&
        (route.params.sessionId === targetSessionId || sessionStore.currentSessionId === targetSessionId)
      )
      if (stillOnTargetSession) {
        sessionStore.setCurrentSession(targetSessionId)
      }
    } catch (error) {
      console.error('同步会话标题失败:', error)
    }
  }

  await profileStore.fetchSummary()
  scrollToBottom(true)
}

function handleStarterPrompt(prompt) {
  if (chatStore.loading) return
  handleSend(prompt)
}

function focusHeaderRenameInput() {
  nextTick(() => {
    headerRenameInputRef.value?.focus()
    headerRenameInputRef.value?.select()
  })
}

function startHeaderRename() {
  if (!canRenameCurrentSession.value) return
  headerRenameTitle.value = sessionStore.currentSession?.title || ''
  headerRenaming.value = true
  focusHeaderRenameInput()
}

function cancelHeaderRename() {
  headerRenaming.value = false
  headerRenameTitle.value = ''
}

async function commitHeaderRename() {
  if (headerRenameSaving.value || !headerRenaming.value) {
    return
  }

  const session = sessionStore.currentSession
  if (!session?.id) {
    cancelHeaderRename()
    return
  }

  const nextTitle = headerRenameTitle.value.trim()
  const previousTitle = String(session.title || '').trim()

  if (!nextTitle || nextTitle === previousTitle) {
    cancelHeaderRename()
    return
  }

  headerRenameSaving.value = true
  try {
    await sessionStore.updateSession(session.id, { title: nextTitle })
    cancelHeaderRename()
  } catch (error) {
    console.error('重命名当前会话失败:', error)
    ElMessage.error('重命名失败，请稍后再试')
    focusHeaderRenameInput()
  } finally {
    headerRenameSaving.value = false
  }
}

function readWebSearchPreference() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem('ds-course-agent.webSearchEnabled') === 'true'
}

function readSidebarCollapsedPreference() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem('ds-course-agent.sidebarCollapsed') === 'true'
}

function readThemePreference() {
  if (typeof window === 'undefined') return 'light'
  return window.localStorage.getItem('ds-course-agent.theme') === 'dark' ? 'dark' : 'light'
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
    window.localStorage.setItem('ds-course-agent.theme', theme.value)
  }
}

function toggleWebSearch(nextValue) {
  webSearchEnabled.value = Boolean(nextValue)
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(
      'ds-course-agent.webSearchEnabled',
      webSearchEnabled.value ? 'true' : 'false'
    )
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(
      'ds-course-agent.sidebarCollapsed',
      sidebarCollapsed.value ? 'true' : 'false'
    )
  }
}

function normalizePanelSource(source, index) {
  const url = source?.url || ''
  const domain = source?.domain || domainFromUrl(url)
  const isExternal = isExternalUrl(url)

  return {
    key: source?.key || `${url || source?.label || 'source'}-${index}`,
    index: source?.index || index + 1,
    label: source?.label || source?.title || domain || url || `网页 ${index + 1}`,
    title: source?.title || source?.label || domain || url || `网页 ${index + 1}`,
    url,
    domain,
    isExternal,
    favicon: source?.favicon || faviconUrl(url, domain),
    snippet: source?.snippet || '',
    provider: source?.provider || '',
    published_at: source?.published_at || ''
  }
}

function openSourcesPanel(payload = {}) {
  const sources = Array.isArray(payload.sources) ? payload.sources : []
  sourcesPanelSources.value = sources
    .map(normalizePanelSource)
    .filter(source => source.url)
  sourcesPanelTitle.value = payload.title || `搜索来源 · ${sourcesPanelSources.value.length} 个网页`
  sourcesPanelOpen.value = sourcesPanelSources.value.length > 0
}

function closeSourcesPanel() {
  sourcesPanelOpen.value = false
}

function isNearBottom(container = messagesContainer.value) {
  if (!container) return true
  const threshold = 48
  return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold
}

function handleMessagesScroll() {
  const container = messagesContainer.value
  if (!container) return

  const shouldStick = isNearBottom(container)
  stickToBottom.value = shouldStick

  if (!shouldStick && scrollFrameId !== null && typeof window !== 'undefined') {
    window.cancelAnimationFrame(scrollFrameId)
    scrollFrameId = null
  }
}

function performScroll() {
  nextTick(() => {
    const anchor = bottomAnchor.value
    const container = messagesContainer.value

    if (anchor && typeof anchor.scrollIntoView === 'function') {
      anchor.scrollIntoView({ block: 'end', inline: 'nearest' })
      return
    }

    if (container) {
      container.scrollTop = container.scrollHeight
    }
  })
}

function scheduleScroll(force = false) {
  if (!force && !stickToBottom.value) return
  if (typeof window === 'undefined') return

  stickToBottom.value = true

  if (scrollFrameId !== null) {
    return
  }

  scrollFrameId = window.requestAnimationFrame(() => {
    scrollFrameId = null
    performScroll()
  })
}

function scrollToBottom(force = false) {
  scheduleScroll(force)
}

function syncMessagesResizeObserver() {
  if (messagesResizeObserver) {
    messagesResizeObserver.disconnect()
    messagesResizeObserver = null
  }

  if (typeof window === 'undefined' || typeof window.ResizeObserver === 'undefined') {
    return
  }

  const target = messagesList.value
  if (!target) {
    return
  }

  messagesResizeObserver = new ResizeObserver(() => {
    if (stickToBottom.value) {
      scheduleScroll(true)
    }
  })

  messagesResizeObserver.observe(target)
}

watch(theme, applyThemePreference, { immediate: true })

watch(
  () => chatStore.messages.length,
  async () => {
    await nextTick()
    syncMessagesResizeObserver()
    if (stickToBottom.value) {
      scheduleScroll(true)
    }
  },
  { immediate: true, flush: 'post' }
)

onMounted(async () => {
  try {
    await sessionStore.fetchSessions()
  } catch (error) {
    console.error('加载会话列表失败:', error)
    ElMessage.error('加载会话列表失败，请稍后重试。')
  }
})

onBeforeUnmount(() => {
  if (scrollFrameId !== null && typeof window !== 'undefined') {
    window.cancelAnimationFrame(scrollFrameId)
    scrollFrameId = null
  }

  if (messagesResizeObserver) {
    messagesResizeObserver.disconnect()
    messagesResizeObserver = null
  }
})
</script>

<style scoped>
.chat-layout {
  --chat-thread-width: 820px;

  display: flex;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(245, 158, 11, 0.16), transparent 26%),
    radial-gradient(circle at 82% 12%, rgba(79, 70, 229, 0.14), transparent 30%),
    radial-gradient(circle at right center, rgba(20, 184, 166, 0.10), transparent 30%),
    linear-gradient(140deg, #fafaf9 0%, #f8fafc 46%, #eef2ff 100%);
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: transparent;
}

.chat-header {
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 18px;
  background: transparent;
  border-bottom: 1px solid transparent;
  flex-shrink: 0;
}

.thread-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.thread-title-button {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: min(58vw, 34rem);
  gap: 7px;
  padding: 5px 8px;
  color: #44403c;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  font: inherit;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.thread-title-button:not(:disabled):hover {
  color: #1c1917;
  background: rgba(28, 25, 23, 0.05);
}

.thread-title-button--disabled {
  cursor: default;
}

.thread-title {
  min-width: 0;
  overflow: hidden;
  color: currentColor;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 800;
  line-height: 1.25;
}

.thread-title-edit-icon {
  flex: 0 0 auto;
  color: #a8a29e;
  font-size: 14px;
  opacity: 0;
  transition: opacity 0.16s ease, color 0.16s ease;
}

.thread-title-button:hover .thread-title-edit-icon {
  color: #78716c;
  opacity: 1;
}

.thread-title-input {
  width: min(58vw, 34rem);
  max-width: 34rem;
  height: 34px;
  padding: 0 10px;
  color: #292524;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid rgba(147, 197, 253, 0.70);
  border-radius: 10px;
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.10);
  font: inherit;
  font-size: 15px;
  font-weight: 800;
}

.header-status {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  color: #57534e;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  cursor: pointer;
  box-shadow: none;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, color 0.16s ease;
}

.theme-toggle:hover {
  color: #1c1917;
  background: rgba(28, 25, 23, 0.05);
  border-color: transparent;
  transform: translateY(-1px);
}

.theme-toggle:active {
  transform: translateY(0) scale(0.97);
}

.theme-icon {
  width: 17px;
  height: 17px;
}

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.messages-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 28px 28px 18px;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  width: min(100%, var(--chat-thread-width));
  margin: 0 auto;
}

.messages-bottom-anchor {
  width: 100%;
  height: 1px;
  flex: 0 0 auto;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 30px 12px;
}

.empty-content {
  width: min(100%, 860px);
  max-width: 860px;
  text-align: center;
  padding: 8px 0;
}

.empty-kicker {
  margin-bottom: 14px;
  color: #78716c;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: 0.16em;
}

.empty-content h1 {
  max-width: 720px;
  margin: 0 auto 14px;
  color: #1c1917;
  font-size: clamp(30px, 5vw, 48px);
  font-weight: 760;
  line-height: 1.16;
  letter-spacing: -0.04em;
}

.empty-content p {
  margin: 0 auto;
  max-width: 560px;
  color: #57534e;
  line-height: 1.7;
}

.empty-composer {
  margin-top: 30px;
}

.prompt-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  width: min(100%, 800px);
  margin: 16px auto 0;
}

.prompt-card {
  min-height: 38px;
  padding: 9px 12px;
  color: #57534e;
  text-align: center;
  background: rgba(255, 255, 255, 0.64);
  border: 1px solid rgba(214, 211, 209, 0.70);
  border-radius: 999px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.prompt-card:hover {
  transform: translateY(-2px);
  border-color: rgba(79, 70, 229, 0.32);
  box-shadow: 0 14px 30px rgba(79, 70, 229, 0.10);
}

.input-area {
  padding: 16px 28px 18px;
  flex-shrink: 0;
  background: linear-gradient(180deg, transparent, rgba(248, 250, 252, 0.86) 42%);
}

.sources-panel {
  width: min(390px, 34vw);
  min-width: 320px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.86);
  border-left: 1px solid rgba(214, 211, 209, 0.74);
  box-shadow: -18px 0 42px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(18px);
}

.sources-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 18px 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.92);
}

.sources-panel__kicker {
  color: #64748b;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.12em;
}

.sources-panel__header h2 {
  margin: 4px 0 0;
  color: #0f172a;
  font-size: 17px;
  font-weight: 850;
  line-height: 1.35;
}

.sources-panel__close {
  width: 32px;
  height: 32px;
  padding: 0;
  flex: 0 0 auto;
  color: #64748b;
  background: rgba(248, 250, 252, 0.8);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 999px;
  cursor: pointer;
  font-size: 22px;
  line-height: 1;
  transition: color 0.16s ease, background 0.16s ease, transform 0.16s ease;
}

.sources-panel__close:hover {
  color: #0f172a;
  background: #fff;
  transform: translateY(-1px);
}

.sources-panel__list {
  display: grid;
  align-content: start;
  gap: 10px;
  overflow-y: auto;
  padding: 14px;
}

.sources-panel__card {
  display: flex;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  color: #1f2937;
  text-decoration: none;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(203, 213, 225, 0.78);
  border-radius: 16px;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.sources-panel__card:hover {
  background: #fff;
  border-color: rgba(37, 99, 235, 0.32);
  box-shadow: 0 14px 28px rgba(37, 99, 235, 0.10);
  transform: translateY(-1px);
}

.sources-panel__favicon-wrap {
  position: relative;
  display: block;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border: 1px solid rgba(203, 213, 225, 0.78);
  border-radius: 999px;
  background: #fff;
  overflow: hidden;
}

.sources-panel__favicon-fallback {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  line-height: 1;
}

.sources-panel__favicon {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.sources-panel__body {
  min-width: 0;
}

.sources-panel__title {
  display: block;
  color: #0f172a;
  font-size: 13px;
  font-weight: 850;
  line-height: 1.45;
}

.sources-panel__domain {
  display: block;
  margin-top: 2px;
  overflow: hidden;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sources-panel__snippet {
  display: -webkit-box;
  margin-top: 7px;
  overflow: hidden;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.sources-panel__meta {
  display: block;
  margin-top: 8px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}












@media (max-width: 900px) {
  .chat-header {
    padding: 8px 12px;
  }

  .header-status {
    flex-shrink: 0;
  }

  .messages-area {
    padding: 18px 14px;
  }

  .prompt-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .input-area {
    padding: 12px 14px 14px;
  }

  .sources-panel {
    position: fixed;
    inset: 0 0 0 auto;
    z-index: 30;
    width: min(92vw, 390px);
    min-width: 0;
  }
}

@media (max-width: 560px) {
  .prompt-grid {
    grid-template-columns: 1fr;
  }
}
</style>
