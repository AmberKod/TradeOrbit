export type Role = 'ADMIN' | 'TRADER' | 'VIEWER'
export type Exchange = 'binance' | 'bitget' | 'okx'
export type Environment = 'DEMO' | 'LIVE'
export type AccountMode = 'STANDARD' | 'CLASSIC' | 'UTA' | 'UNIFIED' | 'UNKNOWN'
export interface Session { user: { id: string; email: string }; workspace: { id: string; name: string }; role: Role; csrf_token: string }
export interface Account { id: string; label: string; exchange: Exchange; environment: Environment; account_mode: AccountMode; region_profile: string; status: string; credentials_configured: boolean; credential_version: number; capability_state: string; created_at: string; updated_at: string }
export interface AccountInput { label: string; exchange: Exchange; environment: Environment; account_mode: AccountMode; region_profile: string }
export interface SystemStatus { stage: string; version: string; app_environment: string; trading_enabled: boolean; checks: Record<string, string>; exchange_integration: string; workspace_id: string }
export interface AuditEntry { id: string; action: string; target_id: string | null; actor_id: string | null; request_id: string; details: Record<string, unknown>; created_at: string }
export const exchangeNames: Record<Exchange, string> = { binance: 'Binance', bitget: 'Bitget', okx: 'OKX 欧易' }
export const roleNames: Record<Role, string> = { ADMIN: '管理员', TRADER: '交易员', VIEWER: '观察者' }
