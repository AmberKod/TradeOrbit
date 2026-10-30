import { createRouter, createWebHistory } from 'vue-router'
import { useSessionStore } from '../stores/session'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/', name: 'overview', component: () => import('../views/OverviewView.vue'), meta: { title: '资产总览' } },
    { path: '/accounts', name: 'accounts', component: () => import('../views/AccountsView.vue'), meta: { title: '账户连接' } },
    { path: '/system', name: 'system', component: () => import('../views/SystemView.vue'), meta: { title: '系统状态' } },
    { path: '/audit', name: 'audit', component: () => import('../views/AuditView.vue'), meta: { title: '操作审计', admin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.beforeEach(async (to) => {
  const store = useSessionStore(); await store.hydrate()
  if (!to.meta.public && !store.session) return { name: 'login' }
  if (to.name === 'login' && store.session) return { name: 'overview' }
  if (to.meta.admin && !store.isAdmin) return { name: 'overview' }
})
