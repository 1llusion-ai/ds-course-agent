<template>
  <div class="chat-layout">
    <ChatSidebar :collapsed="sidebarCollapsed" @toggle-collapse="toggleSidebar" />

    <div class="chat-main">
      <header class="chat-header">
        <div class="thread-header-left">
          <span class="thread-title">{{ headerTitle }}</span>
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
        <div ref="messagesContainer" class="messages-area">
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
                class="empty-composer"
                @send="handleSend"
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

          <div v-else class="messages-list">
            <ChatMessage
              v-for="(message, index) in chatStore.messages"
              :key="`${message.timestamp || index}-${index}`"
              :message="message"
            />
          </div>
        </div>

        <div v-if="chatStore.messages.length > 0" class="input-area">
          <ChatInput :loading="chatStore.loading" @send="handleSend" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ChatInput from '../components/ChatInput.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatSidebar from '../components/ChatSidebar.vue'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'
import { useSessionStore } from '../stores/session'

const route = useRoute()
const router = useRouter()
const messagesContainer = ref(null)

const sessionStore = useSessionStore()
const chatStore = useChatStore()
const profileStore = useProfileStore()
const sidebarCollapsed = ref(readSidebarCollapsedPreference())
const theme = ref(readThemePreference())

const headerTitle = computed(() => sessionStore.currentSession?.title || '新对话')
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

  scrollToBottom()
}

async function handleSend(message) {
  const streamOptions = { onProgress: scrollToBottom }
  const currentSessionId = sessionStore.currentSessionId
  let targetSessionId = currentSessionId
  let shouldRefreshTitle = false

  if (!currentSessionId) {
    const newSession = await sessionStore.createSession()
    targetSessionId = newSession.id
    shouldRefreshTitle = true
    chatStore.setActiveSession(newSession.id)
    await router.push(`/chat/${newSession.id}`)
    await chatStore.sendMessage(newSession.id, message, undefined, streamOptions)
  } else {
    shouldRefreshTitle = sessionStore.shouldAutoTitle(currentSessionId)
    chatStore.setActiveSession(currentSessionId)
    await chatStore.sendMessage(currentSessionId, message, undefined, streamOptions)
  }

  if (shouldRefreshTitle) {
    try {
      await sessionStore.fetchSessions()
      if (targetSessionId) {
        sessionStore.setCurrentSession(targetSessionId)
      }
    } catch (error) {
      console.error('同步会话标题失败:', error)
    }
  }

  await profileStore.fetchSummary()
  scrollToBottom()
}

function handleStarterPrompt(prompt) {
  if (chatStore.loading) return
  handleSend(prompt)
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

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(
      'ds-course-agent.sidebarCollapsed',
      sidebarCollapsed.value ? 'true' : 'false'
    )
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

watch(theme, applyThemePreference, { immediate: true })

onMounted(async () => {
  try {
    await sessionStore.fetchSessions()
  } catch (error) {
    console.error('加载会话列表失败:', error)
    ElMessage.error('加载会话列表失败，请稍后重试。')
  }
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background:
    radial-gradient(circle at top left, rgba(245, 158, 11, 0.16), transparent 26%),
    radial-gradient(circle at 82% 12%, rgba(79, 70, 229, 0.14), transparent 30%),
    radial-gradient(circle at right center, rgba(20, 184, 166, 0.10), transparent 30%),
    linear-gradient(140deg, #fafaf9 0%, #f8fafc 46%, #eef2ff 100%);
}

.chat-header {
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 18px;
  background: rgba(255, 255, 255, 0.68);
  border-bottom: 1px solid rgba(214, 211, 209, 0.62);
  backdrop-filter: blur(16px);
  flex-shrink: 0;
}

.thread-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.thread-title {
  max-width: min(58vw, 34rem);
  overflow: hidden;
  color: #78716c;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
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
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(214, 211, 209, 0.72);
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(28, 25, 23, 0.06);
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, color 0.16s ease;
}

.theme-toggle:hover {
  color: #1c1917;
  background: rgba(255, 255, 255, 0.92);
  border-color: rgba(148, 163, 184, 0.38);
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
  overflow: hidden;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 28px 28px 18px;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  width: min(100%, 1120px);
  margin: 0 auto;
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
}

@media (max-width: 560px) {
  .prompt-grid {
    grid-template-columns: 1fr;
  }
}
</style>
