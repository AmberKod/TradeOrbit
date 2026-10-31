import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AccountSnapshot from './AccountSnapshot.vue'
import type { AccountSnapshot as Snapshot, PrivateScope } from '../types/accounts'
function snapshot(): Snapshot { return { account_id: 'fixture', credential_version: 1, state: 'VERIFIED', checked_at: '2026-10-31T00:00:00Z', trading_enabled: false, sync_supported: true, sync_block_reason: null, transport: 'MANUAL_REST', stale_after_seconds: 300, scopes: { spot_balances: { status: 'OK', error_code: null, error_message: null, observed_at: '2026-10-31T00:00:00Z', age_seconds: 0, freshness: 'FRESH', data: { balances: [{ asset: 'USDT', equity: '0', available: '0', wallet_balance: '0', unrealized_pnl: null, equity_definition: 'fixture' }], positions: [], metadata: {} } } } } }
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })
describe('private snapshot display', () => {
  it('distinguishes no snapshot from a successful empty wallet', async () => {
    const wrapper = mount(AccountSnapshot, { props: { snapshot: null, label: 'Fixture' } })
    expect(wrapper.text()).toContain('尚无账户快照')
    await wrapper.setProps({ snapshot: snapshot() })
    expect(wrapper.text()).toContain('当前没有非零余额')
    await wrapper.find('input[type=checkbox]').setValue(true)
    expect(wrapper.text()).toContain('USDT')
    wrapper.unmount()
  })
  it('expires a snapshot with monotonic elapsed time without polling an exchange', async () => {
    vi.useFakeTimers()
    let now = 0
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    const wrapper = mount(AccountSnapshot, { props: { snapshot: snapshot(), label: 'Fixture' } })
    expect(wrapper.text()).toContain('快照可用')
    now = 301000
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.text()).toContain('快照已过期')
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('does not make a cached snapshot fresh again after remounting', () => {
    vi.spyOn(performance, 'now').mockReturnValue(360000)
    const value = snapshot(); value.received_monotonic_ms = 0
    const wrapper = mount(AccountSnapshot, { props: { snapshot: value, label: 'Fixture' } })
    expect(wrapper.text()).toContain('快照已过期')
    wrapper.unmount()
  })
  it('keeps native contract units and shows failed reads as stale', () => {
    const value = snapshot(), scope = value.scopes.spot_balances as PrivateScope
    value.state = 'PARTIAL'; delete value.scopes.spot_balances
    value.scopes.swap_positions = { ...scope, status: 'FAILED', freshness: 'STALE', error_code: 'TIMEOUT', error_message: '读取超时', data: { balances: [], metadata: {}, positions: [{ instrument: 'BTC-USDT-SWAP', side: 'SHORT', quantity: '2', quantity_unit: 'CONTRACT', margin_asset: 'USDT', entry_price: '50000', mark_price: null, liquidation_price: null, unrealized_pnl: '-1.123456789123456789', leverage: null, margin_ratio: null, margin_ratio_definition: null, margin_mode: 'cross' }] } }
    const wrapper = mount(AccountSnapshot, { props: { snapshot: value, label: 'Fixture' } })
    expect(wrapper.text()).toContain('原生合约数量')
    expect(wrapper.text()).toContain('-1.123456789123456789')
    expect(wrapper.text()).toContain('保留上次成功数据')
    expect(wrapper.text()).toContain('快照已过期')
    wrapper.unmount()
  })
})
