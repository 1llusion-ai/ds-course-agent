<template>
  <aside class="w-72 bg-white border-r border-stone-200 flex flex-col h-full">
    <div class="sidebar-top p-4">
      <ProfileCard compact />
      <el-button type="primary" class="w-full" size="large" @click="handleCreate">
        <el-icon class="mr-2"><Plus /></el-icon>
        新建聊天
      </el-button>
    </div>

    <el-scrollbar class="flex-1 px-3 pb-4">
      <div
        v-for="session in sessionStore.sortedSessions"
        :key="session.id"
        class="session-wrapper rounded-lg p-3 mb-1 cursor-pointer transition-all"
        :class="sessionStore.currentSessionId === session.id
          ? 'bg-indigo-50 border-l-4 border-indigo-500'
          : 'hover:bg-stone-50 border-l-4 border-transparent'"
        @click="selectSession(session.id)"
      >
        <div class="flex justify-between items-center gap-3">
          <div class="flex items-center gap-2 min-w-0">
            <span
              class="font-medium text-sm truncate"
              :class="sessionStore.currentSessionId === session.id ? 'text-indigo-900' : 'text-stone-700'"
            >
              {{ session.title }}
            </span>
            <span
              v-if="chatStore.isSessionPending(session.id)"
              class="session-status"
              title="进行中"
            >
              <span class="session-spinner"></span>
              <span class="session-status-text">进行中</span>
            </span>
          </div>

          <div class="flex items-center gap-1">
            <span
              v-if="sessionStore.unreadCounts[session.id]"
              class="unread-badge"
            >
              {{ sessionStore.unreadCounts[session.id] }}
            </span>
            <el-dropdown trigger="click" @command="(cmd) => handleCommand(cmd, session)" size="small">
              <el-button type="default" link size="small" class="session-menu-btn">
                <el-icon><MoreFilled /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">
                    <el-icon><Edit /></el-icon>
                    <span>重命名</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="delete">
                    <el-icon><Delete /></el-icon>
                    <span>删除</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <div class="text-xs text-stone-400 mt-1">
          消息 {{ session.message_count || 0 }} 条 · {{ formatTime(session.updated_at) }}
        </div>
      </div>
    </el-scrollbar>
  </aside>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import ProfileCard from './ProfileCard.vue'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const sessionStore = useSessionStore()
const chatStore = useChatStore()

function selectSession(id) {
  sessionStore.setCurrentSession(id)
  router.push(`/chat/${id}`)
}

async function handleCreate() {
  const session = await sessionStore.createSession()
  ElMessage.success('会话已创建')
  router.push(`/chat/${session.id}`)
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除这个会话吗？', '删除会话', { type: 'warning' })
    await sessionStore.deleteSession(id)
    ElMessage.success('会话已删除')
    router.push('/chat')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error('删除会话失败，请稍后再试')
    }
  }
}

async function handleCommand(cmd, session) {
  if (cmd === 'delete') {
    await handleDelete(session.id)
  } else if (cmd === 'rename') {
    try {
      const { value } = await ElMessageBox.prompt(
        '请输入新的会话标题',
        '重命名会话',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          inputValue: session.title,
          inputPattern: /\S+/,
          inputErrorMessage: '标题不能为空',
        }
      )
      await sessionStore.updateSession(session.id, { title: value.trim() })
      ElMessage.success('会话已重命名')
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error('重命名失败，请稍后再试')
      }
    }
  }
}

function formatTime(timeStr) {
  if (!timeStr) {
    return ''
  }

  const date = new Date(timeStr)
  const now = new Date()
  const diff = now - date

  if (diff < 60_000) {
    return '刚刚'
  }
  if (diff < 3_600_000) {
    return `${Math.floor(diff / 60_000)} 分钟前`
  }
  if (diff < 86_400_000) {
    return `${Math.floor(diff / 3_600_000)} 小时前`
  }
  return `${Math.floor(diff / 86_400_000)} 天前`
}
</script>

<style scoped>
.sidebar-top {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

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

.session-menu-btn {
  opacity: 0;
  transition: opacity 0.15s;
}

.session-wrapper:hover .session-menu-btn,
.session-menu-btn:focus {
  opacity: 1;
}

.session-menu-btn .el-icon {
  font-size: 16px;
  color: #57534e;
}

:deep(.el-dropdown-menu__item) {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
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
