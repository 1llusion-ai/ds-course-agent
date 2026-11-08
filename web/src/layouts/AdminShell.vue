<template>
  <div class="admin-shell">
    <aside class="admin-sidebar" aria-label="管理导航">
      <router-link to="/admin" class="admin-brand" aria-label="管理台首页">
        <img class="admin-brand__logo" src="/icon/thought_logo.png" alt="数字力" />
        <img class="admin-brand__mark" src="/icon/thought_mark.png" alt="数字力" />
      </router-link>
      <div class="admin-sidebar__label">管理工作区</div>
      <nav class="admin-nav">
        <router-link
          v-for="item in navigation"
          :key="item.path"
          :to="item.path"
          :title="item.label"
          :class="{ 'is-active': isActive(item.path) }"
          :aria-current="isActive(item.path) ? 'page' : undefined"
        >
          <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="admin-sidebar__bottom">
        <router-link to="/chat" title="返回学习空间">
          <el-icon aria-hidden="true"><Back /></el-icon>
          <span>返回学习空间</span>
        </router-link>
        <button
          type="button"
          :aria-label="isDarkTheme ? '切换浅色模式' : '切换深色模式'"
          :title="isDarkTheme ? '切换浅色模式' : '切换深色模式'"
          @click="toggleTheme"
        >
          <el-icon aria-hidden="true"><component :is="isDarkTheme ? Sunny : Moon" /></el-icon>
          <span>{{ isDarkTheme ? '浅色模式' : '深色模式' }}</span>
        </button>
        <div class="admin-identity">
          <span class="admin-avatar">{{ displayName.slice(0, 1).toUpperCase() }}</span>
          <div>
            <strong>{{ displayName }}</strong>
            <small>{{ roleLabels[authStore.user?.role] }}</small>
          </div>
        </div>
      </div>
    </aside>
    <main class="admin-workspace" aria-label="管理工作区">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Back, DataAnalysis, Histogram, Moon, Sunny, Tickets, User, Document } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../composables/useTheme'
import { roleLabels } from '../utils/admin'
import '../styles/admin.css'

const route = useRoute()
const authStore = useAuthStore()
const { isDarkTheme, toggleTheme } = useTheme()
const displayName = computed(() => authStore.user?.display_name || authStore.user?.student_id || '管理账号')
const navigation = computed(() => [
  { path: '/admin', label: '数据概览', icon: DataAnalysis },
  ...(authStore.isAdmin
    ? [
        { path: '/admin/users', label: '账号管理', icon: User },
        { path: '/admin/registration', label: '注册与邀请码', icon: Tickets }
      ]
    : []),
  { path: '/admin/statistics', label: '统计分析', icon: Histogram },
  ...(authStore.isAdmin ? [{ path: '/admin/audit', label: '操作记录', icon: Document }] : [])
])
function isActive(path) {
  return path === '/admin' ? route.path === path : route.path.startsWith(path)
}
</script>
