<template>
  <aside class="chat-sidebar" :class="{ 'chat-sidebar--collapsed': props.collapsed }">
    <div class="sidebar-brand-row">
      <button
        type="button"
        class="brand-icon-button"
        :class="{ 'brand-icon-button--logo': !props.collapsed }"
        :aria-label="props.collapsed ? '展开边栏' : '教学 Agent'"
        :title="props.collapsed ? '展开边栏' : '教学 Agent'"
        @click="handleBrandClick"
      >
        <img
          :src="props.collapsed ? '/icon/thought_mark.png' : '/icon/thought_logo.png'"
          alt=""
          class="brand-icon"
          :class="props.collapsed ? 'brand-icon--mark' : 'brand-icon--logo'"
        />
      </button>

      <div v-if="!props.collapsed" class="sidebar-brand-actions">
        <button
          ref="searchButtonRef"
          type="button"
          class="sidebar-search-button"
          :class="{ 'sidebar-search-button--active': searchOpen || searchQuery }"
          aria-label="搜索会话"
          title="搜索会话 · Ctrl K"
          @click="toggleSessionSearch"
        >
          <el-icon><Search /></el-icon>
        </button>

        <button
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
    </div>

    <div class="sidebar-top">
      <button
        type="button"
        class="new-chat-button"
        :class="{ 'new-chat-button--active': isNewChatActive }"
        :aria-current="isNewChatActive ? 'page' : undefined"
        :title="props.collapsed ? '开启新对话' : undefined"
        @click="handleCreate"
      >
        <span class="new-chat-button__icon">
          <el-icon><EditPen /></el-icon>
        </span>
        <span v-if="!props.collapsed" class="new-chat-button__text">开启新对话</span>
      </button>

      <label
        v-if="!props.collapsed && searchOpen"
        ref="searchContainerRef"
        class="session-search"
        aria-label="搜索会话"
      >
        <el-icon class="session-search__icon"><Search /></el-icon>
        <input
          ref="searchInputRef"
          v-model="searchQuery"
          class="session-search__input"
          type="search"
          placeholder="搜索会话"
          autocomplete="off"
          @keydown.esc.prevent.stop="closeSessionSearch"
        />
        <button
          type="button"
          class="session-search__close"
          aria-label="关闭搜索"
          title="关闭搜索"
          @click="closeSessionSearch"
        >
          ×
        </button>
      </label>
    </div>

    <nav class="sidebar-primary-nav" aria-label="学习空间">
      <button
        type="button"
        class="utility-entry"
        :class="{ 'utility-entry--active': isKnowledgeMapActive }"
        :aria-current="isKnowledgeMapActive ? 'page' : undefined"
        title="知识地图"
        @click="router.push('/knowledge-map')"
      >
        <span class="utility-entry__icon"><el-icon><Connection /></el-icon></span>
        <span v-if="!props.collapsed" class="utility-entry__body">
          <span class="utility-entry__title">知识地图</span>
          <span class="utility-entry__meta">探索知识关系与学习目标</span>
        </span>
      </button>
      <button
        type="button"
        class="utility-entry"
        :class="{ 'utility-entry--active': isProfileActive }"
        :aria-current="isProfileActive ? 'page' : undefined"
        title="学习画像"
        @click="handleProfileOpen"
      >
        <span class="utility-entry__icon utility-entry__icon--profile">
          <svg class="profile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <rect x="4" y="4.5" width="16" height="15" rx="3.2" stroke-width="1.8" />
            <circle cx="10" cy="10" r="2.1" stroke-width="1.8" />
            <path stroke-linecap="round" stroke-width="1.8" d="M7.2 16.1c.7-1.4 1.7-2.1 2.8-2.1s2.1.7 2.8 2.1" />
            <path stroke-linecap="round" stroke-width="1.8" d="M15.3 9h1.8M15.3 12h1.8M15.3 15h1.8" />
          </svg>
        </span>
        <span v-if="!props.collapsed" class="utility-entry__body">
          <span class="utility-entry__title">学习画像</span>
          <span class="utility-entry__meta">{{ profileSummaryText }}</span>
        </span>
      </button>
    </nav>

    <el-scrollbar v-if="!props.collapsed" class="session-scroll">
      <div v-if="showSessionEmpty" class="session-empty">
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
          </div>

          <div
            v-for="session in group.sessions"
            :key="session.id"
            class="session-wrapper"
            :class="{
              'session-wrapper--active': activeSessionId === session.id,
              'session-wrapper--pinned': sessionStore.isPinned(session.id),
              'session-wrapper--editing': editingSessionId === session.id
            }"
            :aria-current="activeSessionId === session.id ? 'page' : undefined"
            @click="handleSessionClick(session.id, $event)"
          >
            <span class="session-leading">
              <span class="session-leading__dot"></span>
            </span>

            <div class="session-body">
              <div class="session-row">
                <input
                  v-if="editingSessionId === session.id"
                  :ref="el => setSessionRenameInputRef(el, session.id)"
                  v-model="editingTitle"
                  class="session-title-input"
                  type="text"
                  aria-label="重命名会话"
                  autocomplete="off"
                  @click.stop
                  @keydown.enter.prevent="commitSessionRename(session)"
                  @keydown.esc.prevent.stop="cancelSessionRename"
                  @blur="commitSessionRename(session)"
                />
                <span v-else class="session-title">
                  {{ session.title }}
                </span>
                <span
                  v-if="editingSessionId !== session.id && chatStore.isSessionPending(session.id)"
                  class="session-status"
                  title="进行中"
                >
                  <span class="session-spinner"></span>
                  <span class="session-status-text">进行中</span>
                </span>
              </div>

            </div>

            <div v-if="editingSessionId !== session.id" class="session-actions">
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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

