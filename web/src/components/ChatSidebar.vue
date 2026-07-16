<template>
  <aside class="chat-sidebar" :class="{ 'chat-sidebar--collapsed': props.collapsed }">
    <div class="sidebar-brand-row">
      <button
        type="button"
        class="brand-icon-button"
        :aria-label="props.collapsed ? '展开边栏' : '教学 Agent'"
        :title="props.collapsed ? '展开边栏' : '教学 Agent'"
        @click="handleBrandClick"
      >
        <img src="/icon/thought_mark.png" alt="" class="brand-icon" />
      </button>

      <button
        v-if="!props.collapsed"
        type="button"
        class="sidebar-collapse-button"
        aria-label="折叠边栏"
        title="折叠边栏"
        @click="handleSidebarToggle"
      >
        <svg class="sidebar-collapse-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-width="2" d="M5 7h14M5 12h14M5 17h14" />
        </svg>
      </button>
    </div>

    <div class="sidebar-top">
      <button
        type="button"
        class="new-chat-button"
        :title="props.collapsed ? '新建聊天' : undefined"
        @click="handleCreate"
      >
        <span class="new-chat-button__icon">
          <el-icon><Plus /></el-icon>
        </span>
        <span v-if="!props.collapsed" class="new-chat-button__text">新建聊天</span>
        <span v-if="!props.collapsed" class="new-chat-button__hint">New</span>
      </button>

      <label v-if="!props.collapsed" class="session-search" aria-label="搜索会话">
        <el-icon class="session-search__icon"><Search /></el-icon>
        <input
          v-model="searchQuery"
          class="session-search__input"
          type="search"
          placeholder="搜索会话"
          autocomplete="off"
        />
      </label>
    </div>

    <div v-if="!props.collapsed" class="session-list-heading">
      <span>最近对话</span>
      <span>{{ filteredSessionCount }} 个</span>
    </div>

    <el-scrollbar v-if="!props.collapsed" class="session-scroll">
      <div v-if="groupedSessions.length === 0" class="session-empty">
        <div class="session-empty__icon">
          <el-icon><Search /></el-icon>
        </div>
        <p>没有匹配的会话</p>
        <span>换个关键词试试</span>
      </div>

      <template v-else>
        <section
          v-for="group in groupedSessions"
          :key="group.key"
          class="session-group"
        >
          <div class="session-group__title">
            <span>{{ group.label }}</span>
            <span>{{ group.sessions.length }}</span>
          </div>

          <div
            v-for="session in group.sessions"
            :key="session.id"
            class="session-wrapper"
            :class="{
              'session-wrapper--active': sessionStore.currentSessionId === session.id,
              'session-wrapper--pinned': sessionStore.isPinned(session.id)
            }"
            @click="handleSessionClick(session.id, $event)"
          >
            <span class="session-leading">
              <span class="session-leading__dot"></span>
            </span>

            <div class="session-body">
              <div class="session-row">
                <span class="session-title">
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

              <span class="session-meta">
                <template v-if="sessionStore.isPinned(session.id)">置顶 · </template>
                消息 {{ session.message_count || 0 }} 条 · {{ formatTime(session.updated_at) }}
              </span>
            </div>

            <div class="session-actions">
              <span
                v-if="sessionStore.unreadCounts[session.id]"
                class="unread-badge"
              >
                {{ sessionStore.unreadCounts[session.id] }}
              </span>
              <el-dropdown
                trigger="click"
                popper-class="session-action-menu"
                @command="(cmd) => handleCommand(cmd, session)"
                size="small"
              >
                <button
                  type="button"
                  class="session-menu-btn"
                  aria-label="会话操作"
                  title="会话操作"
                  @click.stop
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 12h.01M12 12h.01M18 12h.01" />
                  </svg>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="pin">
                      <span class="menu-item-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.9" d="m14.5 4.5 5 5-3.2 1.1-3.8 3.8.3 3.5-1 1-3.7-3.7-3.1 3.1-1.3-1.3 3.1-3.1-3.7-3.7 1-1 3.5.3 3.8-3.8 1.1-3.2Z" />
                        </svg>
                      </span>
                      <span>{{ sessionStore.isPinned(session.id) ? '取消置顶' : '置顶' }}</span>
                    </el-dropdown-item>
                    <el-dropdown-item command="rename">
                      <span class="menu-item-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.9" d="M4 20h4.2L18.7 9.5a2.1 2.1 0 0 0 0-3l-1.2-1.2a2.1 2.1 0 0 0-3 0L4 15.8V20Z" />
                          <path stroke-linecap="round" stroke-width="1.9" d="M13.5 6.5l4 4" />
                        </svg>
                      </span>
                      <span>重命名</span>
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" divided class="menu-item-danger">
                      <span class="menu-item-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.9" d="M6 7h12M10 7V5h4v2m-6 3v8m4-8v8m4-8v8M8 7l.6 13h6.8L16 7" />
                        </svg>
                      </span>
                      <span>删除</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </section>
      </template>
    </el-scrollbar>

    <div class="sidebar-footer">
      <button type="button" class="utility-entry" title="学习快照" @click="handleProfileOpen">
        <span class="utility-entry__icon utility-entry__icon--profile">
          <el-icon><TrendCharts /></el-icon>
        </span>
        <span v-if="!props.collapsed" class="utility-entry__body">
          <span class="utility-entry__title">学习快照</span>
          <span class="utility-entry__meta">{{ profileSummaryText }}</span>
        </span>
      </button>

      <button
        type="button"
        class="utility-entry utility-entry--muted"
        title="设置"
        @click="handleSettingsClick"
      >
        <span class="utility-entry__icon">
          <el-icon><Setting /></el-icon>
        </span>
        <span v-if="!props.collapsed" class="utility-entry__body">
          <span class="utility-entry__title">设置</span>
          <span class="utility-entry__meta">后续开放</span>
        </span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'
