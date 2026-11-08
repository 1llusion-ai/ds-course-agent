import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '../layouts/AppShell.vue'
import ChatView from '../views/ChatView.vue'
import ProfileView from '../views/ProfileView.vue'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import SettingsView from '../views/SettingsView.vue'
import { useAuthStore } from '../stores/auth'
import { authenticatedRedirect } from '../utils/authRedirect'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/login', name: 'Login', component: LoginView, meta: { public: true } },
  { path: '/register', name: 'Register', component: RegisterView, meta: { public: true } },
  {
    path: '/admin',
    component: () => import('../layouts/AdminShell.vue'),
    meta: { requiresAuth: true, management: true },
    children: [
      { path: '', name: 'AdminOverview', component: () => import('../views/admin/AdminOverviewView.vue') },
      { path: 'users', name: 'AdminUsers', component: () => import('../views/admin/AdminUsersView.vue'), meta: { adminOnly: true } },
      { path: 'users/:userId', name: 'AdminUser', component: () => import('../views/admin/AdminUserView.vue'), meta: { adminOnly: true } },
      { path: 'registration', name: 'AdminRegistration', component: () => import('../views/admin/AdminRegistrationView.vue'), meta: { adminOnly: true } },
      { path: 'statistics', name: 'AdminStatistics', component: () => import('../views/admin/AdminStatisticsView.vue') },
      { path: 'audit', name: 'AdminAudit', component: () => import('../views/admin/AdminAuditView.vue'), meta: { adminOnly: true } }
    ]
  },
  {
    path: '/',
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      { path: 'chat', name: 'Chat', component: ChatView },
      { path: 'chat/:sessionId', name: 'ChatWithSession', component: ChatView },
      { path: 'profile', name: 'Profile', component: ProfileView },
      { path: 'settings', name: 'Settings', component: SettingsView },
      { path: 'knowledge-map', name: 'KnowledgeMap', component: () => import('../views/KnowledgeMapView.vue') },
      { path: 'assessments', name: 'Assessments', component: () => import('../views/AssessmentListView.vue') },
      { path: 'assessments/:assessmentId', name: 'AssessmentTake', component: () => import('../views/AssessmentTakeView.vue') },
      { path: 'assessments/:assessmentId/result', name: 'AssessmentResult', component: () => import('../views/AssessmentResultView.vue') }
    ]
  }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  if (!authStore.initialized || to.matched.some(record => record.meta.management)) {
    try {
      await authStore.fetchMe()
    } catch (error) {
      // Unauthenticated is handled below without storing any client-side token.
    }
  }

  const isPublicRoute = to.matched.some(record => record.meta.public)
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)

  if (isPublicRoute) {
    if ((to.path === '/login' || to.path === '/register') && authStore.isAuthenticated) {
      return authenticatedRedirect(to.query.redirect)
    }
    return true
  }

  if (requiresAuth && !authStore.isAuthenticated) {
    return {
      path: '/login',
      query: { redirect: to.fullPath }
    }
  }

  if (to.matched.some(record => record.meta.management) && !authStore.canViewAdmin) return '/chat'
  if (to.matched.some(record => record.meta.adminOnly) && !authStore.isAdmin) return '/admin'

  return true
})

export default router
