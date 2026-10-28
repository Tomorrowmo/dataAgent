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
/** Route prefix owned by this plugin. */
export const RLAB_API_PREFIX = '/rlab/api';
/** Methods the bridge forwards. Anything else is refused before it leaves the host. */
const ALLOWED = new Set(['GET', 'HEAD']);
/**
 * Register the bridge when a web server is mounted.
 *
 * `ctx.webServer` only exists in a Web composition, so the dependency is taken
 * through a nested fiber: a headless run gets the tools and no route, rather
 * than failing to load.
 */
export function applyWebRoutes(ctx, baseUrl) {
    ctx.inject(['webServer'], (wctx) => {
        wctx.effect(() => wctx.webServer.register({
            kind: 'prefix',
            path: RLAB_API_PREFIX,
            handler: (req, res) => {
                void forward(req, res, baseUrl);
            },
        }), 'tool-dataagent: /rlab/api bridge');
    });
}
/** Forward one browser request to the sidecar and stream the answer back. */
async function forward(req, res, baseUrl) {
    const method = (req.method ?? 'GET').toUpperCase();
    if (!ALLOWED.has(method)) {
        // Writes go through tools so they land in the session log. Say why, rather
        // than returning a bare 405 that looks like a missing route.
        res.writeHead(405, { 'content-type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({
            error: 'read-only bridge',
            detail: '写操作请走工具调用，以便进入会话日志、可回放可审计。',
        }));
        return;
    }
    const suffix = (req.url ?? '').slice(RLAB_API_PREFIX.length) || '/';
    const target = `${baseUrl.replace(/\/+$/, '')}/api${suffix}`;
    try {
        const upstream = await fetch(target, { method, signal: AbortSignal.timeout(60_000) });
        const body = Buffer.from(await upstream.arrayBuffer());
        res.writeHead(upstream.status, {
            'content-type': upstream.headers.get('content-type') ?? 'application/octet-stream',
            // The page is served fresh from the harness; a cached dataset list would
            // show stale rows right after a tool call changed them.
            'cache-control': 'no-store',
        });
        res.end(body);
    }
    catch (e) {
        res.writeHead(502, { 'content-type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({
            error: 'sidecar unreachable',
            detail: `${e.message}（计算面是否在 ${baseUrl} 运行？）`,
        }));
    }
}