import { useSessionStore } from '../stores/session'

const props = defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-collapse'])

const router = useRouter()
const sessionStore = useSessionStore()
const chatStore = useChatStore()
const profileStore = useProfileStore()
const searchQuery = ref('')

const filteredSessions = computed(() => {
  const query = normalizeSearchText(searchQuery.value)
  if (!query) {
    return sessionStore.sortedSessions
  }

  return sessionStore.sortedSessions.filter(session => {
    const title = normalizeSearchText(session.title)
    const updated = normalizeSearchText(formatTime(session.updated_at))
    return title.includes(query) || updated.includes(query)
  })
})

const filteredSessionCount = computed(() => filteredSessions.value.length)

const groupedSessions = computed(() => {
  if (normalizeSearchText(searchQuery.value)) {
    return filteredSessions.value.length
      ? [{ key: 'search', label: '搜索结果', sessions: filteredSessions.value }]
      : []
  }

  const groups = []
  const byKey = new Map()
  const pinnedSessions = []
  const regularSessions = []

  for (const session of filteredSessions.value) {
    if (sessionStore.isPinned(session.id)) {
      pinnedSessions.push(session)
    } else {
      regularSessions.push(session)
    }
  }

  if (pinnedSessions.length) {
    groups.push({
      key: 'pinned',
      label: '置顶',
      sessions: pinnedSessions
    })
  }

  for (const session of regularSessions) {
    const bucket = getSessionBucket(session.updated_at)
    if (!byKey.has(bucket.key)) {
      byKey.set(bucket.key, {
        key: bucket.key,
        label: bucket.label,
        sessions: []
      })
      groups.push(byKey.get(bucket.key))
    }
    byKey.get(bucket.key).sessions.push(session)
  }

  return groups
})

const profileSummaryText = computed(() => {
  const summary = profileStore.summary
  if (!summary) {
    return profileStore.loading ? '同步中...' : '查看学习状态'
  }

  const weakCount = Array.isArray(summary.weak_spots) ? summary.weak_spots.length : 0
  const pendingCount = Array.isArray(summary.pending_weak_spots) ? summary.pending_weak_spots.length : 0
  const recentCount = Array.isArray(summary.recent_concepts) ? summary.recent_concepts.length : 0
  const totalWeak = weakCount + pendingCount

  if (totalWeak || recentCount) {
    return `薄弱点 ${totalWeak} · 近期关注 ${recentCount}`
  }

  return '暂无明显薄弱点'
})

function selectSession(id) {
  sessionStore.setCurrentSession(id)
  router.push(`/chat/${id}`)
}

