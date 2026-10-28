/**
 * Self-extension: the model writes an algorithm, the sandbox tests it, the human
 * approves it, and only then does it become a permanent callable tool.
 *
 * This is the product's core claim — "curated classical algorithms first,
 * sandboxed user code second, model-written code only as a last resort, and
 * only after a test passes and the human approves" — so the gate is enforced
 * here rather than described in a prompt:
 *
 *   1. `algo_test` runs the code through the Python AST whitelist and the
 *      subprocess sandbox (rlimits, wall-clock kill, no network) against a real
 *      dataset, and records the hash of code that actually passed.
 *   2. `algo_save` refuses any code whose hash is not in that set. A model that
 *      skips the test cannot persist anything, and neither can one that edits
 *      the code after testing — the hash covers the exact bytes that ran.
 *   3. When a UI is mounted, `algo_save` additionally pauses on a human
 *      decision through `ctx.userQuestions`. Without a UI (headless), the
 *      sandbox gate still holds and the save is recorded as untrusted-by-human.
 *
 * The model writing the code is the harness model, not a second server-side
 * LLM. One model, one loop, one session log — the previous architecture had the
 * backend call its own LLM from inside a tool, which put half the reasoning
 * outside the transcript.
 *
 * @module
 */
import type { Context } from '@deepseek-ai/cordis';
import type { SidecarClient } from './sidecar.ts';
/**
 * Register the codegen tools.
 *
 * `passed` is plugin-closure state holding the hashes of code that cleared the
 * sandbox in this process. It is deliberately not persisted: a restart should
 * force a re-test rather than let a stale approval carry over.
 */
export declare function applyCodegenTools(ctx: Context, sidecar: SidecarClient, timeoutMs: number): void;
