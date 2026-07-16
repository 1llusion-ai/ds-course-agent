<template>
  <div class="chat-layout">
    <ChatSidebar :collapsed="sidebarCollapsed" @toggle-collapse="toggleSidebar" />

    <div class="chat-main">
      <header class="chat-header">
        <div class="thread-header-left">
          <button
            type="button"
            class="thread-sidebar-toggle"
            :aria-label="sidebarCollapsed ? '展开边栏' : '折叠边栏'"
            :title="sidebarCollapsed ? '展开边栏' : '折叠边栏'"
            @click="toggleSidebar"
          >
            <el-icon><Menu /></el-icon>
          </button>
          <span class="thread-title">{{ headerTitle }}</span>
        </div>
        <div class="header-status">
          <span class="status-pill">
            <span class="status-dot"></span>
            {{ chatStore.loading ? '回答生成中' : '随时可提问' }}
          </span>
        </div>
      </header>

      <div class="chat-content">
        <div ref="messagesContainer" class="messages-area">
          <div v-if="chatStore.messages.length === 0" class="empty-state">
            <div class="empty-content">
              <img src="/avatar/Assistant.png" alt="AI助手" class="robot-icon" />
              <h2>开始一段新的学习对话</h2>
              <p>
                可以直接提问课程概念、公式推导、案例理解，
                也可以让我帮你梳理最近卡住的知识点。
              </p>
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

        <div class="input-area">
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

const headerTitle = computed(() => sessionStore.currentSession?.title || '新对话')

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

    if (sessionCount > 0) {
      const first = sessionStore.sortedSessions[0]
      if (first) {
        sessionStore.setCurrentSession(first.id)
        router.replace(`/chat/${first.id}`)
      }
    }
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

.thread-sidebar-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  padding: 0;
  color: #78716c;
  background: transparent;
  border: 0;
  border-radius: 9px;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.thread-sidebar-toggle:hover {
  color: #292524;
  background: rgba(245, 245, 244, 0.88);
}

.thread-sidebar-toggle:active {
  transform: scale(0.96);
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

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 6px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.status-pill {
  gap: 7px;
  color: #0f766e;
  background: rgba(20, 184, 166, 0.10);
  border: 1px solid rgba(20, 184, 166, 0.16);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #14b8a6;
  box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.12);
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
  height: 100%;
}

.empty-content {
  max-width: 720px;
  text-align: center;
  padding: 34px;
  border-radius: 32px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(255, 255, 255, 0.68));
  border: 1px solid rgba(231, 229, 228, 0.9);
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.10);
  backdrop-filter: blur(18px);
}

.robot-icon {
  width: 68px;
  height: 68px;
  margin: 0 auto 16px;
  border-radius: 20px;
  object-fit: cover;
}

.empty-content h2 {
  margin: 0 0 10px;
  color: #1c1917;
  font-size: 22px;
  font-weight: 700;
}

.empty-content p {
  margin: 0 auto;
  max-width: 520px;
  color: #57534e;
  line-height: 1.7;
}

.prompt-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 22px;
}

.prompt-card {
  min-height: 54px;
  padding: 12px 14px;
  color: #334155;
  text-align: left;
  background: rgba(248, 250, 252, 0.84);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 16px;
  cursor: pointer;
  font: inherit;
  font-weight: 650;
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
    grid-template-columns: 1fr;
  }

  .input-area {
    padding: 12px 14px 14px;
  }
}
</style>
