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
import { basename, extname, isAbsolute, resolve as resolvePath } from 'node:path';
import { readFile, stat } from 'node:fs/promises';
import { defineTool } from '@deepseek-ai/dsh-tools';
/** Upper bound on an ingested file, mirroring the sidecar's own 200 MiB cap. */
const MAX_INGEST_BYTES = 200 * 1024 * 1024;
export function applyPipelineTools(ctx, sidecar, baseUrl, timeoutMs) {
    ctx.systemPrompt.section({
        name: 'tool:dataagent-pipeline',
        order: 123,
        text: '用户给你一个数据文件路径时，用 dataset_ingest 把它变成数据集再分析。'
            + '当一段分析步骤以后还会重复用（比如每批新数据都要走同样的清洗和滤波），'
            + '用 flow_save 存成流程模板，之后用 flow_replay 在新数据集上重放——'
            + '重放会逐步串联并落下带血缘的中间结果，比让你每次重新调一遍算法更可靠。',
    });
    ctx.tools.register(defineTool({
        name: 'dataset_ingest',
        description: 'Read a data file from disk and register it as a dataset. '
            + 'Supports CSV / Excel / Parquet / JSON and the mesh formats the platform knows.',
        parameters: {
            path: { type: 'string', required: true, description: 'Absolute path to the file.' },
            name: { type: 'string', description: 'Display name; defaults to the file name.' },
            description: { type: 'string' },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    status: { type: 'string', required: true },
                    datasetId: { type: 'number' },
                    name: { type: 'string' },
                    rows: { type: 'number' },
                    columns: { type: 'number' },
                    columnNames: { type: 'array', items: { type: 'string' } },
                    extraDatasets: { type: 'number' },
                    stagingPath: { type: 'string' },
                    extension: { type: 'string' },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.status === 'needs_parser'
                        ? `平台还不认识 ${value.extension ?? '这个'} 格式。文件已暂存：`
                            + `\n  ${value.stagingPath}`
                            + `\n写一个 parse(path) 返回 DataFrame 的解析器，用 parser_save 落地，`
                            + `之后这个扩展名的文件都会自动走它。`
                        : `已导入数据集 #${value.datasetId}「${value.name}」`
                            + `（${value.rows} 行 × ${value.columns} 列）`
                            + `\n列名：${(value.columnNames ?? []).join('、')}`
                            + ((value.extraDatasets ?? 0) > 0
                                ? `\n该文件还拆出了另外 ${value.extraDatasets} 个数据集（多 sheet），用 dataset_list 查看。`
                                : ''),
                }],
            presentationMeta: (_args, value) => ({
                status: value.status,
                ...value.datasetId !== undefined ? { datasetId: value.datasetId } : {},
                ...value.name !== undefined ? { name: value.name } : {},
                ...value.rows !== undefined ? { rows: value.rows } : {},
                ...value.columns !== undefined ? { columns: value.columns } : {},
            }),
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            if (!isAbsolute(args.path)) {
                throw new Error(`path 必须是绝对路径，收到「${args.path}」`);
            }
            const target = resolvePath(args.path);
            let size;
            try {
                const st = await stat(target);
                if (!st.isFile())
                    throw new Error('不是一个文件');
                size = st.size;
            }
            catch (e) {
                throw new Error(`读不到文件 ${target}：${e.message}`);
            }
            if (size > MAX_INGEST_BYTES) {
                throw new Error(`文件 ${(size / 1024 / 1024).toFixed(1)} MiB，超过 200 MiB 上限。`);
            }
            const bytes = await readFile(target);
            const form = new FormData();
            form.append('file', new Blob([bytes]), basename(target));
            form.append('name', args.name ?? basename(target, extname(target)));
            if (args.description !== undefined)
                form.append('description', args.description);
            const res = await fetch(`${baseUrl.replace(/\/+$/, '')}/api/datasets`, {
                method: 'POST', body: form, signal: exec.signal,
            });
            const text = await res.text();
            if (!res.ok) {
                let detail = text.slice(0, 300);
                try {
                    const parsed = JSON.parse(text);
                    if (typeof parsed.detail === 'string')
                        detail = parsed.detail;
                }
                catch { /* not JSON; the truncated body is the best detail available */ }
                throw new Error(`导入失败（HTTP ${res.status}）：${detail}`);
            }
            const payload = JSON.parse(text);
            // An unrecognised format is a normal outcome with a next step, not a
            // failure: hand back the staging path so the model can write a parser.
            // Throwing here would end the turn on a dead end instead.
            const pending = payload.needs_parser;
            if (pending !== undefined && pending !== null) {
                return {
                    status: 'needs_parser',
                    stagingPath: pending.staging_path,
                    extension: pending.extension,
                };
            }
            const ds = payload.dataset;
            if (ds === undefined) {
                throw new Error(`导入没有产出数据集：${text.slice(0, 200)}`);
            }
            const extra = Math.max(0, (payload.datasets?.length ?? 1) - 1);
            return {
                status: 'ok',
                datasetId: ds.id,
                name: ds.name,
                rows: ds.rows,
                columns: ds.columns,
                columnNames: (ds.schema?.columns ?? []).map(c => c.name),
                extraDatasets: extra,
            };
        },
        presentCall: args => ({
            card: 'generic', title: `导入数据文件`, kind: 'read',
            locations: [{ path: args.path }],
        }),
    }));
    ctx.tools.register(defineTool({
        name: 'flow_save',
        description: 'Save an ordered sequence of algorithm steps as a reusable pipeline template.',
        parameters: {
            name: { type: 'string', required: true },
            description: { type: 'string' },
            steps: {
                type: 'array',
                required: true,
                description: 'Steps in order; each runs on the previous step\'s output.',
                items: {
                    type: 'object',
                    additionalProperties: false,
                    properties: {
                        slug: { type: 'string', required: true, description: 'Algorithm slug.' },
                        label: { type: 'string', description: 'Human-readable step name.' },
                        params: { type: 'object', additionalProperties: true, properties: {} },
                    },
                },
            },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    templateId: { type: 'number', required: true },
                    name: { type: 'string', required: true },
                    stepCount: { type: 'number', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `已保存流程模板 #${value.templateId}「${value.name}」，共 ${value.stepCount} 步。`
                        + `\n以后用 flow_replay 就能在别的数据集上重放这套步骤。`,
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            if (args.steps.length === 0)
                throw new Error('至少要有一个步骤');
            const r = await sidecar.post('/api/templates', {
                name: args.name,
                description: args.description ?? '',
                steps: args.steps.map(s => ({
                    action: 'run_tool',
                    slug: s.slug,
                    params: s.params ?? {},
                    ...s.label !== undefined ? { label: s.label } : {},
                })),
            }, exec.signal);
            return { templateId: r.id, name: r.name, stepCount: r.n_steps };
        },
        presentCall: args => ({ card: 'generic', title: `保存流程模板「${args.name}」` }),
    }));
    ctx.tools.register(defineTool({
        name: 'flow_list',
        description: 'List the saved pipeline templates and their steps.',
        parameters: {},
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    templates: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                id: { type: 'number', required: true },
                                name: { type: 'string', required: true },
                                description: { type: 'string' },
                                stepCount: { type: 'number', required: true },
                                steps: { type: 'array', required: true, items: { type: 'string' } },
                            },
                        },
                    },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.templates.length
                        ? value.templates.map(t => `#${t.id} ${t.name}（${t.stepCount} 步）：${t.steps.join(' → ')}`).join('\n')
                        : '还没有保存过流程模板。',
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(_args, exec) {
            const rows = await sidecar.get('/api/templates', exec.signal);
            return {
                templates: rows.map(t => ({
                    id: t.id,
                    name: t.name,
                    description: t.description ?? '',
                    stepCount: t.n_steps,
                    steps: (t.steps ?? []).map(s => String(s['label'] ?? s['slug'] ?? '?')),
                })),
            };
        },
        presentCall: () => ({ card: 'generic', title: '列出流程模板', kind: 'read' }),
    }));
    ctx.tools.register(defineTool({
        name: 'flow_replay',
        description: 'Replay a saved pipeline on a dataset. Each step runs on the previous step\'s '
            + 'output and every intermediate result is kept as a lineage-tracked derived dataset.',
        parameters: {
            template_id: { type: 'number', required: true },
            dataset_id: { type: 'number', required: true, description: 'Dataset to feed the first step.' },
            param_overrides: {
                type: 'object', additionalProperties: true, properties: {},
                description: 'Per-step parameter overrides keyed by step index as a string, e.g. {"1": {"window": 9}}.',
            },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    templateId: { type: 'number', required: true },
                    sourceDatasetId: { type: 'number', required: true },
                    steps: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                index: { type: 'number', required: true },
                                label: { type: 'string', required: true },
                                status: { type: 'string', required: true },
                                rows: { type: 'number' },
                                error: { type: 'string' },
                            },
                        },
                    },
                    derivedDatasetIds: { type: 'array', required: true, items: { type: 'number' } },
                    finalDatasetId: { type: 'number' },
                    failedSteps: { type: 'number', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: [
                        `流程 #${value.templateId} 在数据集 #${value.sourceDatasetId} 上重放：`,
                        ...value.steps.map(s => `  ${s.index + 1}. ${s.label} — ${s.status}`
                            + (s.rows !== undefined ? `（${s.rows} 行）` : '')
                            + (s.error ? `：${s.error}` : '')),
                        value.failedSteps > 0
                            ? `有 ${value.failedSteps} 步失败，结果不完整。`
                            : `全部成功，产出 ${value.derivedDatasetIds.length} 个带血缘的派生数据集。`
                                + (value.finalDatasetId !== undefined ? `最终结果 #${value.finalDatasetId}。` : ''),
                    ].join('\n'),
                }],
            presentationMeta: (_args, value) => ({
                templateId: value.templateId,
                sourceDatasetId: value.sourceDatasetId,
                steps: value.steps,
                derivedDatasetIds: value.derivedDatasetIds,
            }),
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            const r = await sidecar.post(`/api/templates/${args.template_id}/run`, {
                dataset_id: args.dataset_id,
                save_result: true,
                param_overrides: (args.param_overrides ?? {}),
            }, exec.signal);
            const steps = (r.steps ?? []).map(s => ({
                index: s.i,
                label: s.label,
                status: s.status,
                ...typeof s.rows === 'number' ? { rows: s.rows } : {},
                ...s.error ? { error: s.error } : {},
            }));
            const chain = r.derived_chain ?? [];
            // The final dataset is the last output that actually carried data forward.
            // A trailing report (a statistics table, say) is materialized and worth
            // listing, but calling it "the result of the pipeline" would point the next
            // step at a summary instead of the transformed data.
            const lastData = [...chain].reverse().find(d => d.report !== true);
            return {
                templateId: args.template_id,
                sourceDatasetId: args.dataset_id,
                steps,
                derivedDatasetIds: chain.map(d => d.id),
                ...lastData !== undefined ? { finalDatasetId: lastData.id } : {},
                failedSteps: steps.filter(s => s.status !== 'ok').length,
            };
        },
        presentCall: args => ({
            card: 'generic',
            title: `重放流程 #${args.template_id} 于数据集 #${args.dataset_id}`,
        }),
    }));
}