const emit = defineEmits(['toggle-collapse', 'new-chat'])

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const chatStore = useChatStore()
const profileStore = useProfileStore()
const searchQuery = ref('')
const searchOpen = ref(false)
const searchInputRef = ref(null)
const searchButtonRef = ref(null)
const searchContainerRef = ref(null)
const editingSessionId = ref(null)
const editingTitle = ref('')
const sessionRenameSaving = ref(false)
const sessionRenameInputRefs = new Map()

const isChatRoute = computed(() => ['Chat', 'ChatWithSession'].includes(route.name))
const isNewChatActive = computed(() => isChatRoute.value && !route.params.sessionId)
const activeSessionId = computed(() => (
  isChatRoute.value ? route.params.sessionId || null : null
))
const isProfileActive = computed(() => route.name === 'Profile')
const isKnowledgeMapActive = computed(() => route.name === 'KnowledgeMap')

const hasSearchQuery = computed(() => Boolean(normalizeSearchText(searchQuery.value)))

const sessionDialogClasses = {
  overlay: 'session-dialog-overlay',
  deleteDialog: 'session-dialog session-dialog--delete',
  cancelButton: 'session-dialog__cancel',
  dangerConfirmButton: 'session-dialog__confirm session-dialog__confirm--danger'
}

const sessionDialogBaseOptions = {
  modalClass: sessionDialogClasses.overlay,
  cancelButtonClass: sessionDialogClasses.cancelButton,
  closeOnClickModal: true,
  distinguishCancelAndClose: true
}

const filteredSessions = computed(() => {
  const query = normalizeSearchText(searchQuery.value)
  if (!query) {
    return sessionStore.sortedSessions
  }

  return sessionStore.sortedSessions.filter(session => {
    const title = normalizeSearchText(session.title)
    return title.includes(query)
  })
})

