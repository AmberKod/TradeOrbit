import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../api/client'
import { useAccountsStore } from './accounts'
import { useSessionStore } from './session'
import type { AccountSnapshot } from '../types/accounts'
import type { Account, Session } from '../types/domain'
vi.mock('../api/client', () => ({ api: vi.fn(), setCsrfToken: vi.fn(), onUnauthorized: vi.fn(), ApiError: class extends Error {} }))
const fixture = { id: 'old-workspace-account', label: 'Old account', credential_version: 1 } as Account
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

const savedSnapshot = { account_id: fixture.id, credential_version: 1, state: 'VERIFIED', scopes: {} } as AccountSnapshot
describe('private snapshot isolation', () => {
  it('ignores a verification response after logout', async () => {
    let finish!: (value: AccountSnapshot) => void
    vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const store = useAccountsStore(); store.accounts = [fixture]
    const pending = store.verify(fixture.id)
    store.reset(); finish(savedSnapshot)
    expect(await pending).toBeNull()
    expect(store.snapshots).toEqual({})
    expect(store.syncing).toEqual({})
  })
  it('rejects a stale snapshot response after credential invalidation', async () => {
    let finish!: (value: AccountSnapshot) => void
    vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const store = useAccountsStore(); store.accounts = [fixture]
    const pending = store.readSnapshot(fixture.id)
    store.invalidateSnapshot(fixture.id); finish(savedSnapshot); await pending
    expect(store.snapshots).toEqual({})
    expect(store.snapshotLoading).toEqual({})
  })
  it('a slow GET cannot overwrite a newer verification response', async () => {
    let finish!: (value: AccountSnapshot) => void
    vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValueOnce(savedSnapshot).mockResolvedValueOnce([fixture])
    const store = useAccountsStore(); store.accounts = [fixture]
    const slow = store.readSnapshot(fixture.id)
    await store.verify(fixture.id)
    finish({ ...savedSnapshot, state: 'FAILED' }); await slow
    expect(store.snapshots[fixture.id]?.state).toBe('VERIFIED')
    expect(store.snapshotLoading).toEqual({})
    expect(store.syncing).toEqual({})
  })
  it('clears cached balances when the credential version changes', async () => {
    vi.mocked(api).mockResolvedValueOnce([{ ...fixture, credential_version: 2 }])
    const store = useAccountsStore(); store.accounts = [fixture]; store.snapshots[fixture.id] = savedSnapshot
    await store.refresh()
    expect(store.snapshots).toEqual({})
  })
})
