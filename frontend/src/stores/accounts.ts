import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { Account, AccountInput } from '../types/domain'

export const useAccountsStore = defineStore('accounts', () => {
  const accounts = ref<Account[]>([])
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  function reset(): void { generation += 1; accounts.value = []; error.value = ''; loading.value = false }
  async function refresh(): Promise<void> {
    const current = ++generation
    loading.value = true; error.value = ''
    try { const values = await api<Account[]>('/accounts'); if (current === generation) accounts.value = values }
    catch (cause) { if (current === generation) { accounts.value = []; error.value = cause instanceof Error ? cause.message : '账户加载失败' } }
    finally { if (current === generation) loading.value = false }
  }
  async function create(payload: AccountInput): Promise<void> {
    await api('/accounts', { method: 'POST', body: JSON.stringify(payload) }); await refresh()
  }
  async function archive(id: string): Promise<void> { await api('/accounts/' + id, { method: 'DELETE' }); await refresh() }
  return { accounts, loading, error, reset, refresh, create, archive }
})
