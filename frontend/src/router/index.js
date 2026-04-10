import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import ProfileView from '../views/ProfileView.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'Chat', component: ChatView },
  { path: '/chat/:sessionId', name: 'ChatWithSession', component: ChatView },
  { path: '/profile', name: 'Profile', component: ProfileView },
]

export default createRouter({ history: createWebHistory(), routes })
