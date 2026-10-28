/**
 * Browser-side reads over the Host's same-origin bridge.
 *
 * Everything goes through `/rlab/api/...` on the page's own origin. The compute
 * sidecar is never addressed directly: it has no authentication, and in the
 * deployed shape the browser can only reach the gateway anyway.
 *
 * Reads only, by construction — the bridge refuses writes. Anything that
 * changes state is a tool call, so it lands in the session log where it can be
 * replayed and audited. A button that quietly mutated data outside that log
 * would break the product's own traceability claim.
 *
 * @module
 */

/** One dataset, as the compute plane reports it. */
export interface Dataset {
  readonly id: number
  readonly name: string
  readonly rows: number
  readonly columns: number
  readonly kind: string
  readonly derived_from: number | null
  readonly description: string
  readonly lineage?: { readonly op?: { readonly slug?: string, readonly label?: string } }
}

/** One algorithm in the catalogue. */
export interface Algorithm {
  readonly slug: string
  readonly name: string
  readonly category: string
  readonly description: string
  readonly source: string
  readonly verified?: boolean
}

/** A bounded row window. */
export interface Preview {
  readonly columns: readonly string[]
  readonly rows: readonly Record<string, unknown>[]
}

/** A read that failed, carrying enough to tell the reader what to do about it. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/rlab/api${path}`, {
    signal: signal ?? null,
    headers: { accept: 'application/json' },
  })
  const text = await res.text()
  if (!res.ok) {
    let detail = text.slice(0, 200)
    try {
      const parsed = JSON.parse(text) as { detail?: unknown, error?: unknown }
      if (typeof parsed.detail === 'string') detail = parsed.detail
      else if (typeof parsed.error === 'string') detail = parsed.error
    } catch { /* keep the raw text */ }
    throw new ApiError(detail || `HTTP ${res.status}`, res.status)
  }
  return JSON.parse(text) as T
}

export const api = {
  datasets: (signal?: AbortSignal) => get<Dataset[]>('/datasets', signal),
  dataset: (id: number, signal?: AbortSignal) => get<Dataset>(`/datasets/${id}`, signal),
  preview: (id: number, limit: number, signal?: AbortSignal) =>
    get<Preview>(`/datasets/${id}/preview?limit=${limit}`, signal),
  algorithms: (signal?: AbortSignal) => get<Algorithm[]>('/algorithms', signal),
}
