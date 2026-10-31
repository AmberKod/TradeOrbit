import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { Account, AccountInput } from '../types/domain'
import type { AccountSnapshot } from '../types/accounts'

export const useAccountsStore = defineStore('accounts', () => {
  const accounts = ref<Account[]>([])
  const snapshots = ref<Record<string, AccountSnapshot>>({})
  const syncing = ref<Record<string, boolean>>({})
  const snapshotLoading = ref<Record<string, boolean>>({})
  const loading = ref(false), error = ref('')
  let generation = 0, epoch = 0
  const revisions: Record<string, number> = {}
  function invalidateSnapshot(id: string): void {
    revisions[id] = (revisions[id] ?? 0) + 1
    delete snapshots.value[id]
    delete syncing.value[id]
    delete snapshotLoading.value[id]
  }
  function reset(): void {
    generation += 1; epoch += 1
    accounts.value = []; snapshots.value = {}; syncing.value = {}; snapshotLoading.value = {}
    error.value = ''; loading.value = false
  }
  async function refresh(): Promise<void> {
    const current = ++generation
    loading.value = true; error.value = ''
    try {
      const values = await api<Account[]>('/accounts')
      if (current !== generation) return
      for (const old of accounts.value) {
        const next = values.find(a => a.id === old.id)
        if (!next || next.credential_version !== old.credential_version) invalidateSnapshot(old.id)
      }
      accounts.value = values
    } catch (cause) {
      if (current === generation) { accounts.value = []; snapshots.value = {}; error.value = cause instanceof Error ? cause.message : '账户加载失败' }
    } finally { if (current === generation) loading.value = false }
  }
  async function create(payload: AccountInput): Promise<void> {
    const current = epoch
    await api('/accounts', { method: 'POST', body: JSON.stringify(payload) })
    if (current === epoch) await refresh()
  }
  async function archive(id: string): Promise<void> {
    const current = epoch
    await api('/accounts/' + id, { method: 'DELETE' })
    if (current === epoch) { invalidateSnapshot(id); await refresh() }
  }
  async function readSnapshot(id: string): Promise<void> {
    if (syncing.value[id]) return
    const current = epoch, revision = (revisions[id] ?? 0) + 1
    revisions[id] = revision; snapshotLoading.value[id] = true
    try {
      const value = await api<AccountSnapshot>('/accounts/' + id + '/snapshot')
      if (current === epoch && revisions[id] === revision && accounts.value.some(a => a.id === id && a.credential_version === value.credential_version)) snapshots.value[id] = { ...value, received_monotonic_ms: performance.now() }
    } finally { if (current === epoch && revisions[id] === revision) delete snapshotLoading.value[id] }
  }
  async function verify(id: string): Promise<AccountSnapshot | null> {
    if (syncing.value[id]) return null
    const current = epoch, revision = (revisions[id] ?? 0) + 1
    revisions[id] = revision; syncing.value[id] = true; delete snapshotLoading.value[id]
    try {
      const value = await api<AccountSnapshot>('/accounts/' + id + '/verify', { method: 'POST' })
      if (current !== epoch || revisions[id] !== revision || !accounts.value.some(a => a.id === id && a.credential_version === value.credential_version)) return null
      snapshots.value[id] = { ...value, received_monotonic_ms: performance.now() }
      await refresh()
      return current === epoch ? value : null
    } finally { if (current === epoch && revisions[id] === revision) delete syncing.value[id] }
  }
  return { accounts, snapshots, syncing, snapshotLoading, loading, error, reset, refresh, create, archive, invalidateSnapshot, readSnapshot, verify }
})