const groupedSessions = computed(() => {
  if (hasSearchQuery.value) {
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

const showSessionEmpty = computed(() => hasSearchQuery.value && groupedSessions.value.length === 0)

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

function focusSearchInput() {
  nextTick(() => {
    searchInputRef.value?.focus()
  })
  window.setTimeout(() => {
    searchInputRef.value?.focus()
  }, 0)
}

function openSessionSearch() {
  if (props.collapsed) {
    emit('toggle-collapse')
  }
  searchOpen.value = true
  focusSearchInput()
}

function closeSessionSearch() {
  searchQuery.value = ''
  searchOpen.value = false
}

function toggleSessionSearch() {
  if (searchOpen.value) {
    closeSessionSearch()
    return
  }
  openSessionSearch()
}

function handleGlobalKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key?.toLowerCase() === 'k') {
    event.preventDefault()
    openSessionSearch()
  }
}

function handleGlobalPointerDown(event) {
  if (!searchOpen.value || normalizeSearchText(searchQuery.value)) {
    return
  }

  const target = event.target
  if (!(target instanceof Node)) {
    return
  }

  if (searchContainerRef.value?.contains(target) || searchButtonRef.value?.contains(target)) {
    return
  }

  closeSessionSearch()
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
  closeSessionSearch()
  cancelSessionRename()
  emit('new-chat')
}

function setSessionRenameInputRef(el, sessionId) {
  if (el) {
    sessionRenameInputRefs.set(sessionId, el)
  } else {
    sessionRenameInputRefs.delete(sessionId)
  }
}

function focusSessionRenameInput(sessionId) {
  nextTick(() => {
    const input = sessionRenameInputRefs.get(sessionId)
    input?.focus()
    input?.select()
  })
}

function startSessionRename(session) {
  if (!session?.id) return
  editingSessionId.value = session.id
  editingTitle.value = session.title || ''
  focusSessionRenameInput(session.id)
}

function cancelSessionRename() {
  editingSessionId.value = null
  editingTitle.value = ''
}

async function commitSessionRename(session) {
  if (sessionRenameSaving.value || editingSessionId.value !== session?.id) {
    return
  }

  const nextTitle = editingTitle.value.trim()
  const previousTitle = String(session.title || '').trim()

  if (!nextTitle || nextTitle === previousTitle) {
    cancelSessionRename()
    return
  }

  sessionRenameSaving.value = true
  try {
    await sessionStore.updateSession(session.id, { title: nextTitle })
    cancelSessionRename()
  } catch (error) {
    console.error('重命名失败:', error)
    ElMessage.error('重命名失败，请稍后再试')
    focusSessionRenameInput(session.id)
  } finally {
    sessionRenameSaving.value = false
  }
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm(
      '删除后将无法恢复此对话记录。',
      '删除这个对话？',
      {
        type: 'warning',
        ...sessionDialogBaseOptions,
        customClass: sessionDialogClasses.deleteDialog,
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: sessionDialogClasses.dangerConfirmButton
      }
    )
    await sessionStore.deleteSession(id)
    ElMessage.success('会话已删除')
    if (route.params.sessionId === id) {
      router.push('/chat')
    }
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
    startSessionRename(session)
  }
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
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('pointerdown', handleGlobalPointerDown)

  if (!profileStore.summary && !profileStore.loading) {
    profileStore.fetchSummary().catch(error => {
      console.warn('加载学习快照失败:', error)
    })
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('pointerdown', handleGlobalPointerDown)
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
  background: transparent;
  border-right: 1px solid rgba(214, 211, 209, 0.34);
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

.sidebar-brand-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.brand-icon-button,
.sidebar-search-button,
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
  transition: background 0.16s ease, color 0.16s ease;
}

.brand-icon-button--logo {
  justify-content: flex-start;
  width: 132px;
  padding: 0 4px;
}

.brand-icon-button:hover,
.sidebar-search-button:hover,
.sidebar-search-button--active,
.sidebar-collapse-button:hover {
  color: #292524;
  background: rgba(28, 25, 23, 0.06);
}

.brand-icon-button:active,
.sidebar-search-button:active,
.sidebar-collapse-button:active {
  transform: scale(0.96);
}

.brand-icon {
  object-fit: contain;
}

.brand-icon--mark {
  width: 38px;
  height: 38px;
  border-radius: 12px;
}

.brand-icon--logo {
  width: 124px;
  height: 38px;
  object-position: left center;
}

.sidebar-collapse-button .el-icon {
  font-size: 17px;
}

.sidebar-search-button .el-icon {
  font-size: 17px;
}

.sidebar-collapse-icon {
  width: 18px;
  height: 18px;
}



.sidebar-top {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 6px 10px 12px;
}

.chat-sidebar--collapsed .sidebar-top {
  align-items: center;
  padding: 6px 0 10px;
}

.new-chat-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 44px;
  gap: 7px;
  padding: 0 14px;
  color: #2563eb;
  background: rgba(239, 246, 255, 0.92);
  border: 1px solid rgba(147, 197, 253, 0.58);
  border-radius: 999px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82), 0 8px 22px rgba(37, 99, 235, 0.08);
  cursor: pointer;
  font: inherit;
  transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.chat-sidebar--collapsed .new-chat-button {
  justify-content: center;
  width: 42px;
  min-height: 42px;
  padding: 0;
  border-radius: 14px;
}

.new-chat-button:hover {
  color: #1d4ed8;
  background: #e8f1ff;
  border-color: rgba(96, 165, 250, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9), 0 10px 26px rgba(37, 99, 235, 0.12);
  transform: translateY(-1px);
}

.new-chat-button--active {
  color: #1d4ed8;
  background: #e8f1ff;
  border-color: rgba(96, 165, 250, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9), 0 10px 26px rgba(37, 99, 235, 0.12);
}

.new-chat-button:active {
  transform: translateY(0) scale(0.985);
}

.new-chat-button__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  color: currentColor;
  background: transparent;
  border-radius: 999px;
  box-shadow: none;
}

.chat-sidebar--collapsed .new-chat-button__icon {
  width: 28px;
  height: 28px;
}

.new-chat-button__text {
  flex: 0 1 auto;
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
  text-align: center;
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
  background: rgba(28, 25, 23, 0.04);
  border: 1px solid transparent;
  border-radius: 11px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
}

