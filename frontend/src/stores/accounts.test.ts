import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useAccountsStore } from './accounts'
import { useSessionStore } from './session'
import type { Account, Session } from '../types/domain'
vi.mock('../api/client', () => ({ api: vi.fn(), setCsrfToken: vi.fn(), onUnauthorized: vi.fn(), ApiError: class extends Error {} }))
const fixture = { id: 'old-workspace-account', label: 'Old account' } as Account
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks() })
describe('workspace account isolation', () => {
  it('ignores an old response after reset', async () => {
    let finish!: (value: Account[]) => void
    vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const store = useAccountsStore(), pending = store.refresh()
    store.reset(); finish([fixture]); await pending
    expect(store.accounts).toEqual([])
    expect(store.loading).toBe(false)
  })
  it('removes previous values when a refresh fails', async () => {
    const store = useAccountsStore(); store.accounts = [fixture]
    vi.mocked(api).mockRejectedValueOnce(new Error('Unavailable'))
    await store.refresh()
    expect(store.accounts).toEqual([])
    expect(store.error).toBe('Unavailable')
  })
  it('clears account cache on logout', async () => {
    const session = { user: { id: 'user', email: 'fixture@example.com' }, workspace: { id: 'workspace', name: 'Fixture' }, role: 'ADMIN', csrf_token: 'fixture-token' } as Session
    vi.mocked(api).mockResolvedValueOnce(session).mockResolvedValueOnce({ logged_out: true })
    const auth = useSessionStore(), store = useAccountsStore()
    await auth.login('fixture@example.com', 'fixture-password')
    store.accounts = [fixture]; await auth.logout()
    expect(store.accounts).toEqual([])
    expect(auth.session).toBeNull()
  })
})
