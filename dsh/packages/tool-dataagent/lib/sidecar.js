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
/**
 * A sidecar call that failed in a way the model should see verbatim.
 *
 * Carries the HTTP status so callers can tell "you asked for something that is
 * not there" (404) from "the compute plane is still waking up" (503) — the
 * second is worth retrying and the first never is.
 */
export class SidecarError extends Error {
    message;
    status;
    path;
    constructor(message, status, path) {
        super(message);
        this.message = message;
        this.status = status;
        this.path = path;
        this.name = 'SidecarError';
    }
}
/** Reject a base URL that would expose an unauthenticated data plane. */
export function assertLoopback(baseUrl) {
    let host;
    try {
        host = new URL(baseUrl).hostname;
    }
    catch {
        throw new Error(`tool-dataagent: baseUrl is not a valid URL: ${baseUrl}`);
    }
    const loopback = host === '127.0.0.1' || host === 'localhost' || host === '::1';
    if (!loopback) {
        throw new Error(`tool-dataagent: baseUrl must be loopback (got ${host}). The compute sidecar `
            + 'has no authentication — binding it to a routable address would publish an '
            + 'unauthenticated data plane.');
    }
}
/** Client bound to one sidecar. */
export class SidecarClient {
    baseUrl;
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
    async request(path, init, signal) {
        const url = `${this.baseUrl.replace(/\/+$/, '')}${path}`;
        let res;
        try {
            res = await fetch(url, { ...init, signal });
        }
        catch (e) {
            // A dead sidecar is infrastructure failure, not a domain result: throwing
            // marks the tool call isError so the model does not treat it as data.
            throw new SidecarError(`compute sidecar unreachable at ${this.baseUrl}: ${e.message}`, 0, path);
        }
        const body = await res.text();
        if (!res.ok) {
            let detail = body.slice(0, 400);
            try {
                const parsed = JSON.parse(body);
                if (typeof parsed.detail === 'string')
                    detail = parsed.detail;
            }
            catch { /* body was not JSON — the truncated text is the best detail */ }
            throw new SidecarError(detail || `HTTP ${res.status}`, res.status, path);
        }
        return (body ? JSON.parse(body) : null);
    }
    /**
     * Raw GET against the sidecar.
     *
     * Public because the domain modules (wind-tunnel and, later, the flow and
     * codegen surfaces) own their own wire shapes: pulling every route into this
     * class would make it a second copy of the Python API rather than a client.
     */
    get(path, signal) {
        return this.request(path, { method: 'GET' }, signal);
    }
    /** Raw POST against the sidecar. See {@link get} for why this is public. */
    post(path, payload, signal) {
        return this.request(path, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
        }, signal);
    }
    /** Every dataset the instance owner has, sources and derived alike. */
    listDatasets(signal) {
        return this.get('/api/datasets', signal);
    }
    /** A bounded row window of one dataset. */
    previewDataset(id, limit, signal) {
        return this.get(`/api/datasets/${id}/preview?limit=${encodeURIComponent(String(limit))}`, signal);
    }
    /** The algorithm catalogue: built-ins plus whatever the owner has added. */
    listAlgorithms(signal) {
        return this.get('/api/algorithms', signal);
    }
    /**
     * Run an algorithm and keep its table as a derived dataset.
     *
     * This is the materializing path, not a scratch run: the sidecar records the
     * parent and the operation, so the result carries its own provenance and the
     * lineage tree stays complete.
     */
    runToDataset(slug, datasetId, params, signal) {
        return this.post('/api/algorithms/run-to-dataset', { slug, dataset_id: datasetId, params }, signal);
    }
    /** Liveness plus warmup state — the sidecar answers this before its heavy imports finish. */
    health(signal) {
        return this.get('/api/health', signal);
    }
}