.session-search:focus-within {
  background: rgba(255, 255, 255, 0.72);
  border-color: rgba(168, 162, 158, 0.32);
  box-shadow: none;
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

.session-search__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  padding: 0;
  color: #a8a29e;
  background: transparent;
  border: 0;
  border-radius: 999px;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: background 0.16s ease, color 0.16s ease;
}

.session-search__close:hover {
  color: #44403c;
  background: rgba(28, 25, 23, 0.06);
}

.session-scroll {
  flex: 1;
  padding: 2px 8px 14px;
}

:deep(.session-scroll .el-scrollbar__view) {
  padding: 0 2px 8px;
}

.session-group {
  margin-bottom: 10px;
}

.session-group__title {
  display: flex;
  align-items: center;
  padding: 7px 6px 5px;
  color: #a8a29e;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.session-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 6px 8px;
  margin-bottom: 2px;
  overflow: hidden;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 11px;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease;
}

.session-wrapper:hover {
  background: rgba(28, 25, 23, 0.05);
}

.session-wrapper--active {
  background: rgba(28, 25, 23, 0.075);
  border-color: transparent;
  box-shadow: none;
}

.session-wrapper--pinned:not(.session-wrapper--active) {
  background: rgba(28, 25, 23, 0.035);
  border-color: transparent;
}

.session-wrapper--editing {
  background: rgba(255, 255, 255, 0.62);
  border-color: rgba(147, 197, 253, 0.50);
}

.session-leading {
  display: none;
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
  background: rgba(87, 83, 78, 0.10);
}

.session-wrapper--active .session-leading__dot {
  background: #78716c;
  box-shadow: 0 0 0 4px rgba(87, 83, 78, 0.10);
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
  color: #3f3f3f;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.35;
}

.session-title-input {
  width: 100%;
  min-width: 0;
  height: 28px;
  padding: 0 8px;
  color: #292524;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(147, 197, 253, 0.72);
  border-radius: 8px;
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.10);
  font: inherit;
  font-size: 13px;
  font-weight: 650;
}

.session-wrapper--active .session-title {
  color: #1f1f1f;
  font-weight: 750;
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
  color: #10a37f;
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
  border-radius: 9px;
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
  background: rgba(28, 25, 23, 0.07);
  border-color: transparent;
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
  background: transparent;
  border: 1px dashed rgba(214, 211, 209, 0.72);
  border-radius: 14px;
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

.sidebar-primary-nav {
  flex-shrink: 0;
  padding: 0 10px 10px;
  border-bottom: 1px solid rgba(231, 229, 228, 0.38);
}

.chat-sidebar--collapsed .sidebar-primary-nav {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 0 10px;
}

.sidebar-footer {
  flex-shrink: 0;
  padding: 10px 12px 14px;
  background: transparent;
  border-top: 1px solid rgba(231, 229, 228, 0.28);
}

.chat-sidebar--collapsed .sidebar-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: auto;
  padding: 8px 0 12px;
}

:global(html.theme-dark) .sidebar-primary-nav {
  border-bottom-color: var(--dark-border-soft);
}

.utility-entry {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 42px;
  gap: 9px;
  padding: 7px 9px;
  margin-top: 4px;
  color: #44403c;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 11px;
  cursor: pointer;
  font: inherit;
  transition: background 0.16s ease, color 0.16s ease;
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
  background: rgba(28, 25, 23, 0.05);
}

.utility-entry--active {
  color: #1d4ed8;
  background: rgba(37, 99, 235, 0.09);
  border-color: rgba(147, 197, 253, 0.28);
}

.utility-entry--active .utility-entry__icon {
  color: #2563eb;
  background: rgba(147, 197, 253, 0.24);
}

.utility-entry--muted {
  color: #78716c;
}

.utility-entry__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  color: #78716c;
  background: rgba(28, 25, 23, 0.05);
  border-radius: 9px;
}

.chat-sidebar--collapsed .utility-entry__icon {
  width: 28px;
  height: 28px;
}

.utility-entry__icon--profile {
  color: #57534e;
  background: rgba(28, 25, 23, 0.05);
}

.profile-icon {
  width: 18px;
  height: 18px;
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

:global(html.theme-dark) .new-chat-button--active {
  color: var(--dark-text) !important;
  background: var(--dark-hover) !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  box-shadow: none !important;
}

:global(html.theme-dark) .utility-entry--active {
  color: var(--dark-text) !important;
  background: var(--dark-hover) !important;
  border-color: var(--dark-border) !important;
}

:global(html.theme-dark) .utility-entry--active .utility-entry__icon {
  color: var(--dark-text) !important;
  background: rgba(255, 255, 255, 0.10) !important;
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