function handleProfileOpen() {
  router.push('/profile')
}

function handleSettingsClick() {
  ElMessage.info('设置页后续开放')
}

function handleSidebarToggle() {
  emit('toggle-collapse')
}

function handleBrandClick() {
  if (props.collapsed) {
    emit('toggle-collapse')
  }
}

function handleSessionClick(id, event) {
  // 如果点击来自 dropdown 内部（按钮或菜单项），不触发会话切换
  if (event.target.closest('.el-dropdown') || event.target.closest('.el-dropdown-menu')) {
    return
  }
  selectSession(id)
}

function handleCreate() {
  sessionStore.setCurrentSession(null)
  chatStore.setActiveSession(null)
  router.push('/chat')
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm(
      '删除后将无法恢复此对话记录。',
      '删除这个对话？',
      {
        type: 'warning',
        customClass: 'session-delete-dialog',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'session-delete-dialog__confirm',
        cancelButtonClass: 'session-delete-dialog__cancel',
        closeOnClickModal: true,
        distinguishCancelAndClose: true
      }
    )
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
  if (cmd === 'pin') {
    sessionStore.togglePin(session.id)
    ElMessage.success(sessionStore.isPinned(session.id) ? '已置顶' : '已取消置顶')
  } else if (cmd === 'delete') {
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
  if (Number.isNaN(date.getTime())) {
    return ''
  }

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

function normalizeSearchText(value) {
  return String(value || '').trim().toLowerCase()
}

function getSessionBucket(timeStr) {
  if (!timeStr) {
    return { key: 'unknown', label: '未记录时间' }
  }

  const date = new Date(timeStr)
  const now = new Date()

  if (Number.isNaN(date.getTime())) {
    return { key: 'unknown', label: '未记录时间' }
  }

  if (isSameDate(date, now)) {
    return { key: 'today', label: '今天' }
  }

  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (isSameDate(date, yesterday)) {
    return { key: 'yesterday', label: '昨天' }
  }

  const diffDays = Math.floor((startOfDay(now) - startOfDay(date)) / 86_400_000)
  if (diffDays < 7) {
    return { key: 'week', label: '近 7 天' }
  }

  return { key: 'earlier', label: '更早' }
}

function isSameDate(left, right) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

onMounted(() => {
  if (!profileStore.summary && !profileStore.loading) {
    profileStore.fetchSummary().catch(error => {
      console.warn('加载学习快照失败:', error)
    })
  }
})
</script>

<style scoped>
.chat-sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: 18rem;
  height: 100%;
  overflow: hidden;
  color: #292524;
  background:
    radial-gradient(circle at 14% 0%, rgba(79, 70, 229, 0.08), transparent 28%),
    linear-gradient(180deg, #ffffff 0%, #fbfaf8 100%);
  border-right: 1px solid rgba(214, 211, 209, 0.82);
  transition: width 0.18s ease;
}

.chat-sidebar--collapsed {
  width: 4rem;
}


.sidebar-brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 54px;
  padding: 10px 10px 8px;
}

.chat-sidebar--collapsed .sidebar-brand-row {
  justify-content: center;
  padding: 10px 0 6px;
}

.brand-icon-button,
.sidebar-collapse-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  padding: 0;
  color: #57534e;
  background: transparent;
  border: 0;
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.brand-icon-button:hover,
.sidebar-collapse-button:hover {
  color: #312e81;
  background: rgba(99, 102, 241, 0.08);
}

.brand-icon-button:active,
.sidebar-collapse-button:active {
  transform: scale(0.96);
}

.brand-icon {
  width: 38px;
  height: 38px;
  object-fit: contain;
  border-radius: 12px;
}

.sidebar-collapse-button .el-icon {
  font-size: 17px;
}

.sidebar-collapse-icon {
  width: 18px;
  height: 18px;
}



.sidebar-top {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 14px 12px;
}

.chat-sidebar--collapsed .sidebar-top {
  align-items: center;
  padding: 6px 0 10px;
}

.new-chat-button {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 42px;
  gap: 10px;
  padding: 9px 10px;
  color: #312e81;
  background: linear-gradient(180deg, #ffffff 0%, #f7f7ff 100%);
  border: 1px solid rgba(99, 102, 241, 0.20);
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(79, 70, 229, 0.08);
  cursor: pointer;
  font: inherit;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.chat-sidebar--collapsed .new-chat-button {
  justify-content: center;
  width: 40px;
  min-height: 40px;
  padding: 0;
  border-radius: 13px;
}

.new-chat-button:hover {
  transform: translateY(-1px);
  border-color: rgba(79, 70, 229, 0.34);
  box-shadow: 0 14px 28px rgba(79, 70, 229, 0.12);
}

.new-chat-button__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  color: white;
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  border-radius: 10px;
  box-shadow: 0 8px 18px rgba(79, 70, 229, 0.24);
}

.chat-sidebar--collapsed .new-chat-button__icon {
  width: 28px;
  height: 28px;
}

.new-chat-button__text {
  flex: 1;
  font-size: 14px;
  font-weight: 700;
  text-align: left;
}

.new-chat-button__hint {
  padding: 2px 7px;
  color: #6366f1;
  background: rgba(99, 102, 241, 0.08);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.session-search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 0 11px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(214, 211, 209, 0.74);
  border-radius: 14px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
}

.session-search:focus-within {
  background: #ffffff;
  border-color: rgba(99, 102, 241, 0.34);
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.08);
}

.session-search__icon {
  flex-shrink: 0;
  color: #a8a29e;
}

.session-search__input {
  width: 100%;
  min-width: 0;
  color: #292524;
  background: transparent;
  border: 0;
  outline: none;
  font: inherit;
  font-size: 13px;
}

.session-search__input::placeholder {
  color: #a8a29e;
}

.session-list-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 16px 8px;
  color: #78716c;
  font-size: 12px;
  font-weight: 700;
}

