import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useMarketStore } from './market'
import { api } from '../api/client'
import type { Snapshot, Ticker } from '../types/market'
vi.mock('../api/client', () => ({ api: vi.fn() }))
class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  send = vi.fn()
  constructor() { FakeSocket.instances.push(this) }
  close(): void { this.readyState = 3; this.onclose?.({ code: 1000 }) }
  frame(type: string, data: unknown, sequence: number, connectionId = 'first'): void { this.onmessage?.({ data: JSON.stringify({ type, data, schema_version: 1, connection_id: connectionId, sequence }) }) }
}
const key = 'binance:SPOT:BTCUSDT'
function tick(received = Date.now(), source = received, last = '100'): Ticker { return { key, last, bid: '99', ask: '101', high_24h: '110', low_24h: '90', change_percent_24h: '2', volume_base_24h: '2', volume_quote_24h: '200', source_ts: source, received_at: received, transport: 'WS' } }
function snapshot(): Snapshot { return { entries: [{ id: 'one', key, instrument: { key, exchange: 'binance', market_type: 'SPOT', symbol: 'BTCUSDT', base: 'BTC', quote: 'USDT', settle: null, price_tick: '0.01', quantity_step: '0.001', quantity_unit: 'BASE', contract_size: null }, ticker: tick() }], sources: [{ exchange: 'binance', market_type: 'SPOT', state: 'LIVE', transport: 'WS', catalog_updated_at: Date.now(), catalog_stale: false, instrument_count: 1, error: null, last_received_at: Date.now(), requested: 1, subscribed: 1 }], worker_alive: true, server_time: Date.now(), trading_enabled: false } }
let store: ReturnType<typeof useMarketStore>
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-31T00:00:00Z')); setActivePinia(createPinia()); FakeSocket.instances = []; vi.stubGlobal('WebSocket', FakeSocket); vi.mocked(api).mockResolvedValue(snapshot()); store = useMarketStore() })
afterEach(() => { store.reset(); vi.unstubAllGlobals(); vi.useRealTimers(); vi.clearAllMocks() })
describe('market stream', () => {
  it('never treats heartbeat as a new market quote', async () => {
    await store.start(); const ws = FakeSocket.instances[0]!; ws.onopen?.(); ws.frame('snapshot', snapshot(), 1)
    expect(store.freshness(store.entries[0]!)).toBe('LIVE')
    store.sources[0]!.state = 'DEGRADED'; expect(store.freshness(store.entries[0]!)).toBe('STALE'); store.sources[0]!.state = 'LIVE'
    for (let i = 0; i < 17; i++) { await vi.advanceTimersByTimeAsync(1000); ws.frame('heartbeat', {}, i + 2) }
    expect(store.freshness(store.entries[0]!)).toBe('STALE')
    expect(store.entries[0]!.ticker!.received_at).toBe(Date.parse('2026-10-31T00:00:00Z'))
  })
  it('rejects duplicate frames, old timestamps and unrequested products', async () => {
    await store.start(); const ws = FakeSocket.instances[0]!; ws.onopen?.(); ws.frame('snapshot', snapshot(), 1)
    ws.frame('tickers', { items: [tick(Date.now() + 2, Date.now() + 2, '102')] }, 2)
    ws.frame('tickers', { items: [tick(Date.now() + 3, Date.now() + 3, '999')] }, 2)
    ws.frame('tickers', { items: [tick(Date.now() + 4, Date.now() - 1, '90'), { ...tick(), key: 'other' }] }, 3)
    expect(store.entries).toHaveLength(1); expect(store.entries[0]!.ticker!.last).toBe('102')
    ws.frame('snapshot', snapshot(), 4)
    expect(store.entries[0]!.ticker!.last).toBe('102')
  })
  it('reconnects with a new connection sequence and clears on logout', async () => {
    await store.start(); const first = FakeSocket.instances[0]!; first.onopen?.(); first.frame('snapshot', snapshot(), 1); first.close()
    expect(store.freshness(store.entries[0]!)).toBe('STALE')
    await vi.advanceTimersByTimeAsync(1400); expect(FakeSocket.instances).toHaveLength(2)
    const second = FakeSocket.instances[1]!; second.onopen?.(); second.frame('snapshot', snapshot(), 1, 'second')
    expect(store.connection).toBe('CONNECTED'); store.reset(); await vi.advanceTimersByTimeAsync(60000)
    expect(store.entries).toHaveLength(0); expect(FakeSocket.instances).toHaveLength(2); expect(store.connection).toBe('STOPPED')
  })
  it('does not restore data after a reset races an HTTP response', async () => {
    let finish!: (data: Snapshot) => void
    vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve as (data: Snapshot) => void }))
    const pending = store.start(); store.reset(); finish(snapshot()); await pending
    expect(store.entries).toHaveLength(0); expect(FakeSocket.instances).toHaveLength(0)
  })
})
