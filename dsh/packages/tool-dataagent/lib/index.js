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
import z from '@deepseek-ai/schemastery';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { assertLoopback, SidecarClient, } from "./sidecar.js";
import { applyWindTunnelTools } from "./windtunnel.js";
import { applyCodegenTools } from "./codegen.js";
import { applyPipelineTools } from "./pipeline.js";
import { applyExtensionTools } from "./extend.js";
import { applyWebRoutes } from "./webroutes.js";
export { SidecarClient, SidecarError, assertLoopback } from "./sidecar.js";
/** Cordis plugin name used by loader diagnostics. */
export const name = 'tool-dataagent';
/** Services required by the data-analysis tool suite. */
export const inject = ['tools', 'systemPrompt'];
/** Default row window for `dataset_preview`. */
export const DEFAULT_PREVIEW_ROWS = 20;
/** Upper bound on one preview, so a wide table cannot flood the context. */
export const MAX_PREVIEW_ROWS = 200;
/** Default cooperative timeout for a sidecar call (ms). */
export const DEFAULT_TIMEOUT_MS = 120_000;
export const Config = z.object({
    baseUrl: z.string().default('http://127.0.0.1:8078'),
    timeoutMs: z.number().default(DEFAULT_TIMEOUT_MS),
    windtunnel: z.boolean().default(true),
    codegen: z.boolean().default(true),
});
/** Human-readable one-line summary of a dataset, lineage included. */
function describeDataset(d) {
    const shape = `${d.rows} 行 × ${d.columns} 列`;
    const origin = d.kind === 'derived' && d.derived_from !== null
        ? `派生自 #${d.derived_from}`
        : '源数据';
    return `#${d.id} ${d.name}（${shape}，${origin}）`;
}
/** Human-readable one-line summary of an algorithm. */
function describeAlgorithm(a) {
    const provenance = a.source === 'builtin' ? '内置'
        : a.source === 'ai' ? 'AI 生成' : '用户上传';
    const vetted = a.source === 'builtin' || a.is_verified ? '' : '（未通过测试）';
    return `${a.slug} — ${a.name}｜${a.category}｜${provenance}${vetted}`;
}
/** Render a preview as a plain text table the model can read without parsing tricks. */
function renderPreview(columns, rows) {
    if (!rows.length)
        return '（无数据行）';
    const head = columns.join('\t');
    const body = rows.map(r => columns.map(c => {
        const v = r[c];
        return v === null || v === undefined ? '' : String(v);
    }).join('\t'));
    return [head, ...body].join('\n');
}
/**
 * Register the data-analysis tools.
 *
 * Reads are marked concurrency-safe; `algo_run` is not, because it writes a new
 * derived dataset and two racing runs against one parent would interleave in
 * the lineage tree.
 */