.session-list-heading span:first-child {
  letter-spacing: 0.08em;
}

.session-scroll {
  flex: 1;
  padding: 0 10px 14px;
}

:deep(.session-scroll .el-scrollbar__view) {
  padding: 0 2px 8px;
}

.session-group {
  margin-bottom: 12px;
}

.session-group__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px 6px;
  color: #a8a29e;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.session-wrapper {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 9px;
  min-height: 58px;
  padding: 10px 8px;
  margin-bottom: 3px;
  overflow: hidden;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 15px;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.session-wrapper:hover {
  background: rgba(255, 255, 255, 0.74);
  border-color: rgba(231, 229, 228, 0.92);
  box-shadow: 0 10px 22px rgba(28, 25, 23, 0.05);
  transform: translateY(-1px);
}

.session-wrapper--active {
  background:
    linear-gradient(90deg, rgba(99, 102, 241, 0.12), rgba(255, 255, 255, 0.88) 50%),
    #ffffff;
  border-color: rgba(99, 102, 241, 0.22);
  box-shadow:
    inset 3px 0 0 #6366f1,
    0 12px 24px rgba(79, 70, 229, 0.08);
}

.session-wrapper--pinned:not(.session-wrapper--active) {
  background: rgba(255, 255, 255, 0.44);
  border-color: rgba(99, 102, 241, 0.10);
}

.session-leading {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  margin-top: 1px;
  border-radius: 8px;
  background: rgba(231, 229, 228, 0.55);
}

.session-leading__dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #a8a29e;
}

.session-wrapper--active .session-leading {
  background: rgba(99, 102, 241, 0.12);
}

.session-wrapper--active .session-leading__dot {
  background: #6366f1;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.10);
}

.session-wrapper--pinned .session-leading__dot {
  background: #f59e0b;
}

.session-body {
  min-width: 0;
  flex: 1;
}

