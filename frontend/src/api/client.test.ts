import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, onUnauthorized, setCsrfToken } from './client'

afterEach(() => { vi.unstubAllGlobals(); setCsrfToken(''); onUnauthorized(() => undefined) })
describe('API transport', () => {
  it('binds mutations to the current session and never uses browser storage', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { saved: true } }), { status: 200 }))
    vi.stubGlobal('fetch', fetcher); setCsrfToken('session-bound-token')
    expect(await api('/accounts', { method: 'POST', body: '{}' })).toEqual({ saved: true })
    const init = fetcher.mock.calls[0]?.[1] as RequestInit
    expect(init.credentials).toBe('include'); expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('session-bound-token')
    expect(localStorage.length).toBe(0)
  })
  it('clears authentication on 401 and preserves the request ID', async () => {
    const notify = vi.fn(); onUnauthorized(notify)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'UNAUTHENTICATED', message: '请先登录' }, meta: { request_id: 'request-1' } }), { status: 401 })))
    await expect(api('/accounts')).rejects.toMatchObject({ code: 'UNAUTHENTICATED', requestId: 'request-1' }); expect(notify).toHaveBeenCalledOnce()
  })
  it('does not retry an uncertain mutation', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('offline')); vi.stubGlobal('fetch', fetcher)
    await expect(api('/accounts', { method: 'POST', body: '{}' })).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).toHaveBeenCalledOnce()
  })
  it('rejects non-JSON upstream failures safely', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('upstream error', { status: 502 })))
    await expect(api('/accounts')).rejects.toMatchObject({ code: 'INVALID_RESPONSE', status: 502 })
  })
})
