/**
 * Typed HTTP client for the RLab Cortex compute sidecar.
 *
 * The sidecar owns everything that needs pandas/scipy/sklearn: the algorithm
 * catalogue, the AST-validated Python sandbox, dataset storage with its lineage
 * DAG, and the wind-tunnel domain modules. This module is the only place in the
 * plugin that knows its wire shapes — tools depend on the functions here, never
 * on raw URLs.
 *
 * The sidecar has no authentication by design: one instance serves one user and
 * listens on loopback only. Reaching it over a non-loopback address would mean
 * an unauthenticated data plane on the network, so the base URL is checked once
 * at plugin load.
 *
 * @module
 */

/** One dataset as the compute sidecar reports it. */
export interface DatasetRow {
  readonly id: number
  readonly name: string
  readonly rows: number
  readonly columns: number
  /** `source` for an uploaded file, `derived` for an algorithm output. */
  readonly kind: string
  /** Parent dataset id when this one was derived, else null. */
  readonly derived_from: number | null
  /** How this dataset came to be: parent plus the operation that produced it. */
  readonly lineage: Record<string, unknown>
  readonly description: string
}

/** One algorithm in the catalogue. */
export interface AlgorithmRow {
  readonly id: number
  readonly slug: string
  readonly name: string
  readonly category: string
  readonly description: string
  /** `builtin`, `user`, or `ai` — provenance decides how much it can be trusted. */
  readonly source: string
  readonly params_schema: Record<string, unknown>
  readonly returns: string
  readonly is_verified: boolean
}

/** A tabular preview: column names plus a bounded row window. */
export interface PreviewPayload {
  readonly columns: readonly string[]
  readonly rows: readonly Record<string, unknown>[]
  readonly total_rows?: number
}

/** The derived dataset an algorithm run produced. */
export interface DerivedDataset {
  readonly id: number
  readonly name: string
  readonly rows: number
  readonly columns: number
}

/**
 * A sidecar call that failed in a way the model should see verbatim.
 *
 * Carries the HTTP status so callers can tell "you asked for something that is
 * not there" (404) from "the compute plane is still waking up" (503) — the
 * second is worth retrying and the first never is.
 */
export class SidecarError extends Error {
  constructor(
    override readonly message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message)
    this.name = 'SidecarError'
  }
}

/** Reject a base URL that would expose an unauthenticated data plane. */
export function assertLoopback(baseUrl: string): void {
  let host: string
  try {
    host = new URL(baseUrl).hostname
  } catch {
    throw new Error(`tool-dataagent: baseUrl is not a valid URL: ${baseUrl}`)
  }
  const loopback = host === '127.0.0.1' || host === 'localhost' || host === '::1'
  if (!loopback) {
    throw new Error(
      `tool-dataagent: baseUrl must be loopback (got ${host}). The compute sidecar `
      + 'has no authentication — binding it to a routable address would publish an '
      + 'unauthenticated data plane.',
    )
  }
}

/** Client bound to one sidecar. */
export class SidecarClient {
  constructor(private readonly baseUrl: string) {}

  private async request<T>(
    path: string,
    init: RequestInit,
    signal: AbortSignal,
  ): Promise<T> {
    const url = `${this.baseUrl.replace(/\/+$/, '')}${path}`
    let res: Response
    try {
      res = await fetch(url, { ...init, signal })
    } catch (e) {
      // A dead sidecar is infrastructure failure, not a domain result: throwing
      // marks the tool call isError so the model does not treat it as data.
      throw new SidecarError(
        `compute sidecar unreachable at ${this.baseUrl}: ${(e as Error).message}`,
        0, path,
      )
    }
    const body = await res.text()
    if (!res.ok) {
      let detail = body.slice(0, 400)
      try {
        const parsed = JSON.parse(body) as { detail?: unknown }
        if (typeof parsed.detail === 'string') detail = parsed.detail
      } catch { /* body was not JSON — the truncated text is the best detail */ }
      throw new SidecarError(detail || `HTTP ${res.status}`, res.status, path)
    }
    return (body ? JSON.parse(body) : null) as T
  }

  /**
   * Raw GET against the sidecar.
   *
   * Public because the domain modules (wind-tunnel and, later, the flow and
   * codegen surfaces) own their own wire shapes: pulling every route into this
   * class would make it a second copy of the Python API rather than a client.
   */
  get<T>(path: string, signal: AbortSignal): Promise<T> {
    return this.request<T>(path, { method: 'GET' }, signal)
  }

  /** Raw POST against the sidecar. See {@link get} for why this is public. */
  post<T>(path: string, payload: unknown, signal: AbortSignal): Promise<T> {
    return this.request<T>(path, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    }, signal)
  }

  /** Every dataset the instance owner has, sources and derived alike. */
  listDatasets(signal: AbortSignal): Promise<DatasetRow[]> {
    return this.get<DatasetRow[]>('/api/datasets', signal)
  }

  /** A bounded row window of one dataset. */
  previewDataset(id: number, limit: number, signal: AbortSignal): Promise<PreviewPayload> {
    return this.get<PreviewPayload>(
      `/api/datasets/${id}/preview?limit=${encodeURIComponent(String(limit))}`, signal)
  }

  /** The algorithm catalogue: built-ins plus whatever the owner has added. */
  listAlgorithms(signal: AbortSignal): Promise<AlgorithmRow[]> {
    return this.get<AlgorithmRow[]>('/api/algorithms', signal)
  }

  /**
   * Run an algorithm and keep its table as a derived dataset.
   *
   * This is the materializing path, not a scratch run: the sidecar records the
   * parent and the operation, so the result carries its own provenance and the
   * lineage tree stays complete.
   */
  runToDataset(
    slug: string,
    datasetId: number,
    params: Record<string, unknown>,
    signal: AbortSignal,
  ): Promise<DerivedDataset> {
    return this.post<DerivedDataset>('/api/algorithms/run-to-dataset',
      { slug, dataset_id: datasetId, params }, signal)
  }

  /** Liveness plus warmup state — the sidecar answers this before its heavy imports finish. */
  health(signal: AbortSignal): Promise<{ ok: boolean, ready: boolean }> {
    return this.get<{ ok: boolean, ready: boolean }>('/api/health', signal)
  }
}
