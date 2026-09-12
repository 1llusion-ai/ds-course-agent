import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '../layouts/AppShell.vue'
import ChatView from '../views/ChatView.vue'
import ProfileView from '../views/ProfileView.vue'
import LoginView from '../views/LoginView.vue'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/login', name: 'Login', component: LoginView, meta: { public: true } },
  {
    path: '/',
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      { path: 'chat', name: 'Chat', component: ChatView },
      { path: 'chat/:sessionId', name: 'ChatWithSession', component: ChatView },
      { path: 'profile', name: 'Profile', component: ProfileView },
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

  if (!authStore.initialized) {
    try {
      await authStore.fetchMe()
    } catch (error) {
      // Unauthenticated is handled below without storing any client-side token.
    }
  }

  const isPublicRoute = to.matched.some(record => record.meta.public)
  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)

  if (isPublicRoute) {
    if (to.path === '/login' && authStore.isAuthenticated) {
      return typeof to.query.redirect === 'string' ? to.query.redirect : '/chat'
    }
    return true
  }

  if (requiresAuth && !authStore.isAuthenticated) {
    return {
      path: '/login',
      query: { redirect: to.fullPath }
    }
  }

  return true
})

export default router
