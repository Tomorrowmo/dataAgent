/**
 * RLab Cortex browser half: keyed tool views for the data-analysis tools.
 *
 * The generic tool row prints whatever text a tool rendered. That is fine for a
 * shell command, but it flattens the two things this product exists to keep
 * distinct: a finding that was *assessed and failed* versus an item that could
 * *not be assessed at all*. A wall of text lets 未评定 read like a pass, which
 * is precisely the failure mode the wind-tunnel module was built to prevent.
 *
 * So these views are not decoration. They encode, in form, the distinction the
 * domain refuses to blur.
 *
 * Views are pure functions of the durable call/result slice, so they replay
 * identically from the session log and never consult live services.
 *
 * @module
 */
import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client';
/** Required services: the keyed tool-view registry. */
export declare const inject: string[];
/**
 * Register the keyed tool views.
 *
 * Both keys name tools this product registered itself, so registration is
 * purely additive — nothing shipped by dsh is taken over.
 */
export declare function apply(ctx: ClientContext): void;
