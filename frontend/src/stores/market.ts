import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
import type { Entry, Snapshot, Source, Ticker } from '../types/market'

export const useMarketStore = defineStore('market', () => {
  const entries = ref<Entry[]>([]), sources = ref<Source[]>([])
  const workerAlive = ref(false), loading = ref(false), error = ref('')
  const connection = ref<'STOPPED' | 'CONNECTING' | 'CONNECTED' | 'RETRYING'>('STOPPED')
  const clock = ref(Date.now())
  let socket: WebSocket | null = null, retry: ReturnType<typeof setTimeout> | null = null
  let timer: ReturnType<typeof setInterval> | null = null
  let active = false, generation = 0, attempts = 0, connectionId = '', sequence = 0
  let offset = 0, lastFrame = 0

  function setSnapshot(data: Snapshot): void {
    const prior = new Map(entries.value.map(row => [row.key, row.ticker]))
    for (const row of data.entries) {
      const old = prior.get(row.key), next = row.ticker
      if (old && (!next || old.received_at > next.received_at || old.source_ts != null && next.source_ts != null && old.source_ts > next.source_ts)) row.ticker = old
    }
    entries.value = data.entries; sources.value = data.sources; workerAlive.value = data.worker_alive
    offset = data.server_time - Date.now(); clock.value = Date.now() + offset
  }
  function merge(ticks: Ticker[]): void {
    for (const tick of ticks) {
      const row = entries.value.find(item => item.key === tick.key)
      if (!row || (row.ticker && tick.received_at < row.ticker.received_at)) continue
      if (row.ticker?.source_ts != null && tick.source_ts != null && tick.source_ts < row.ticker.source_ts) continue
      row.ticker = tick
    }
  }
  async function refresh(): Promise<void> {
    const version = generation
    const data = await api<Snapshot>('/market/watchlist')
    if (version === generation) setSnapshot(data)
  }
  function age(ticker: Ticker | null): number | null {
    if (!ticker) return null
    return Math.max(0, clock.value - ticker.received_at, ticker.source_ts ? clock.value - ticker.source_ts : 0)
  }
  function freshness(entry: Entry): 'LIVE' | 'REST' | 'STALE' | 'WAITING' {
    const elapsed = age(entry.ticker)
    if (elapsed == null) return 'WAITING'
    if (!workerAlive.value || connection.value !== 'CONNECTED' || elapsed > 15000) return 'STALE'
    const source = sources.value.find(item => item.exchange === entry.instrument?.exchange && item.market_type === entry.instrument?.market_type)
    if (entry.ticker?.transport === 'REST') return 'REST'
    return source?.state === 'LIVE' ? 'LIVE' : 'STALE'
  }
  function connect(): void {
    if (!active) return
    connection.value = attempts ? 'RETRYING' : 'CONNECTING'
    const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/v1/market/stream')
    socket = ws; connectionId = ''; sequence = 0; lastFrame = Date.now()
    ws.onopen = () => { if (socket !== ws) return; connection.value = 'CONNECTED' }
    ws.onmessage = (event: MessageEvent<string>) => {
      if (socket !== ws || !active) return
      try {
        const frame = JSON.parse(event.data) as { schema_version: number; connection_id: string; sequence: number; type: string; data: Snapshot & { items: Ticker[] } }
        if (frame.schema_version !== 1 || !Number.isSafeInteger(frame.sequence)) return
        if (connectionId && frame.connection_id !== connectionId) { ws.close(); return }
        if (frame.sequence <= sequence) return
        if (sequence && frame.sequence !== sequence + 1) ws.send(JSON.stringify({ type: 'resync' }))
        connectionId = frame.connection_id; sequence = frame.sequence; lastFrame = Date.now(); attempts = 0
        if (frame.type === 'snapshot') { setSnapshot(frame.data); error.value = '' }
        else if (frame.type === 'tickers') merge(frame.data.items)
      } catch { error.value = '行情推送格式异常，正在重新连接'; ws.close() }
    }
    ws.onerror = () => { if (socket === ws) error.value = '行情推送连接中断，正在重试' }
    ws.onclose = (event) => {
      if (socket !== ws || !active) return
      socket = null; connection.value = 'RETRYING'
      if (event.code === 4401 || event.code === 4403) {
        error.value = event.code === 4401 ? '行情会话已失效，请重新登录' : '行情连接来源未授权'
        if (event.code === 4401) void refresh().catch(() => undefined)
        active = false; connection.value = 'STOPPED'; return
      }
      retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(attempts++, 5)) + Math.random() * 300)
    }
  }
  async function start(): Promise<void> {
    if (active) return
    active = true; const version = ++generation; loading.value = true; error.value = ''
    try { await refresh() } catch (cause) { error.value = cause instanceof Error ? cause.message : '行情加载失败' }
    finally { if (version === generation) loading.value = false }
    if (!active || version !== generation) return
    connect()
    timer = setInterval(() => {
      clock.value = Date.now() + offset
      if (socket?.readyState === WebSocket.OPEN && Date.now() - lastFrame > 12000) socket.close()
    }, 1000)
  }
  function stop(): void {
    active = false; generation++
    if (retry) clearTimeout(retry); if (timer) clearInterval(timer)
    retry = timer = null
    const old = socket; socket = null; old?.close()
    connection.value = 'STOPPED'
  }
  function reset(): void { stop(); entries.value = []; sources.value = []; workerAlive.value = false; error.value = ''; loading.value = false }
  async function add(key: string): Promise<void> { await api('/market/watchlist', { method: 'POST', body: JSON.stringify({ key }) }); await refresh() }
  async function remove(id: string): Promise<void> { await api('/market/watchlist/' + id, { method: 'DELETE' }); await refresh() }
  return { entries, sources, workerAlive, loading, error, connection, clock, age, freshness, start, stop, reset, refresh, add, remove }
})
