<template>
  <aside class="course-sidebar">
    <div class="sidebar-aurora sidebar-aurora--one"></div>
    <div class="sidebar-aurora sidebar-aurora--two"></div>

    <div class="sidebar-shell">
      <div class="sidebar-brand">
        <div class="brand-mark">
          <img src="/icon/thought_logo.png" alt="logo" />
        </div>
        <div class="brand-copy">
          <p>DS Tutor</p>
          <h2>数据科学助教</h2>
        </div>
      </div>

      <ProfileCard compact />

      <button class="new-chat-btn" type="button" @click="handleCreate">
        <span class="new-chat-btn__icon">
          <el-icon><Plus /></el-icon>
        </span>
        <span>
          <strong>新建聊天</strong>
          <small>开始一个新的学习问题</small>
        </span>
      </button>

      <div class="sidebar-stats">
        <div class="sidebar-stat">
          <span class="sidebar-stat__value">{{ sessionStore.sortedSessions.length }}</span>
          <span class="sidebar-stat__label">会话</span>
        </div>
        <div class="sidebar-stat">
          <span class="sidebar-stat__value">{{ activePendingCount }}</span>
          <span class="sidebar-stat__label">进行中</span>
        </div>
        <div class="sidebar-stat">
          <span class="sidebar-stat__value">{{ totalUnreadCount }}</span>
          <span class="sidebar-stat__label">未读</span>
        </div>
      </div>

      <div class="session-search">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m21 21-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" />
        </svg>
        <input v-model="searchQuery" type="search" placeholder="搜索会话标题" />
      </div>

      <div class="session-section-head">
        <span>近期对话</span>
        <span>{{ filteredSessions.length }}</span>
      </div>
    </div>

    <el-scrollbar class="session-scrollbar">
      <div class="session-list">
        <button
          v-for="session in filteredSessions"
          :key="session.id"
          class="session-card"
          :class="{
            'session-card--active': sessionStore.currentSessionId === session.id,
            'session-card--pending': chatStore.isSessionPending(session.id)
          }"
          type="button"
          @click="handleSessionClick(session.id, $event)"
        >
          <span class="session-card__glow"></span>
          <span class="session-card__icon">{{ sessionInitial(session.title) }}</span>

          <span class="session-card__content">
            <span class="session-card__topline">
              <span class="session-card__title">{{ session.title }}</span>
              <span v-if="sessionStore.unreadCounts[session.id]" class="unread-badge">
                {{ sessionStore.unreadCounts[session.id] }}
              </span>
            </span>
            <span class="session-card__meta">
              <span>消息 {{ session.message_count || 0 }} 条</span>
              <span>·</span>
              <span>{{ formatTime(session.updated_at) }}</span>
            </span>
            <span v-if="chatStore.isSessionPending(session.id)" class="session-status">
              <span class="session-spinner"></span>
              <span class="session-status-text">AI 正在回复</span>
            </span>
          </span>

          <el-dropdown trigger="click" @command="(cmd) => handleCommand(cmd, session)" size="small">
            <button class="session-menu-btn" type="button" @click.stop>
              <el-icon><MoreFilled /></el-icon>
            </button>
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
        </button>

        <div v-if="filteredSessions.length === 0" class="session-empty">
          <div class="session-empty__icon">⌕</div>
          <p>{{ searchQuery ? '没有找到匹配会话' : '还没有会话' }}</p>
          <button v-if="!searchQuery" type="button" @click="handleCreate">创建第一个会话</button>
        </div>
      </div>
    </el-scrollbar>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import ProfileCard from './ProfileCard.vue'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const sessionStore = useSessionStore()
const chatStore = useChatStore()
const searchQuery = ref('')

const filteredSessions = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) {
    return sessionStore.sortedSessions
  }
  return sessionStore.sortedSessions.filter(session =>
    String(session.title || '').toLowerCase().includes(query)
  )
})

const totalUnreadCount = computed(() => Object.values(sessionStore.unreadCounts || {})
  .reduce((total, count) => total + Number(count || 0), 0))

