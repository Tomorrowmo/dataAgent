/**
 * Model-facing data-analysis tools over the RLab Cortex compute sidecar.
 *
 * This package replaces the JSON-action ReAct loop that used to live in
 * `backend/app/services/chat_agent.py`. That loop hand-rolled its own action
 * vocabulary, JSON self-repair, enum guessing guards and an 8-step ceiling;
 * none of that is needed once the harness owns tool calling, so the tools here
 * are thin and the reasoning is the model's.
 *
 * What stays behind the sidecar and never moves into TypeScript: the curated
 * classical algorithms, the AST-validated Python sandbox, and the wind-tunnel
 * domain modules. They are built on pandas/scipy/sklearn, and a rewrite would
 * throw away the evidence chain that pins their output to the customer's own
 * production numbers.
 *
 * @module @rlab/dsh-tool-dataagent
 */
import type { Context } from '@deepseek-ai/cordis';
import z from '@deepseek-ai/schemastery';
export { SidecarClient, SidecarError, assertLoopback } from './sidecar.ts';
export type { AlgorithmRow, DatasetRow, DerivedDataset, PreviewPayload } from './sidecar.ts';
/** Cordis plugin name used by loader diagnostics. */
export declare const name = "tool-dataagent";
/** Services required by the data-analysis tool suite. */
export declare const inject: string[];
/** Default row window for `dataset_preview`. */
export declare const DEFAULT_PREVIEW_ROWS = 20;
/** Upper bound on one preview, so a wide table cannot flood the context. */
export declare const MAX_PREVIEW_ROWS = 200;
/** Default cooperative timeout for a sidecar call (ms). */
export declare const DEFAULT_TIMEOUT_MS = 120000;
/** Plugin config. */
export interface Config {
    /** Compute sidecar base URL. Must be loopback — the sidecar has no auth. */
    baseUrl?: string;
    /** Cooperative timeout budget (ms) for one sidecar call. */
    timeoutMs?: number;
    /** Register the wind-tunnel quality-check tools. Defaults to true. */
    windtunnel?: boolean;
    /** Register the self-extension tools (model writes an algorithm, sandbox gates it). Defaults to true. */
    codegen?: boolean;
}
export declare const Config: z<Config>;
/**
 * Register the data-analysis tools.
 *
 * Reads are marked concurrency-safe; `algo_run` is not, because it writes a new
 * derived dataset and two racing runs against one parent would interleave in
 * the lineage tree.
 */
export declare function apply(ctx: Context, config: Config): void;
