<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api/client'
import CandleChart from '../components/CandleChart.vue'
import Icon from '../components/Icon.vue'
import { useMarketStore } from '../stores/market'
import { useSessionStore } from '../stores/session'
import type { CatalogResult, Component, Exchange, Instrument, MarketDetail, MarketType } from '../types/market'
import { displayNumber as num, displayTime as time, exchangeNames, marketNames, sourceNames } from '../types/market'
const market = useMarketStore(), session = useSessionStore()
const exchange = ref<Exchange>('binance'), kind = ref<MarketType>('SPOT'), search = ref('')
const products = ref<Instrument[]>([]), productTotal = ref(0), finding = ref(false), action = ref(''), error = ref('')
const selected = ref(''), detail = ref<MarketDetail | null>(null), detailError = ref(''), detailLoading = ref(false)
const canEdit = computed(() => !!session.session && session.session.role !== 'VIEWER')
const selectedEntry = computed(() => market.entries.find(row => row.key === selected.value))
const currentSource = computed(() => market.sources.find(row => row.exchange === exchange.value && row.market_type === kind.value))
const visibleRows = computed(() => market.entries.filter(row => row.instrument?.exchange === exchange.value && row.instrument?.market_type === kind.value || !row.instrument && row.key.startsWith(exchange.value + ':' + kind.value + ':')))
const connectionLabels = { STOPPED: '已停止', CONNECTING: '连接中', CONNECTED: '推送已连接', RETRYING: '正在重连' }
const freshnessLabels = { LIVE: '实时 WS', REST: 'REST 降级', STALE: '数据过期', WAITING: '等待报价' }
let searchTimer: ReturnType<typeof setTimeout> | null = null, detailTimer: ReturnType<typeof setTimeout> | null = null
let searchVersion = 0, detailVersion = 0, alive = true
let searchAbort: AbortController | null = null, detailAbort: AbortController | null = null
function message(cause: unknown): string { return cause instanceof Error ? cause.message : '请求失败，请稍后重试' }
async function find(): Promise<void> {
  const version = ++searchVersion
  searchAbort?.abort(); searchAbort = new AbortController(); finding.value = true
  try {
    const query = new URLSearchParams({ exchange: exchange.value, market_type: kind.value, search: search.value.trim(), limit: '12' })
    const result = await api<CatalogResult>('/market/instruments?' + query, { signal: searchAbort.signal })
    if (version !== searchVersion || !alive) return
    products.value = result.items; productTotal.value = result.total; error.value = ''
  } catch (cause) { if (version === searchVersion && alive) error.value = message(cause) }
  finally { if (version === searchVersion && alive) finding.value = false }
}
function scheduleSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchVersion++; searchAbort?.abort()
  searchTimer = setTimeout(() => void find(), 300)
}
async function add(item: Instrument): Promise<void> {
  action.value = item.key; error.value = ''
  try { await market.add(item.key); selected.value = item.key } catch (cause) { error.value = message(cause) } finally { action.value = '' }
}
async function remove(id: string): Promise<void> {
  action.value = id; error.value = ''
  try { await market.remove(id) } catch (cause) { error.value = message(cause) } finally { action.value = '' }
}
async function fetchDetail(version = detailVersion): Promise<void> {
  if (!selected.value || version !== detailVersion || !alive) return
  detailAbort?.abort(); detailAbort = new AbortController(); detailLoading.value = true
  try {
    const data = await api<MarketDetail>('/market/detail?key=' + encodeURIComponent(selected.value), { signal: detailAbort.signal })
    if (version === detailVersion && alive) { detail.value = data; detailError.value = '' }
  } catch (cause) { if (version === detailVersion && alive) detailError.value = message(cause) }
  finally {
    if (version === detailVersion && alive) { detailLoading.value = false; detailTimer = setTimeout(() => void fetchDetail(version), 5000) }
  }
}
function componentLabel(part: Component<unknown> | undefined): string {
  if (!part) return '等待快照'
  const old = !!part.received_at && market.clock - part.received_at > 20000
  return part.status === 'UNAVAILABLE' ? '不可用' : part.status === 'STALE' || old || detailError.value ? '过期快照' : '快照'
}
function selectFirst(): void { if (!visibleRows.value.some(row => row.key === selected.value)) selected.value = visibleRows.value[0]?.key ?? '' }
watch([exchange, kind], () => { products.value = []; scheduleSearch(); selectFirst() })
watch(search, scheduleSearch)
watch(() => market.entries.map(row => row.key).join('|'), selectFirst)
watch(() => currentSource.value?.catalog_updated_at, () => { void find() })
watch(selected, () => {
  detailVersion++; if (detailTimer) clearTimeout(detailTimer); detailAbort?.abort()
  detail.value = null; detailError.value = ''; detailLoading.value = false
  if (selected.value) void fetchDetail(detailVersion)
})
onMounted(async () => { await market.start(); if (alive) { selectFirst(); await find() } })
onBeforeUnmount(() => { alive = false; searchVersion++; detailVersion++; if (searchTimer) clearTimeout(searchTimer); if (detailTimer) clearTimeout(detailTimer); searchAbort?.abort(); detailAbort?.abort(); market.stop() })
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">MARKET ORBIT / PUBLIC DATA</span><h1>行情工作台</h1><p>跨交易所自选与公开行情。现货和 USDT 永续独立订阅。</p></div><span class="pill" :class="market.connection === 'CONNECTED' ? 'green-pill' : 'amber-pill'"><span class="status-dot" :class="market.connection === 'CONNECTED' ? 'green' : 'amber'"></span>{{ connectionLabels[market.connection] }}</span></div>
  <div v-if="error || market.error" class="alert error" role="alert">{{ error || market.error }}</div>
  <div v-if="!market.workerAlive && !market.loading" class="notice"><Icon name="pulse" /><div><strong>行情采集进程尚未就绪</strong><span>请检查 market-worker 和网络出口；已有报价会标记过期。</span></div></div>
  <section class="market-sources" aria-label="交易所数据源状态"><article v-for="source in market.sources" :key="source.exchange + source.market_type" class="source-card"><div><strong>{{ exchangeNames[source.exchange] }}</strong><span class="tiny-tag">{{ marketNames[source.market_type] }}</span></div><p :class="{ positive: source.state === 'LIVE' && market.workerAlive }">{{ !market.workerAlive ? '采集离线' : sourceNames[source.state] ?? source.state }} <small v-if="source.transport">/ {{ source.transport }}</small></p><small>{{ source.instrument_count }} 个产品 · {{ source.catalog_stale ? '规格过期' : '规格已同步' }}</small><small v-if="source.requested > source.subscribed" class="negative">订阅 {{ source.subscribed }}/{{ source.requested }} · 超限部分无实时订阅</small><small v-if="source.error" class="source-error">{{ source.error }}</small></article></section>
  <section class="panel market-picker"><div class="market-controls"><label>交易所<select v-model="exchange"><option value="binance">Binance</option><option value="bitget">Bitget</option><option value="okx">OKX 欧易</option></select></label><label>市场<select v-model="kind"><option value="SPOT">现货 · USDT</option><option value="USDT_PERP">USDT 永续</option></select></label><label class="symbol-search">查找交易对<input v-model="search" placeholder="搜索 BTC、ETH、SOL…" maxlength="30" /></label><button class="button secondary" :disabled="finding" @click="find"><Icon name="refresh" :size="15" />刷新产品</button></div><div class="product-results"><span v-if="finding" class="muted">正在查询产品…</span><span v-else-if="!products.length" class="muted">{{ currentSource?.catalog_stale ? '产品目录未就绪，请检查网络连接。' : '没有匹配的产品。' }}</span><button v-for="item in products" v-else :key="item.key" class="product-chip" :disabled="!canEdit || !!action || market.entries.some(row => row.key === item.key) || currentSource?.catalog_stale" @click="add(item)"><span>{{ item.base }}/USDT</span><small>{{ market.entries.some(row => row.key === item.key) ? '已添加' : '+ 自选' }}</small></button></div><p class="fine-print">匹配 {{ productTotal }} 个产品，最多显示 12 个。自选保存到当前工作空间，最多 40 个。{{ canEdit ? '' : '观察者仅可查看。' }}</p></section>
  <section class="panel"><div class="panel-heading"><div><h2>行情自选 <span class="count-tag">{{ visibleRows.length }}</span></h2><p>{{ exchangeNames[exchange] }} / {{ marketNames[kind] }} · 全工作空间 {{ market.entries.length }}/40 · 报价单位 USDT</p></div><span class="fine-print">绿涨红跌 · 24 小时滚动统计</span></div><div v-if="market.loading" class="loading-state">正在读取自选…</div><div v-else-if="!visibleRows.length" class="empty-state market-empty"><Icon name="chart" :size="32" /><h3>添加一个交易对开始观察</h3><p>从上方产品目录添加自选。这里只显示交易所返回的真实报价。</p></div><div v-else class="table-scroll"><table class="quote-table"><thead><tr><th>交易对 / 详情</th><th>最新价</th><th>24h 涨跌</th><th>买一 / 卖一</th><th>24h 成交量</th><th>数据状态</th><th v-if="canEdit">操作</th></tr></thead><tbody><tr v-for="row in visibleRows" :key="row.id" :class="{ 'selected-quote': selected === row.key }"><td><button class="text-button symbol-button" @click="selected = row.key">{{ row.instrument ? row.instrument.base + '/USDT' : row.key.split(':')[2] }}<small>{{ row.instrument?.symbol ?? '产品已下架或规格不可用' }}</small></button></td><td class="mono">{{ num(row.ticker?.last) }}</td><td class="mono" :class="Number(row.ticker?.change_percent_24h) > 0 ? 'positive' : Number(row.ticker?.change_percent_24h) < 0 ? 'negative' : ''">{{ row.ticker?.change_percent_24h != null ? num(row.ticker.change_percent_24h, 2) + '%' : '—' }}</td><td class="mono">{{ num(row.ticker?.bid) }}<small>{{ num(row.ticker?.ask) }}</small></td><td class="mono">{{ num(row.ticker?.volume_base_24h, 2) }} {{ row.instrument?.base }}<small>{{ num(row.ticker?.volume_quote_24h, 2) }} USDT</small></td><td><span class="pill" :class="market.freshness(row) === 'LIVE' ? 'green-pill' : 'amber-pill'">{{ freshnessLabels[market.freshness(row)] }}</span><small>{{ time(row.ticker?.received_at) }}<template v-if="market.age(row.ticker) !== null"> · {{ Math.floor((market.age(row.ticker) ?? 0) / 1000) }}s</template></small></td><td v-if="canEdit"><button class="text-button muted" :disabled="!!action" @click="remove(row.id)">移除</button></td></tr></tbody></table></div></section>
  <template v-if="selectedEntry"><div class="detail-heading"><div><h2>{{ selectedEntry.instrument?.symbol ?? selected }} <span class="tiny-tag">{{ marketNames[kind] }}</span></h2><p>以下为每 5 秒刷新的 REST 快照；盘口、成交与 K 线分别标记可用性。</p></div><span class="pill muted-pill">REST SNAPSHOT</span></div><div v-if="detailError" class="alert error" role="alert">{{ detailError }} · 保留的数据仅供参考</div><section class="panel"><div class="panel-heading"><h2>1 分钟 K 线 <span class="tiny-tag">{{ componentLabel(detail?.candles) }}</span></h2><span class="fine-print">最近 {{ detail?.candles.data?.length ?? 0 }} 根 · 更新 {{ time(detail?.candles.received_at) }}</span></div><div class="chart-body"><CandleChart v-if="detail?.candles.data?.length" :candles="detail.candles.data" :symbol="detail.instrument.symbol" /><div v-else class="loading-state">{{ detailLoading ? '正在获取 K 线…' : '暂无可用 K 线' }}</div></div></section><div class="market-detail-grid"><section class="panel"><div class="panel-heading"><h2>盘口 · 买卖各 5 档</h2><span class="tiny-tag">{{ componentLabel(detail?.book) }}</span></div><div class="book-content"><div v-for="side in ['asks', 'bids'] as const" :key="side" class="book-side"><div class="book-header"><span>{{ side === 'asks' ? '卖盘' : '买盘' }} / USDT</span><span>数量 / {{ selectedEntry.instrument?.base }}</span></div><div v-for="(level, index) in detail?.book.data?.[side] ?? []" :key="level.price" class="book-level mono"><span :class="side === 'bids' ? 'positive' : 'negative'">{{ side === 'asks' ? '卖' : '买' }}{{ index + 1 }} <b>{{ num(level.price) }}</b></span><span>{{ num(level.quantity) }}</span></div></div><p v-if="!detail?.book.data" class="fine-print">盘口暂不可用</p></div><div class="snapshot-footer">更新 {{ time(detail?.book.received_at) }}<template v-if="selectedEntry.instrument?.quantity_unit === 'CONTRACT'"> · 原始张数 × {{ selectedEntry.instrument.contract_size }} 已换算为 {{ selectedEntry.instrument.base }}</template></div></section><section class="panel"><div class="panel-heading"><h2>最近成交 · 20 笔</h2><span class="tiny-tag">{{ componentLabel(detail?.trades) }}</span></div><div class="recent-trades table-scroll"><table><thead><tr><th>时间</th><th>成交价 / USDT</th><th>数量 / {{ selectedEntry.instrument?.base }}</th><th>主动方向</th></tr></thead><tbody><tr v-for="trade in detail?.trades.data ?? []" :key="trade.id"><td class="mono">{{ time(trade.timestamp) }}</td><td class="mono">{{ num(trade.price) }}</td><td class="mono">{{ num(trade.quantity) }}</td><td :class="trade.side === 'BUY' ? 'positive' : trade.side === 'SELL' ? 'negative' : ''">{{ trade.side === 'BUY' ? '主动买' : trade.side === 'SELL' ? '主动卖' : '未知' }}</td></tr></tbody></table><div v-if="!detail?.trades.data?.length" class="loading-state">暂无可用成交</div></div><div class="snapshot-footer">更新 {{ time(detail?.trades.received_at) }}</div></section></div></template>
  <p class="fine-print">公开行情来自交易所主站市场，与已保存的 DEMO/LIVE 私有账户独立。数据可用性取决于交易所和网络；不代表账户已验证或可下单。</p>
