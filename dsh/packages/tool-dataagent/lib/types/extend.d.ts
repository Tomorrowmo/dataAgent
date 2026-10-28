/**
 * The remaining self-extension surfaces: unknown file formats, messy tables,
 * and the vocabulary that maps a lab's column names onto known roles.
 *
 * Same shape as the algorithm channel in `codegen.ts` — the harness model writes
 * the Python, the sandbox runs it, and the result becomes durable only after it
 * has actually worked. What differs is the unit of work:
 *
 *   - a **parser** turns one unrecognised file into a table, and becomes a
 *     format adapter that every later upload of that extension reuses;
 *   - a **cleaner** turns one messy dataset into a tidy one, leaving the messy
 *     original untouched so the transformation stays auditable;
 *   - a **mapping** records that this lab writes `U(V)` where the platform
 *     means `voltage`, so the next file is understood without asking again.
 *
 * @module
 */
import type { Context } from '@deepseek-ai/cordis';
import type { SidecarClient } from './sidecar.ts';
export declare function applyExtensionTools(ctx: Context, sidecar: SidecarClient, timeoutMs: number): void;
