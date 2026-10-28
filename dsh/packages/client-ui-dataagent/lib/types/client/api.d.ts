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
    readonly id: number;
    readonly name: string;
    readonly rows: number;
    readonly columns: number;
    readonly kind: string;
    readonly derived_from: number | null;
    readonly description: string;
    readonly lineage?: {
        readonly op?: {
            readonly slug?: string;
            readonly label?: string;
        };
    };
}
/** One algorithm in the catalogue. */
export interface Algorithm {
    readonly slug: string;
    readonly name: string;
    readonly category: string;
    readonly description: string;
    readonly source: string;
    readonly verified?: boolean;
}
/** A bounded row window. */
export interface Preview {
    readonly columns: readonly string[];
    readonly rows: readonly Record<string, unknown>[];
}
/** A read that failed, carrying enough to tell the reader what to do about it. */
export declare class ApiError extends Error {
    readonly status: number;
    constructor(message: string, status: number);
}
export declare const api: {
    datasets: (signal?: AbortSignal) => Promise<Dataset[]>;
    dataset: (id: number, signal?: AbortSignal) => Promise<Dataset>;
    preview: (id: number, limit: number, signal?: AbortSignal) => Promise<Preview>;
    algorithms: (signal?: AbortSignal) => Promise<Algorithm[]>;
};