const activePendingCount = computed(() => sessionStore.sortedSessions
  .filter(session => chatStore.isSessionPending(session.id)).length)

function selectSession(id) {
  sessionStore.setCurrentSession(id)
  router.push(`/chat/${id}`)
}

function handleSessionClick(id, event) {
  // 如果点击来自 dropdown 内部（按钮或菜单项），不触发会话切换
  if (event.target.closest('.el-dropdown') || event.target.closest('.el-dropdown-menu')) {
    return
  }
  selectSession(id)
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

function sessionInitial(title = '') {
  const normalized = String(title || '').trim()
  if (!normalized) return '新'
  return normalized.slice(0, 1).toUpperCase()
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
.course-sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 320px;
  min-width: 320px;
  height: 100%;
  overflow: hidden;
  color: #e5e7eb;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.98) 0%, rgba(30, 41, 59, 0.96) 56%, rgba(15, 23, 42, 0.98) 100%);
  border-right: 1px solid rgba(148, 163, 184, 0.22);
  box-shadow: 22px 0 70px rgba(15, 23, 42, 0.16);
}

.sidebar-aurora {
  position: absolute;
  pointer-events: none;
  filter: blur(12px);
  opacity: 0.78;
}

.sidebar-aurora--one {
  top: -72px;
  left: -80px;
  width: 210px;
  height: 210px;
  background: radial-gradient(circle, rgba(79, 70, 229, 0.55), transparent 66%);
}

.sidebar-aurora--two {
  right: -110px;
  bottom: 24%;
  width: 230px;
  height: 230px;
  background: radial-gradient(circle, rgba(20, 184, 166, 0.32), transparent 68%);
}

.sidebar-shell {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 16px 12px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 4px 2px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.20), rgba(255, 255, 255, 0.06));
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 16px;
  box-shadow: 0 16px 36px rgba(79, 70, 229, 0.28);
}

.brand-mark img {
  width: 36px;
  height: 36px;
  object-fit: contain;
}

.brand-copy p {
  margin: 0 0 2px;
  color: #93c5fd;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.brand-copy h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 18px;
  font-weight: 850;
  letter-spacing: -0.02em;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 13px 14px;
  color: #fff;
  text-align: left;
  background: linear-gradient(135deg, #4f46e5 0%, #2563eb 54%, #0f766e 100%);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 20px;
  box-shadow: 0 20px 42px rgba(37, 99, 235, 0.28);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
}

.new-chat-btn:hover {
  transform: translateY(-2px);
  filter: saturate(1.08);
  box-shadow: 0 24px 48px rgba(37, 99, 235, 0.36);
}

.new-chat-btn__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.20);
  border-radius: 14px;
}

.new-chat-btn strong,
.new-chat-btn small {
  display: block;
}

.new-chat-btn strong {
  font-size: 14px;
  font-weight: 850;
}

.new-chat-btn small {
  margin-top: 2px;
  color: rgba(255, 255, 255, 0.76);
  font-size: 11px;
  font-weight: 600;
}

