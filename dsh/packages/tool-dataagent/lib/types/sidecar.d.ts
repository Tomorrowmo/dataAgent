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
    readonly id: number;
    readonly name: string;
    readonly rows: number;
    readonly columns: number;
    /** `source` for an uploaded file, `derived` for an algorithm output. */
    readonly kind: string;
    /** Parent dataset id when this one was derived, else null. */
    readonly derived_from: number | null;
    /** How this dataset came to be: parent plus the operation that produced it. */
    readonly lineage: Record<string, unknown>;
    readonly description: string;
}
/** One algorithm in the catalogue. */
export interface AlgorithmRow {
    readonly id: number;
    readonly slug: string;
    readonly name: string;
    readonly category: string;
    readonly description: string;
    /** `builtin`, `user`, or `ai` — provenance decides how much it can be trusted. */
    readonly source: string;
    readonly params_schema: Record<string, unknown>;
    readonly returns: string;
    readonly is_verified: boolean;
}
/** A tabular preview: column names plus a bounded row window. */
export interface PreviewPayload {
    readonly columns: readonly string[];
    readonly rows: readonly Record<string, unknown>[];
    readonly total_rows?: number;
}
/** The derived dataset an algorithm run produced. */
export interface DerivedDataset {
    readonly id: number;
    readonly name: string;
    readonly rows: number;
    readonly columns: number;
}
/**
 * A sidecar call that failed in a way the model should see verbatim.
 *
 * Carries the HTTP status so callers can tell "you asked for something that is
 * not there" (404) from "the compute plane is still waking up" (503) — the
 * second is worth retrying and the first never is.
 */
export declare class SidecarError extends Error {
    readonly message: string;
    readonly status: number;
    readonly path: string;
    constructor(message: string, status: number, path: string);
}
/** Reject a base URL that would expose an unauthenticated data plane. */
export declare function assertLoopback(baseUrl: string): void;
/** Client bound to one sidecar. */
export declare class SidecarClient {
    private readonly baseUrl;
    constructor(baseUrl: string);
    private request;
    /**
     * Raw GET against the sidecar.
     *
     * Public because the domain modules (wind-tunnel and, later, the flow and
     * codegen surfaces) own their own wire shapes: pulling every route into this
     * class would make it a second copy of the Python API rather than a client.
     */
    get<T>(path: string, signal: AbortSignal): Promise<T>;
    /** Raw POST against the sidecar. See {@link get} for why this is public. */
    post<T>(path: string, payload: unknown, signal: AbortSignal): Promise<T>;
    /** Every dataset the instance owner has, sources and derived alike. */
    listDatasets(signal: AbortSignal): Promise<DatasetRow[]>;
    /** A bounded row window of one dataset. */
    previewDataset(id: number, limit: number, signal: AbortSignal): Promise<PreviewPayload>;
    /** The algorithm catalogue: built-ins plus whatever the owner has added. */
    listAlgorithms(signal: AbortSignal): Promise<AlgorithmRow[]>;
    /**
     * Run an algorithm and keep its table as a derived dataset.
     *
     * This is the materializing path, not a scratch run: the sidecar records the
     * parent and the operation, so the result carries its own provenance and the
     * lineage tree stays complete.
     */
    runToDataset(slug: string, datasetId: number, params: Record<string, unknown>, signal: AbortSignal): Promise<DerivedDataset>;
    /** Liveness plus warmup state — the sidecar answers this before its heavy imports finish. */
    health(signal: AbortSignal): Promise<{
        ok: boolean;
        ready: boolean;
    }>;
}