export function apply(ctx, config) {
    const resolved = config;
    assertLoopback(resolved.baseUrl);
    const sidecar = new SidecarClient(resolved.baseUrl);
    const timeoutMs = resolved.timeoutMs;
    ctx.systemPrompt.section({
        name: 'tool:dataagent',
        order: 120,
        text: '数据分析能力由一组经过验证的经典算法提供，不要用临时写的 pandas 代码替代它们。'
            + '先用 dataset_list 找到数据、algo_list 找到合适的算法、algo_describe 看清参数，'
            + '再用 algo_run 执行。algo_run 的结果会成为一个带血缘的派生数据集，'
            + '可以作为下一步的输入，从而把多步分析串成可追溯的链条。',
    });
    ctx.tools.register(defineTool({
        name: 'dataset_list',
        description: 'List the available datasets, including derived ones and how each was produced.',
        parameters: {},
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    datasets: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                id: { type: 'number', required: true },
                                name: { type: 'string', required: true },
                                rows: { type: 'number', required: true },
                                columns: { type: 'number', required: true },
                                kind: { type: 'string', required: true },
                                derivedFrom: { type: 'number' },
                                description: { type: 'string' },
                            },
                        },
                    },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.datasets.length
                        ? value.datasets.map(d => `#${d.id} ${d.name}（${d.rows} 行 × ${d.columns} 列，`
                            + `${d.kind === 'derived' && d.derivedFrom !== undefined
                                ? `派生自 #${d.derivedFrom}` : '源数据'}）`).join('\n')
                        : '还没有任何数据集。',
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(_args, exec) {
            const rows = await sidecar.listDatasets(exec.signal);
            return {
                datasets: rows.map(d => ({
                    id: d.id,
                    name: d.name,
                    rows: d.rows,
                    columns: d.columns,
                    kind: d.kind,
                    ...d.derived_from !== null && d.derived_from !== undefined
                        ? { derivedFrom: d.derived_from } : {},
                    description: d.description ?? '',
                })),
            };
        },
        presentCall: () => ({ card: 'generic', title: '列出数据集', kind: 'read' }),
    }));
    ctx.tools.register(defineTool({
        name: 'dataset_preview',
        description: 'Preview the first rows of one dataset, with its column names.',
        parameters: {
            dataset_id: { type: 'number', required: true, description: 'Dataset id from dataset_list.' },
            limit: { type: 'number', description: `Rows to return (default ${DEFAULT_PREVIEW_ROWS}, max ${MAX_PREVIEW_ROWS}).` },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    datasetId: { type: 'number', required: true },
                    columns: { type: 'array', required: true, items: { type: 'string' } },
                    rowCount: { type: 'number', required: true },
                    preview: { type: 'string', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `数据集 #${value.datasetId}，${value.columns.length} 列，`
                        + `返回 ${value.rowCount} 行：\n${value.preview}`,
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(args, exec) {
            const requested = args.limit ?? DEFAULT_PREVIEW_ROWS;
            if (!Number.isInteger(requested) || requested < 1) {
                throw new Error(`limit 必须是正整数，收到 ${requested}`);
            }
            const limit = Math.min(requested, MAX_PREVIEW_ROWS);
            const p = await sidecar.previewDataset(args.dataset_id, limit, exec.signal);
            const columns = [...p.columns ?? []];
            const rows = [...p.rows ?? []];
            return {
                datasetId: args.dataset_id,
                columns,
                rowCount: rows.length,
                preview: renderPreview(columns, rows),
            };
        },
        presentCall: args => ({
            card: 'generic',
            title: `预览数据集 #${args.dataset_id}`,
            kind: 'read',
        }),
    }));
    ctx.tools.register(defineTool({
        name: 'algo_list',
        description: 'List the vetted analysis algorithms, optionally filtered by category '
            + '(regression / filter / preprocess / structure / reduce).',
        parameters: {
            category: { type: 'string', description: 'Restrict to one category.' },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    algorithms: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                slug: { type: 'string', required: true },
                                name: { type: 'string', required: true },
                                category: { type: 'string', required: true },
                                source: { type: 'string', required: true },
                                description: { type: 'string' },
                            },
                        },
                    },
                    categories: { type: 'array', required: true, items: { type: 'string' } },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.algorithms.length
                        ? `${value.algorithms.length} 个算法（分类：${value.categories.join('、')}）\n`
                            + value.algorithms.map(a => `${a.slug} — ${a.name}｜${a.category}`).join('\n')
                        : '没有匹配的算法。',
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(args, exec) {
            const all = await sidecar.listAlgorithms(exec.signal);
            const picked = args.category
                ? all.filter(a => a.category === args.category)
                : all;
            return {
                algorithms: picked.map(a => ({
                    slug: a.slug,
                    name: a.name,
                    category: a.category,
                    source: a.source,
                    description: a.description ?? '',
                })),
                categories: [...new Set(all.map(a => a.category))].sort(),
            };
        },
        presentCall: args => ({
            card: 'generic',
            title: args.category ? `列出算法（${args.category}）` : '列出算法',
            kind: 'search',
        }),
    }));
    ctx.tools.register(defineTool({
        name: 'algo_describe',
        description: 'Show one algorithm\'s parameter schema and provenance before running it.',
        parameters: {
            slug: { type: 'string', required: true, description: 'Algorithm slug from algo_list.' },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    slug: { type: 'string', required: true },
                    name: { type: 'string', required: true },
                    category: { type: 'string', required: true },
                    source: { type: 'string', required: true },
                    description: { type: 'string', required: true },
                    returns: { type: 'string', required: true },
                    paramsSchema: { type: 'string', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `${value.slug} — ${value.name}\n分类：${value.category}｜来源：${value.source}`
                        + `｜返回：${value.returns}\n${value.description}\n参数：\n${value.paramsSchema}`,
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(args, exec) {
            const all = await sidecar.listAlgorithms(exec.signal);
            const a = all.find(x => x.slug === args.slug);
            if (!a) {
                // A wrong slug is a domain miss the model must be able to recover from,
                // so name the near misses instead of only saying "not found".
                const near = all.map(x => x.slug)
                    .filter(s => s.includes(args.slug) || args.slug.includes(s)).slice(0, 5);
                throw new Error(`没有 slug 为「${args.slug}」的算法`
                    + (near.length ? `。相近的有：${near.join('、')}` : '。用 algo_list 查看全部。'));
            }
            return {
                slug: a.slug,
                name: a.name,
                category: a.category,
                source: a.source,
                description: a.description ?? '',
                returns: a.returns ?? 'dataframe',
                paramsSchema: JSON.stringify(a.params_schema ?? {}, null, 2),
            };
        },
        presentCall: args => ({ card: 'generic', title: `查看算法 ${args.slug}`, kind: 'read' }),
    }));
    ctx.tools.register(defineTool({
        name: 'algo_run',
        description: 'Run a vetted algorithm on a dataset. The table it produces is kept as a new '
            + 'derived dataset carrying its lineage, so it can feed the next step.',
        parameters: {
            slug: { type: 'string', required: true, description: 'Algorithm slug.' },
            dataset_id: { type: 'number', required: true, description: 'Input dataset id.' },
            params: {
                type: 'object',
                additionalProperties: true,
                properties: {},
                description: 'Algorithm parameters, shaped by algo_describe.',
            },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    datasetId: { type: 'number', required: true },
                    name: { type: 'string', required: true },
                    rows: { type: 'number', required: true },
                    columns: { type: 'number', required: true },
                    derivedFrom: { type: 'number', required: true },
                    algorithm: { type: 'string', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `已用『${value.algorithm}』处理数据集 #${value.derivedFrom}，`
                        + `结果存为派生数据集 #${value.datasetId}「${value.name}」`
                        + `（${value.rows} 行 × ${value.columns} 列）。`,
                }],
            // The lineage edge is persisted so the UI card can redraw it on replay
            // without re-querying a dataset that may since have been deleted.
            presentationMeta: (_args, value) => ({
                algorithm: value.algorithm,
                derivedFrom: value.derivedFrom,
                datasetId: value.datasetId,
                name: value.name,
                rows: value.rows,
                columns: value.columns,
            }),
        },
        timeoutMs,
        // Writes a derived dataset — two racing runs would interleave in the lineage tree.
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            const params = (args.params ?? {});
            const d = await sidecar.runToDataset(args.slug, args.dataset_id, params, exec.signal);
            return {
                datasetId: d.id,
                name: d.name,
                rows: d.rows,
                columns: d.columns,
                derivedFrom: args.dataset_id,
                algorithm: args.slug,
            };
        },
        presentCall: args => ({
            card: 'generic',
            title: `运行 ${args.slug} 于数据集 #${args.dataset_id}`,
        }),
    }));
    if (resolved.windtunnel)
        applyWindTunnelTools(ctx, sidecar, timeoutMs);
    if (resolved.codegen) {
        applyCodegenTools(ctx, sidecar, timeoutMs);
        applyExtensionTools(ctx, sidecar, timeoutMs);
    }
    applyPipelineTools(ctx, sidecar, resolved.baseUrl, timeoutMs);
    applyWebRoutes(ctx, resolved.baseUrl);
}
