/**
 * Getting data in, and turning an ad-hoc analysis into a reusable recipe.
 *
 * Two capabilities live here because they are the two ends of the same arc: a
 * file becomes a dataset, a sequence of steps becomes something you can run
 * again on next week's file.
 *
 * `flow_replay` deliberately delegates the whole chain to the sidecar rather
 * than looping `algo_run` from the model. The Python side threads each step's
 * DataFrame into the next and knows which outputs are *transformed data* versus
 * a *report* — a statistics table has fewer rows than its input and must not
 * become the next step's input. That rule was learned from a real bug, and
 * re-deriving it in the tool layer would be re-deriving the bug.
 *
 * @module
 */
import type { Context } from '@deepseek-ai/cordis';
import type { SidecarClient } from './sidecar.ts';
export declare function applyPipelineTools(ctx: Context, sidecar: SidecarClient, baseUrl: string, timeoutMs: number): void;