</template>
<style scoped>
.negative{color:#ef8998!important}.market-sources{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:22px}.source-card{padding:14px;background:var(--surface);border:1px solid var(--border);border-radius:6px;min-width:0}.source-card>div{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.source-card strong{font-size:11px}.source-card p{font-size:12px;margin-top:10px;color:var(--amber)}.source-card small{font-size:9px;color:var(--muted)}.source-card>small{display:block;margin-top:4px;overflow-wrap:anywhere}.source-error{color:#dbac75!important}.market-picker{padding:20px 23px}.market-controls{display:flex;gap:14px;align-items:end}.market-controls label{display:flex;flex-direction:column;gap:6px;font-size:10px;color:var(--muted);width:160px}.market-controls .symbol-search{flex:1}.market-controls .button{min-height:40px}.product-results{display:flex;flex-wrap:wrap;gap:8px;margin:17px 0 12px;min-height:34px;align-items:center;font-size:12px}.product-chip{display:flex;gap:12px;align-items:center;background:#182536;border:1px solid #31465f;border-radius:5px;color:#c4d6ed;padding:7px 10px;font-size:11px}.product-chip small{color:#86a9dc;font-size:9px}.product-chip:not(:disabled):hover{border-color:var(--accent)}.market-empty{min-height:190px;gap:10px}.market-empty p{margin:0}.quote-table td,.quote-table th{padding:14px 17px}.selected-quote{background:#192638}.symbol-button{text-align:left;font-size:13px}.symbol-button small{color:var(--muted);font-size:9px}.quote-table td small{font-size:9px}.detail-heading{display:flex;gap:15px;justify-content:space-between;align-items:center;margin:27px 0 17px}.detail-heading p{color:var(--muted);font-size:10px;margin-top:5px}.chart-body{padding:18px 16px 5px}.market-detail-grid{display:grid;grid-template-columns:1fr 1.2fr;gap:22px}.book-content{padding:12px 22px}.book-side+.book-side{border-top:1px solid var(--border);margin-top:12px;padding-top:12px}.book-header,.book-level{display:flex;justify-content:space-between;gap:16px}.book-header{font-size:10px;color:var(--muted);margin-bottom:9px}.book-level{padding:4px 0;font-size:11px}.book-level b{font-weight:400;margin-left:14px}.snapshot-footer{padding:10px 22px;border-top:1px solid var(--border);font-size:9px;color:var(--muted)}.recent-trades{height:362px}.recent-trades td,.recent-trades th{padding:8px 13px;font-size:10px}.recent-trades thead{position:sticky;top:0}.detail-heading .pill{flex-shrink:0}@media(max-width:1350px){.market-sources{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:950px){.market-controls{flex-wrap:wrap}.market-controls label{flex:1;min-width:130px}.market-controls .symbol-search{min-width:190px}.market-detail-grid{grid-template-columns:1fr;gap:0}}@media(max-width:650px){.market-sources{grid-template-columns:repeat(2,minmax(0,1fr))}.source-card{padding:12px}.market-picker{padding:16px}.market-controls{gap:10px}.market-controls .symbol-search{min-width:100%}.market-controls .button{width:100%}.detail-heading{align-items:start}.detail-heading .pill{font-size:8px}.chart-body{padding:8px 0}.source-card p{font-size:11px}}
</style>
