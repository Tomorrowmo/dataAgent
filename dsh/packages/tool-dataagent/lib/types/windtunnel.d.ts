/**
 * Model-facing wind-tunnel quality-check tools.
 *
 * The domain logic — parsers, balance handling, feature extraction, the rule
 * engine, trend detection (Mann-Kendall + Hampel + a calibrated Nelson rule),
 * repeatability and the report writer — stays in Python behind the sidecar. It
 * is pinned to the customer's own production numbers by a contract suite, and
 * a reimplementation would forfeit that evidence.
 *
 * What these tools add is the ability for a model to drive that pipeline and
 * reason about its output, which the previous JSON-action loop could not do.
 *
 * Two properties of the domain are deliberately surfaced in the tool schemas
 * rather than buried in prose, because they are the product's trust story:
 *
 *   - a check whose inputs are missing reports 未评定, never a silent pass, so
 *     `unavailable` is a first-class status alongside the severity levels;
 *   - every non-ok finding carries verdict / cause / impact / action, so the
 *     model never has to invent the reasoning that goes to a test engineer.
 *
 * @module
 */
import type { Context } from '@deepseek-ai/cordis';
import type { SidecarClient } from './sidecar.ts';
/** Register the wind-tunnel tools against an already-constructed sidecar client. */
export declare function applyWindTunnelTools(ctx: Context, sidecar: SidecarClient, timeoutMs: number): void;
