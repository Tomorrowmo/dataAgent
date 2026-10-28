/**
 * Same-origin HTTP bridge from the browser half to the compute sidecar.
 *
 * The views need to read datasets, algorithms and wind-tunnel results. They
 * must not fetch the sidecar directly: the sidecar is an unauthenticated
 * loopback service, and in the target deployment the browser reaches only the
 * gateway — a page that talks straight to :8078 works on one laptop and breaks
 * the moment there is more than one user.
 *
 * So the Host proxies. The browser calls `/rlab/api/...` on the page's own
 * origin, this plugin forwards it to the sidecar, and the path survives the
 * gateway unchanged because it is the harness that moves, not the page.
 *
 * Reads only. A browser button must not be able to run an algorithm, save code
 * or write a rule behind the model's back: those are tool calls, and they
 * belong in the session log where they can be replayed and audited.
 *
 * @module
 */
import type { Context } from '@deepseek-ai/cordis';
/** Route prefix owned by this plugin. */
export declare const RLAB_API_PREFIX = "/rlab/api";
/**
 * Register the bridge when a web server is mounted.
 *
 * `ctx.webServer` only exists in a Web composition, so the dependency is taken
 * through a nested fiber: a headless run gets the tools and no route, rather
 * than failing to load.
 */
export declare function applyWebRoutes(ctx: Context, baseUrl: string): void;
