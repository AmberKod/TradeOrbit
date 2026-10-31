export interface PrivateBalance {
  asset: string
  equity: string | null
  available: string | null
  wallet_balance: string | null
  unrealized_pnl: string | null
  equity_definition: string
}
export interface PrivatePosition {
  instrument: string
  side: 'LONG' | 'SHORT'
  quantity: string
  quantity_unit: 'BASE' | 'CONTRACT'
  margin_asset: string | null
  entry_price: string | null
  mark_price: string | null
  liquidation_price: string | null
  unrealized_pnl: string | null
  leverage: string | null
  margin_ratio: string | null
  margin_ratio_definition: string | null
  margin_mode: string | null
}
export interface PrivateScope {
  status: 'OK' | 'FAILED'
  error_code: string | null
  error_message: string | null
  observed_at: string | null
  age_seconds: number | null
  freshness: 'FRESH' | 'STALE' | 'MISSING'
  data: { balances: PrivateBalance[]; positions: PrivatePosition[]; metadata: Record<string, unknown> } | null
}
export interface AccountSnapshot {
  account_id: string
  credential_version: number
  state: 'NOT_VERIFIED' | 'VERIFIED' | 'PARTIAL' | 'FAILED'
  checked_at: string | null
  trading_enabled: false
  sync_supported: boolean
  sync_block_reason: string | null
  transport: 'MANUAL_REST'
  stale_after_seconds: number
  /** Client-only receipt time; never sent to the backend or persisted. */
  received_monotonic_ms?: number
  scopes: Record<string, PrivateScope>
}
export const readStateNames: Record<string, string> = { NOT_VERIFIED: '未验证', VERIFIED: '上次读取通过', PARTIAL: '部分读取成功', FAILED: '读取失败' }
export const scopeNames: Record<string, string> = {
  spot_balances: '现货钱包', usdm_balances: 'USDⓈ-M 合约钱包', usdm_positions: 'USDⓈ-M 持仓',
  usdt_futures_balances: 'USDT 合约钱包', usdt_futures_positions: 'USDT 合约持仓',
  uta_config: 'UTA 账户设置', uta_balances: 'UTA 共享钱包', uta_positions: 'UTA · USDT 合约持仓',
  account_config: '统一账户设置', trading_balances: '统一交易钱包', funding_balances: '资金钱包', swap_positions: '永续合约持仓',
}