.session-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.session-title {
  min-width: 0;
  overflow: hidden;
  color: #44403c;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}

.session-wrapper--active .session-title {
  color: #312e81;
}

.session-meta {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #a8a29e;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}

.session-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  min-height: 24px;
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  color: #78716c;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.session-wrapper:hover .session-menu-btn,
.session-wrapper--active .session-menu-btn,
.session-menu-btn:focus {
  opacity: 1;
}

.session-menu-btn:hover,
.session-menu-btn:focus {
  color: #292524;
  background: rgba(245, 245, 244, 0.90);
  border-color: rgba(214, 211, 209, 0.78);
}

.session-menu-btn svg {
  width: 18px;
  height: 18px;
}

:global(.session-action-menu) {
  min-width: 150px;
  padding: 6px;
  border-radius: 14px;
  border: 1px solid rgba(214, 211, 209, 0.88);
  box-shadow: 0 18px 48px rgba(28, 25, 23, 0.14);
}

:global(.session-action-menu .el-dropdown-menu) {
  padding: 0;
  background: transparent;
  border: 0;
  box-shadow: none;
}

:global(.session-action-menu .el-dropdown-menu__item) {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 34px;
  padding: 8px 10px;
  color: #44403c;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
}

:global(.session-action-menu .el-dropdown-menu__item:not(.is-disabled):focus),
:global(.session-action-menu .el-dropdown-menu__item:not(.is-disabled):hover) {
  color: #1d4ed8;
  background: rgba(37, 99, 235, 0.08);
}

:global(.session-action-menu .el-dropdown-menu__item--divided) {
  margin-top: 5px;
  border-top-color: rgba(231, 229, 228, 0.92);
}

:global(.session-action-menu .menu-item-icon) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  color: currentColor;
}

:global(.session-action-menu .menu-item-icon svg) {
  width: 17px;
  height: 17px;
}

:global(.session-action-menu .menu-item-danger) {
  color: #dc2626;
}

:global(.session-action-menu .menu-item-danger:not(.is-disabled):focus),
:global(.session-action-menu .menu-item-danger:not(.is-disabled):hover) {
  color: #b91c1c;
  background: rgba(239, 68, 68, 0.08);
}

.session-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid rgba(79, 70, 229, 0.18);
  border-top-color: currentColor;
  border-radius: 9999px;
  animation: session-spin 0.8s linear infinite;
}

.session-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  margin: 10px 4px;
  padding: 24px 16px;
  color: #a8a29e;
  text-align: center;
  background: rgba(255, 255, 255, 0.58);
  border: 1px dashed rgba(214, 211, 209, 0.92);
  border-radius: 18px;
}

.session-empty__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  margin-bottom: 10px;
  color: #78716c;
  background: rgba(245, 245, 244, 0.95);
  border-radius: 12px;
}

.session-empty p {
  margin: 0 0 4px;
  color: #57534e;
  font-weight: 700;
}

.session-empty span {
  font-size: 12px;
}

.sidebar-footer {
  flex-shrink: 0;
  padding: 10px 12px 14px;
  background:
    linear-gradient(180deg, rgba(251, 250, 248, 0), rgba(251, 250, 248, 0.96) 22%),
    rgba(251, 250, 248, 0.92);
  border-top: 1px solid rgba(231, 229, 228, 0.76);
}

.chat-sidebar--collapsed .sidebar-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: auto;
  padding: 8px 0 12px;
}

.utility-entry {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 46px;
  gap: 10px;
  padding: 8px 9px;
  margin-top: 4px;
  color: #44403c;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 15px;
  cursor: pointer;
  font: inherit;
  transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.chat-sidebar--collapsed .utility-entry {
  justify-content: center;
  width: 40px;
  min-height: 40px;
  height: 40px;
  padding: 0;
  margin: 4px 0;
  border-radius: 13px;
}

.utility-entry:hover {
  transform: translateY(-1px);
  background: rgba(255, 255, 255, 0.78);
  border-color: rgba(231, 229, 228, 0.92);
  box-shadow: 0 10px 22px rgba(28, 25, 23, 0.05);
}

.utility-entry--muted {
  color: #78716c;
}

.utility-entry__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  color: #78716c;
  background: rgba(245, 245, 244, 0.95);
  border-radius: 12px;
}

.chat-sidebar--collapsed .utility-entry__icon {
  width: 30px;
  height: 30px;
}

.utility-entry__icon--profile {
  color: #4f46e5;
  background: rgba(99, 102, 241, 0.10);
}

.utility-entry__body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}

.utility-entry__title {
  color: #292524;
  font-size: 13px;
  font-weight: 750;
  line-height: 1.2;
}

.utility-entry--muted .utility-entry__title {
  color: #57534e;
}

.utility-entry__meta {
  overflow: hidden;
  color: #a8a29e;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  line-height: 1.2;
}
































@keyframes session-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
