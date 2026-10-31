<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { AccountSnapshot, PrivateBalance, PrivateScope } from '../types/accounts'
import { readStateNames, scopeNames } from '../types/accounts'
import EmptyState from './EmptyState.vue'
const props = defineProps<{ snapshot: AccountSnapshot | null; label: string; loading?: boolean }>()
const showZero = ref(false)
let anchor = props.snapshot?.received_monotonic_ms ?? performance.now(), timer: ReturnType<typeof setInterval> | undefined
const elapsed = ref(Math.max(0, (performance.now() - anchor) / 1000))
watch(() => props.snapshot, () => { anchor = props.snapshot?.received_monotonic_ms ?? performance.now(); elapsed.value = Math.max(0, (performance.now() - anchor) / 1000) })
onMounted(() => { timer = setInterval(() => { elapsed.value = (performance.now() - anchor) / 1000 }, 1000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
const scopes = computed(() => Object.entries(props.snapshot?.scopes ?? {}))
function stale(scope: PrivateScope): boolean { return scope.freshness !== 'FRESH' || scope.status !== 'OK' || (scope.age_seconds ?? 0) + elapsed.value > (props.snapshot?.stale_after_seconds ?? 300) }
function balances(scope: PrivateScope): PrivateBalance[] { return (scope.data?.balances ?? []).filter(b => showZero.value || [b.equity, b.available, b.wallet_balance, b.unrealized_pnl].every(v => v === null) || [b.equity, b.available, b.wallet_balance, b.unrealized_pnl].some(v => v !== null && /[1-9]/.test(v))) }
function time(value: string | null): string { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚无成功快照' }
function pnlClass(value: string | null): string { return value === null || Number(value) === 0 ? 'muted' : value.startsWith('-') ? 'negative' : 'positive' }
</script>
<template>
  <section class="panel private-snapshot" aria-label="账户只读快照">
    <div class="panel-heading"><div><h2>{{ label }} · 账户快照</h2><p class="muted">手动 REST 读取 · 5 分钟后标为过期 · 不自动后台同步</p></div><span class="pill" :class="snapshot?.state === 'VERIFIED' ? 'green-pill' : 'amber-pill'">{{ readStateNames[snapshot?.state ?? 'NOT_VERIFIED'] }}</span></div>
    <div v-if="loading" class="loading-state" role="status">正在读取已保存的快照…</div>
    <EmptyState v-else-if="!snapshot || !scopes.length" title="尚无账户快照" :description="snapshot?.sync_block_reason ?? '管理员保存只读密钥后，点击“验证并同步”以读取交易所。'" icon="wallet" />
    <template v-else>
      <p class="snapshot-note">本次验证：{{ time(snapshot.checked_at) }} · 凭据版本 {{ snapshot.credential_version }}。不同钱包分别展示，尚未计算去重 NAV；余额与持仓按各自读取时间显示。</p>
      <label class="zero-toggle"><input v-model="showZero" type="checkbox">显示零余额</label>
      <article v-for="[name, scope] in scopes" :key="name" class="scope-block">
        <div class="scope-heading"><div><h3>{{ scopeNames[name] ?? name }}</h3><small class="muted">{{ time(scope.observed_at) }}</small></div><span class="pill" :class="scope.data && !stale(scope) ? 'green-pill' : 'amber-pill'">{{ !scope.data ? '未覆盖' : stale(scope) ? '快照已过期' : '快照可用' }}</span></div>
        <div v-if="scope.error_message" class="alert error" role="alert">{{ scope.error_message }}<span v-if="scope.data">；以下保留上次成功数据。</span></div>
        <template v-if="scope.data">
          <dl v-if="name === 'account_config' || name === 'uta_config'" class="detail-list"><div><dt>模式证据</dt><dd>{{ name === 'account_config' ? 'OKX 账户等级 ' + scope.data.metadata.account_level : 'Bitget ' + scope.data.metadata.account_mode + ' / ' + scope.data.metadata.account_level }}</dd></div><div><dt>密钥权限</dt><dd>{{ scope.data.metadata.permissions_inspected ? (scope.data.metadata.permissions as string[]).join(' / ') : '未完整核验，请在交易所确认只读权限' }}</dd></div></dl>
          <p v-if="name === 'account_config' && ((scope.data.metadata.permissions as string[] | undefined)?.some(v => v === 'trade' || v === 'withdraw'))" class="alert error">此密钥包含交易或提币权限，建议重新创建只读密钥。平台交易执行仍锁定。</p>
          <template v-if="name.includes('balances')">
            <div v-if="balances(scope).length" class="table-scroll"><table><thead><tr><th>币种</th><th>交易所权益 / 余额</th><th>可用</th><th>钱包余额</th><th>未实现盈亏</th></tr></thead><tbody><tr v-for="balance in balances(scope)" :key="balance.asset"><td class="mono">{{ balance.asset }}</td><td class="mono">{{ balance.equity ?? '—' }}</td><td class="mono">{{ balance.available ?? '—' }}</td><td class="mono">{{ balance.wallet_balance ?? '—' }}</td><td class="mono" :class="pnlClass(balance.unrealized_pnl)">{{ balance.unrealized_pnl ?? '—' }}</td></tr></tbody></table></div>
            <p v-else class="snapshot-note">已读取本域，当前没有{{ showZero ? '' : '非零' }}余额。</p>
          </template>
          <template v-if="name.includes('positions')">
            <div v-if="scope.data.positions.length" class="table-scroll"><table><thead><tr><th>合约 / 方向</th><th>数量 / 单位</th><th>持仓均价</th><th>标记价</th><th>预估强平价</th><th>未实现盈亏</th><th>杠杆 / 保证金</th></tr></thead><tbody><tr v-for="position in scope.data.positions" :key="position.instrument + ':' + position.side + ':' + position.margin_mode"><td><strong>{{ position.instrument }}</strong><small :class="position.side === 'LONG' ? 'positive' : 'negative'">{{ position.side === 'LONG' ? '多仓' : '空仓' }}</small></td><td class="mono">{{ position.quantity }}<small>{{ position.quantity_unit === 'CONTRACT' ? '张（原生合约数量）' : '基础币数量' }}</small></td><td class="mono">{{ position.entry_price ?? '—' }}</td><td class="mono">{{ position.mark_price ?? '—' }}</td><td class="mono">{{ position.liquidation_price ?? '—' }}</td><td class="mono" :class="pnlClass(position.unrealized_pnl)">{{ position.unrealized_pnl ?? '—' }}<small>{{ position.margin_asset ?? '结算币种未返回' }}</small></td><td class="mono">{{ position.leverage ? position.leverage + '×' : '—' }}<small>{{ position.margin_mode ?? '模式未返回' }}</small><small v-if="position.margin_ratio !== null">原生保证金率 {{ position.margin_ratio }}</small></td></tr></tbody></table></div>
            <p v-else class="snapshot-note">已读取本域，当前没有未平仓持仓。</p>
          </template>
        </template>
      </article>
      <p class="snapshot-note">范围不包含理财、借贷账本、完整资金流水及历史 NAV；OKX 持仓为永续合约，Bitget 持仓为 USDT 合约。空值表示未返回或不适用，不能视为 0。</p>
    </template>
  </section>
</template>
<style scoped>
.private-snapshot { margin-top: 20px; }
.negative { color: #ef929d !important; }
.panel-heading p { margin: 7px 0 0; font-size: 12px; }
.scope-block { border-top: 1px solid var(--border, #263141); padding: 20px 0 8px; }
.scope-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 0 22px 14px; }
h3 { margin: 0 0 5px; font-size: 14px; }
.snapshot-note { margin: 0; padding: 14px 22px; color: var(--text-muted, #8b98aa); font-size: 12px; line-height: 1.7; }
.zero-toggle { display: flex; align-items: center; gap: 8px; padding: 0 22px 16px; font-size: 12px; }
.zero-toggle input { width: auto; margin: 0; }
.alert { margin: 0 22px 14px; }
.detail-list { margin: 0 22px; }
</style>
