import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, ApiError, onUnauthorized, setCsrfToken } from '../api/client'
import type { Session } from '../types/domain'
import { useAccountsStore } from './accounts'
import { useMarketStore } from './market'

export const useSessionStore = defineStore('session', () => {
  const session = ref<Session | null>(null)
  const initialized = ref(false)
  const error = ref('')
  let pending: Promise<void> | null = null
  const isAdmin = computed(() => session.value?.role === 'ADMIN')
  function clear(): void { session.value = null; setCsrfToken(''); useAccountsStore().reset(); useMarketStore().reset() }
  onUnauthorized(clear)
  function assign(value: Session): void { if (session.value?.workspace.id !== value.workspace.id || session.value?.user.id !== value.user.id) { useAccountsStore().reset(); useMarketStore().reset() }; session.value = value; setCsrfToken(value.csrf_token); error.value = '' }
  async function hydrate(): Promise<void> {
    if (initialized.value) return
    if (pending) return pending
    pending = (async () => {
      try { assign(await api<Session>('/auth/session')) }
      catch (cause) { if (!(cause instanceof ApiError && cause.status === 401)) error.value = cause instanceof Error ? cause.message : '登录服务不可用' }
      finally { initialized.value = true; pending = null }
    })()
    return pending
  }
  async function login(email: string, password: string): Promise<void> {
    assign(await api<Session>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }))
    initialized.value = true
  }
  async function logout(): Promise<void> { await api('/auth/logout', { method: 'POST' }); clear() }
  return { session, initialized, error, isAdmin, hydrate, login, logout }
})
