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
/** A read that failed, carrying enough to tell the reader what to do about it. */
export class ApiError extends Error {
    status;
    constructor(message, status) {
        super(message);
        this.status = status;
        this.name = 'ApiError';
    }
}
async function get(path, signal) {
    const res = await fetch(`/rlab/api${path}`, {
        signal: signal ?? null,
        headers: { accept: 'application/json' },
    });
    const text = await res.text();
    if (!res.ok) {
        let detail = text.slice(0, 200);
        try {
            const parsed = JSON.parse(text);
            if (typeof parsed.detail === 'string')
                detail = parsed.detail;
            else if (typeof parsed.error === 'string')
                detail = parsed.error;
        }
        catch { /* keep the raw text */ }
        throw new ApiError(detail || `HTTP ${res.status}`, res.status);
    }
    return JSON.parse(text);
}
export const api = {
    datasets: (signal) => get('/datasets', signal),
    dataset: (id, signal) => get(`/datasets/${id}`, signal),
    preview: (id, limit, signal) => get(`/datasets/${id}/preview?limit=${limit}`, signal),
    algorithms: (signal) => get('/algorithms', signal),
};
