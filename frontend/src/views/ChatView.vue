<template>
  <div class="chat-layout">
    <ChatSidebar />

    <div class="chat-main">
      <!-- Header -->
      <header class="chat-header">
        <div class="header-content">
          <div class="logo">🎓</div>
          <div>
            <h1>智能课程助教</h1>
            <p>数据科学基础</p>
          </div>
        </div>
      </header>

      <!-- Chat Content -->
      <div class="chat-content">
        <!-- Messages Area -->
        <div class="messages-area" ref="messagesContainer">
          <!-- Empty State -->
          <div v-if="chatStore.messages.length === 0" class="empty-state">
            <div class="empty-content">
              <div class="robot-icon">🤖</div>
              <h2>你好！我是你的课程助教</h2>
              <p>我可以帮你理解课程概念、解答疑难问题。<br>在下方输入问题开始对话吧！</p>
            </div>
          </div>

          <!-- Messages List -->
          <div v-else class="messages-list">
            <ChatMessage v-for="(m, i) in chatStore.messages" :key="i" :message="m" />
          </div>
        </div>

        <!-- Input Area -->
        <div class="input-area">
          <ChatInput :loading="chatStore.loading" @send="handleSend" />
        </div>
      </div>
    </div>

    <!-- Profile Card (Desktop) -->
    <div class="profile-sidebar">
      <ProfileCard />
    </div>
  </div>
</template>

<script setup>
import { onMounted, watch, ref, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import ChatSidebar from '../components/ChatSidebar.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import ProfileCard from '../components/ProfileCard.vue'

import { useSessionStore } from '../stores/session'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'

const route = useRoute()
const router = useRouter()
const messagesContainer = ref(null)

const sessionStore = useSessionStore()
const chatStore = useChatStore()
const profileStore = useProfileStore()

watch(() => route.params.sessionId, (newId) => {
  if (newId) {
    if (sessionStore.currentSessionId !== newId) {
      sessionStore.setCurrentSession(newId)
    }
    return
  }

  if (sessionStore.sessions.length > 0) {
    const first = sessionStore.sortedSessions[0]
    if (first) {
      sessionStore.setCurrentSession(first.id)
      router.replace(`/chat/${first.id}`)
    }
  }
}, { immediate: true })

watch(() => sessionStore.currentSessionId, (newId) => {
  if (!newId) return
  if (chatStore.activeSessionId !== newId) {
    loadSession(newId)
  }
})

async function loadSession(sessionId) {
  sessionStore.setCurrentSession(sessionId)
  chatStore.setActiveSession(sessionId)

  try {
    await chatStore.fetchHistory(sessionId)
  } catch (err) {
    console.error('加载历史记录失败:', err)
    ElMessage.error('加载会话历史失败，请重试')
  }
  scrollToBottom()
}

async function handleSend(message) {
  const sessionId = sessionStore.currentSessionId
  if (!sessionId) {
    const newSession = await sessionStore.createSession(message.slice(0, 20))
    chatStore.setActiveSession(newSession.id)
    await chatStore.sendMessage(newSession.id, message)

    // 若用户在回答期间已切换到其他会话，不再强制跳回新会话
    if (sessionStore.currentSessionId === newSession.id) {
      await router.push(`/chat/${newSession.id}`)
    }
  } else {
    if (sessionStore.shouldAutoTitle(sessionId)) {
      try {
        await sessionStore.updateSession(sessionId, { title: message.slice(0, 20) })
      } catch (err) {
        console.error('更新会话标题失败:', err)
      }
    }
    chatStore.setActiveSession(sessionId)
    await chatStore.sendMessage(sessionId, message)
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

onMounted(() => sessionStore.fetchSessions())
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
  background: linear-gradient(135deg, #fafaf9 0%, #f5f5f4 100%);
  min-width: 0;
}

.chat-header {
  height: 64px;
  background: white;
  border-bottom: 1px solid #e7e5e4;
  display: flex;
  align-items: center;
  padding: 0 24px;
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
  background: linear-gradient(135deg, #6366f1 0%, #7c3aed 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.chat-header h1 {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
  color: #1c1917;
}

.chat-header p {
  font-size: 12px;
  color: #78716c;
  margin: 0;
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

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.empty-content {
  text-align: center;
}

.robot-icon {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: linear-gradient(135deg, #6366f1 0%, #7c3aed 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  margin: 0 auto 16px;
}

.empty-content h2 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 8px;
  color: #1c1917;
}

.empty-content p {
  color: #78716c;
  line-height: 1.6;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.input-area {
  padding: 16px 24px;
  background: transparent;
  flex-shrink: 0;
}

.profile-sidebar {
  width: 320px;
  padding: 24px;
  background: transparent;
  display: none;
}

@media (min-width: 1024px) {
  .profile-sidebar {
    display: block;
  }
}
</style>
