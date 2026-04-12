<template>
  <div class="chat-layout">
    <ChatSidebar />

    <div class="chat-main">
      <header class="chat-header">
        <div class="header-content">
          <div class="logo">DS</div>
          <div>
            <h1>数据科学导论教学Agent</h1>
            <p>数据科学导论</p>
          </div>
        </div>
      </header>

      <div class="chat-content">
        <div ref="messagesContainer" class="messages-area">
          <div v-if="chatStore.messages.length === 0" class="empty-state">
            <div class="empty-content">
              <div class="robot-icon">AI</div>
              <h2>开始一段新的学习对话</h2>
              <p>
                可以直接提问课程概念、公式推导、案例理解，
                也可以让我帮你梳理最近卡住的知识点。
              </p>
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
import { nextTick, onMounted, ref, watch } from 'vue'
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

  if (!currentSessionId) {
    const newSession = await sessionStore.createSession(message.slice(0, 20))
    chatStore.setActiveSession(newSession.id)
    await router.push(`/chat/${newSession.id}`)
    await chatStore.sendMessage(newSession.id, message, undefined, streamOptions)
  } else {
    if (sessionStore.shouldAutoTitle(currentSessionId)) {
      try {
        await sessionStore.updateSession(currentSessionId, { title: message.slice(0, 20) })
      } catch (error) {
        console.error('更新会话标题失败:', error)
      }
    }

    chatStore.setActiveSession(currentSessionId)
    await chatStore.sendMessage(currentSessionId, message, undefined, streamOptions)
  }

  await profileStore.fetchSummary()
  scrollToBottom()
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
    radial-gradient(circle at top left, rgba(245, 158, 11, 0.12), transparent 24%),
    radial-gradient(circle at right center, rgba(59, 130, 246, 0.1), transparent 28%),
    linear-gradient(140deg, #fafaf9 0%, #f5f5f4 46%, #f1f5f9 100%);
}

.chat-header {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.88);
  border-bottom: 1px solid rgba(214, 211, 209, 0.9);
  backdrop-filter: blur(18px);
  flex-shrink: 0;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #1d4ed8 0%, #f97316 100%);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.24);
}

.chat-header h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #1c1917;
}

.chat-header p {
  margin: 0;
  font-size: 12px;
  color: #78716c;
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
  padding: 24px;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.empty-content {
  max-width: 420px;
  text-align: center;
  padding: 28px 32px;
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(231, 229, 228, 0.9);
  box-shadow: 0 18px 40px rgba(28, 25, 23, 0.06);
}

.robot-icon {
  width: 68px;
  height: 68px;
  margin: 0 auto 16px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #0f766e 0%, #f59e0b 100%);
}

.empty-content h2 {
  margin: 0 0 10px;
  color: #1c1917;
  font-size: 22px;
  font-weight: 700;
}

.empty-content p {
  margin: 0;
  color: #57534e;
  line-height: 1.7;
}

.input-area {
  padding: 16px 24px;
  flex-shrink: 0;
}
</style>
