import type { MarketDetail, MarketSummary, PricePoint, Tick, WeekendRecord } from './types'

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

const KEY_STORAGE = 'terminal.writeKey'

export function getWriteKey(): string | null {
  try {
    return localStorage.getItem(KEY_STORAGE)
  } catch {
    return null
  }
}

export function setWriteKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key)
    else localStorage.removeItem(KEY_STORAGE)
  } catch {
    // private window or blocked storage: the key lasts for this page only
  }
}

/** An error from the backend. `detail` is the backend's own text, already written for people. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init: RequestInit = {}, write = false): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('content-type', 'application/json')
  if (write) {
    const key = getWriteKey()
    if (key) headers.set('X-Terminal-Key', key)
  }
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'cannot reach the terminal backend')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const api = {
  markets: () => request<MarketSummary[]>('/markets'),
  market: (id: string) => request<MarketDetail>(`/markets/${encodeURIComponent(id)}`),
  ticks: (id: string, limit = 200) => request<Tick[]>(`/markets/${encodeURIComponent(id)}/ticks?limit=${limit}`),
  prices: (id: string, since = 0) => request<PricePoint[]>(`/markets/${encodeURIComponent(id)}/prices?since=${since}`),
  record: () => request<WeekendRecord>('/record'),

  addMarket: (query: string, pollSeconds = 900) =>
    request<MarketDetail & { matched: boolean }>(
      '/markets',
      { method: 'POST', body: JSON.stringify({ query, poll_seconds: pollSeconds }) },
      true,
    ),
  addTick: (id: string, text: string, kind: 'mic' | 'typed') =>
    request<Tick>(
      `/markets/${encodeURIComponent(id)}/ticks`,
      { method: 'POST', body: JSON.stringify({ text, kind }) },
      true,
    ),
  deleteMarket: (id: string) =>
    request<{ deleted: string }>(`/markets/${encodeURIComponent(id)}`, { method: 'DELETE' }, true),
}
