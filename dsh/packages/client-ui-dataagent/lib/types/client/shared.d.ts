/**
 * Shared helpers for the keyed tool views.
 *
 * Everything here derives from the durable call/result slice only — no live
 * service reads, no clock, no randomness — so a view replays identically from
 * the session log.
 *
 * @module
 */
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client';
/** Lifecycle of one tool call, derived from the block alone. */
export type CallState = 'running' | 'ok' | 'error' | 'stopped';
/** Classify a call without consulting anything outside its own slice. */
export declare function callState(block: ToolCallViewProps['block']): CallState;
/**
 * Read the card data a tool projected through `output.presentationMeta`.
 *
 * This is the only structured payload a view may rely on. The canonical return
 * value is not persisted, and the content blocks carry prose written for the
 * model — parsing that prose back into fields would break the moment the
 * wording changed. `presentationMeta` exists precisely so the card has its own
 * replayable contract.
 *
 * Returns `null` while the call is still running, when the producing tool
 * projected nothing, or when an older log predates the projection — every one
 * of which is a normal state the caller handles by falling back to text.
 */
export declare function cardMeta<T>(block: ToolCallViewProps['block']): T | null;
/** Flatten the durable result blocks to text, matching ui-tool's generic row. */
export declare function resultText(block: ToolCallViewProps['block']): string | null;
/** Read the call arguments, tolerating the truncated JSON prefix a stream can expose. */
export declare function callArgs<T extends object>(block: ToolCallViewProps['block']): Partial<T>;
