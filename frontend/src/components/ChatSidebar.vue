<template>
  <aside class="w-72 bg-white border-r border-stone-200 flex flex-col h-full">
    <div class="p-4">
      <el-button type="primary" class="w-full" size="large" @click="handleCreate">
        <el-icon class="mr-2"><Plus /></el-icon>新建会话
      </el-button>
    </div>

    <el-scrollbar class="flex-1 px-3">
      <div
        v-for="session in sessionStore.sortedSessions"
        :key="session.id"
        class="rounded-lg p-3 mb-1 cursor-pointer transition-all"
        :class="sessionStore.currentSessionId === session.id
          ? 'bg-indigo-50 border-l-4 border-indigo-500'
          : 'hover:bg-stone-50 border-l-4 border-transparent'"
        @click="selectSession(session.id)"
      >
        <div class="flex justify-between items-center gap-3">
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-medium text-sm truncate"
              :class="sessionStore.currentSessionId === session.id ? 'text-indigo-900' : 'text-stone-700'"
            >{{ session.title }}</span>
            <span v-if="chatStore.isSessionPending(session.id)" class="session-status" title="进行中">
              <span class="session-spinner"></span>
              <span class="session-status-text">进行中</span>
            </span>
          </div>
          <div class="flex items-center gap-1">
            <span v-if="sessionStore.unreadCounts[session.id]" class="unread-badge">{{ sessionStore.unreadCounts[session.id] }}</span>
            <el-button v-show="sessionStore.currentSessionId === session.id" type="danger" link size="small" @click.stop="handleDelete(session.id)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="text-xs text-stone-400 mt-1">💬 {{ session.message_count || 0 }} 条 · {{ formatTime(session.updated_at) }}</div>
      </div>
    </el-scrollbar>

    <div class="p-4 border-t border-stone-200">
      <el-button text class="w-full justify-start" @click="$router.push('/profile')">
        <el-icon class="mr-2"><DataAnalysis /></el-icon>学习画像
      </el-button>
    </div>
  </aside>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { useChatStore } from '../stores/chat'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const sessionStore = useSessionStore()
const chatStore = useChatStore()

onMounted(() => sessionStore.fetchSessions())

function selectSession(id) {
  sessionStore.setCurrentSession(id)
  router.push(`/chat/${id}`)
}

async function handleCreate() {
  const session = await sessionStore.createSession()
  ElMessage.success('创建成功')
  router.push(`/chat/${session.id}`)
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除？', '提示', { type: 'warning' })
    await sessionStore.deleteSession(id)
    ElMessage.success('已删除')
    router.push('/chat')
  } catch {}
}

function formatTime(timeStr) {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now - date
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff/60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff/3600000)}小时前`
  return `${Math.floor(diff/86400000)}天前`
}
</script>

<style scoped>
.unread-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  font-size: 11px;
  font-weight: 600;
  color: white;
  background: #ef4444;
  border-radius: 9999px;
}

.session-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  color: #4f46e5;
  font-size: 11px;
  font-weight: 500;
}

.session-status-text {
  line-height: 1;
}

.session-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid rgba(79, 70, 229, 0.18);
  border-top-color: currentColor;
  border-radius: 9999px;
  animation: session-spin 0.8s linear infinite;
}

@keyframes session-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
