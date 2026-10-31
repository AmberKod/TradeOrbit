export type Exchange = 'binance' | 'bitget' | 'okx'
export type MarketType = 'SPOT' | 'USDT_PERP'
export interface Instrument { key: string; exchange: Exchange; market_type: MarketType; symbol: string; base: string; quote: string; settle: string | null; price_tick: string | null; quantity_step: string | null; quantity_unit: 'BASE' | 'CONTRACT'; contract_size: string | null }
export interface Ticker { key: string; last: string | null; bid: string | null; ask: string | null; high_24h: string | null; low_24h: string | null; change_percent_24h: string | null; volume_base_24h: string | null; volume_quote_24h: string | null; source_ts: number | null; received_at: number; transport: 'WS' | 'REST' }
export interface Source { exchange: Exchange; market_type: MarketType; catalog_updated_at: number | null; instrument_count: number; catalog_stale: boolean; state: string; transport: string | null; error: string | null; last_received_at: number | null; requested: number; subscribed: number }
export interface Entry { id: string; key: string; instrument: Instrument | null; ticker: Ticker | null }
export interface Snapshot { entries: Entry[]; sources: Source[]; worker_alive: boolean; server_time: number; trading_enabled: false }
export interface CatalogResult { items: Instrument[]; total: number; sources: Source[] }
export interface Level { price: string; quantity: string; native_quantity: string }
export interface Book { bids: Level[]; asks: Level[]; quantity_currency: string; native_quantity_unit: string }
export interface Candle { open_time: number; open: string; high: string; low: string; close: string; confirmed: boolean | null }
export interface Trade { id: string; price: string; quantity: string; native_quantity: string; timestamp: number; side: 'BUY' | 'SELL' | 'UNKNOWN' }
export interface Component<T> { data: T | null; status: 'FRESH' | 'STALE' | 'UNAVAILABLE'; received_at: number | null; error: string | null }
export interface MarketDetail { instrument: Instrument; book: Component<Book>; candles: Component<Candle[]>; trades: Component<Trade[]>; mode: 'REST_SNAPSHOT'; refresh_seconds: number; fetched_at: number }
export const exchangeNames: Record<Exchange, string> = { binance: 'Binance', bitget: 'Bitget', okx: 'OKX 欧易' }
export const marketNames: Record<MarketType, string> = { SPOT: '现货', USDT_PERP: 'USDT 永续' }
export const sourceNames: Record<string, string> = { WAITING: '等待采集', IDLE: '待订阅', CONNECTING: '连接中', LIVE: '实时连接', DEGRADED: '连接降级', UNAVAILABLE: '暂不可用' }
export function displayNumber(value: string | null | undefined, digits = 8): string { if (value == null || value === '') return '—'; const n = Number(value); return Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: digits }) : '—' }
export function displayTime(value: number | null | undefined): string { return value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : '—' }