.sidebar-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.sidebar-stat {
  padding: 10px 8px;
  text-align: center;
  background: rgba(15, 23, 42, 0.34);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.sidebar-stat__value,
.sidebar-stat__label {
  display: block;
}

.sidebar-stat__value {
  color: #f8fafc;
  font-size: 18px;
  font-weight: 850;
  line-height: 1;
}

.sidebar-stat__label {
  margin-top: 5px;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 700;
}

.session-search {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 40px;
  padding: 0 12px;
  background: rgba(15, 23, 42, 0.38);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 15px;
}

.session-search svg {
  width: 16px;
  height: 16px;
  color: #94a3b8;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.session-search input {
  width: 100%;
  min-width: 0;
  color: #e2e8f0;
  background: transparent;
  border: 0;
  outline: none;
  font: inherit;
  font-size: 13px;
}

.session-search input::placeholder {
  color: #64748b;
}

.session-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 3px 0;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.session-scrollbar {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  padding: 0 10px 14px;
}

.session-list {
  display: grid;
  gap: 9px;
  padding: 0 6px 16px;
}

.session-card {
  position: relative;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 28px;
  gap: 10px;
  align-items: center;
  width: 100%;
  min-height: 76px;
  padding: 11px 8px 11px 11px;
  color: #cbd5e1;
  text-align: left;
  background: rgba(15, 23, 42, 0.34);
  border: 1px solid rgba(148, 163, 184, 0.13);
  border-radius: 20px;
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.session-card:hover {
  transform: translateY(-1px);
  background: rgba(30, 41, 59, 0.66);
  border-color: rgba(148, 163, 184, 0.24);
  box-shadow: 0 18px 34px rgba(15, 23, 42, 0.22);
}

.session-card--active {
  color: #f8fafc;
  background:
    linear-gradient(135deg, rgba(79, 70, 229, 0.40), rgba(37, 99, 235, 0.22) 54%, rgba(20, 184, 166, 0.18));
  border-color: rgba(129, 140, 248, 0.46);
  box-shadow: 0 20px 44px rgba(37, 99, 235, 0.24);
}

.session-card--pending {
  border-color: rgba(20, 184, 166, 0.34);
}

.session-card__glow {
  position: absolute;
  inset: auto -40px -54px 44px;
  height: 90px;
  background: radial-gradient(circle, rgba(20, 184, 166, 0.22), transparent 62%);
  opacity: 0;
  transition: opacity 0.16s ease;
}

.session-card:hover .session-card__glow,
.session-card--active .session-card__glow {
  opacity: 1;
}

.session-card__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  color: #dbeafe;
  font-size: 15px;
  font-weight: 850;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.88), rgba(20, 184, 166, 0.82));
  border-radius: 15px;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.22);
  z-index: 1;
}

.session-card__content {
  display: grid;
  gap: 5px;
  min-width: 0;
  z-index: 1;
}

.session-card__topline {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.session-card__title {
  overflow: hidden;
  color: inherit;
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-card__meta {
  display: flex;
  gap: 5px;
  align-items: center;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 650;
}

.unread-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 19px;
  height: 19px;
  padding: 0 6px;
  flex-shrink: 0;
  color: white;
  font-size: 11px;
  font-weight: 850;
  background: linear-gradient(135deg, #f97316, #ef4444);
  border-radius: 9999px;
  box-shadow: 0 8px 18px rgba(239, 68, 68, 0.28);
}

.session-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  width: fit-content;
  color: #5eead4;
  font-size: 11px;
  font-weight: 750;
}

.session-status-text {
  line-height: 1;
}

.session-menu-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  color: #94a3b8;
  background: rgba(15, 23, 42, 0.35);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 10px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
  z-index: 1;
}

.session-card:hover .session-menu-btn,
.session-menu-btn:focus {
  opacity: 1;
}

.session-menu-btn:hover {
  color: #f8fafc;
  background: rgba(30, 41, 59, 0.92);
}

.session-menu-btn .el-icon {
  font-size: 16px;
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
  border: 2px solid rgba(94, 234, 212, 0.22);
  border-top-color: currentColor;
  border-radius: 9999px;
  animation: session-spin 0.8s linear infinite;
}

.session-empty {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 180px;
  padding: 22px;
  color: #94a3b8;
  text-align: center;
  border: 1px dashed rgba(148, 163, 184, 0.20);
  border-radius: 22px;
}

.session-empty__icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  color: #c4b5fd;
  font-size: 22px;
  background: rgba(79, 70, 229, 0.16);
  border-radius: 16px;
}

.session-empty p {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
}

.session-empty button {
  padding: 8px 12px;
  color: #dbeafe;
  font: inherit;
  font-size: 12px;
  font-weight: 800;
  background: rgba(37, 99, 235, 0.28);
  border: 1px solid rgba(96, 165, 250, 0.24);
  border-radius: 999px;
  cursor: pointer;
}

@keyframes session-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 900px) {
  .course-sidebar {
    width: 286px;
    min-width: 286px;
  }
}
</style>
