interface Envelope<T> { data: T; meta: { request_id: string; schema_version?: number } }
interface Failure { error?: { code?: string; message?: string }; meta?: { request_id?: string } }
let csrf = ''
let unauthorizedHandler: () => void = () => undefined

export class ApiError extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number, public readonly requestId?: string) { super(message) }
}
export function setCsrfToken(value: string): void { csrf = value }
export function onUnauthorized(callback: () => void): void { unauthorizedHandler = callback }
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (init.method && !['GET', 'HEAD', 'OPTIONS'].includes(init.method.toUpperCase())) headers.set('X-CSRF-Token', csrf)
  let response: Response
  try { response = await fetch('/api/v1' + path, { ...init, credentials: 'include', headers }) }
  catch { throw new ApiError('NETWORK_ERROR', '无法连接后端，请检查服务与网络', 0) }
  let body: Envelope<T> & Failure
  try { body = await response.json() }
  catch { throw new ApiError('INVALID_RESPONSE', '服务返回了无法识别的响应', response.status) }
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler()
    throw new ApiError(body.error?.code ?? 'HTTP_ERROR', body.error?.message ?? '请求失败', response.status, body.meta?.request_id)
  }
  return body.data
}
