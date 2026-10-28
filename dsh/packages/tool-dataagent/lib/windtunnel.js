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
import { defineTool } from '@deepseek-ai/dsh-tools';
const NON_OK = new Set(['notice', 'warning', 'critical']);
/** Register the wind-tunnel tools against an already-constructed sidecar client. */
export function applyWindTunnelTools(ctx, sidecar, timeoutMs) {
    ctx.systemPrompt.section({
        name: 'tool:windtunnel',
        order: 121,
        text: '风洞试验质量检查有专门的工具链：wt_batch_list 看批次，wt_check 执行检查，'
            + 'wt_findings 看某个车次的逐条判定，wt_report 出报告。'
            + '关于判定结果有两条硬规矩，不要违反：'
            + '（1）status 为 unavailable 的项是「未评定」，表示输入不足，'
            + '绝不能当作合格，也不要替它猜一个结论——要如实说明缺什么；'
            + '（2）每条非 ok 判定都自带原因分析、影响评估、处理建议，'
            + '直接引用它们，不要自己另编一套说法。',
    });
    ctx.tools.register(defineTool({
        name: 'wt_batch_list',
        description: 'List the uploaded wind-tunnel batches and their check status.',
        parameters: {},
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    batches: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                id: { type: 'number', required: true },
                                name: { type: 'string', required: true },
                                status: { type: 'string', required: true },
                                runCount: { type: 'number', required: true },
                            },
                        },
                    },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.batches.length
                        ? value.batches.map(b => `#${b.id} ${b.name}（${b.runCount} 个车次，${b.status}）`).join('\n')
                        : '还没有上传任何风洞批次。',
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(_args, exec) {
            const rows = await sidecar.get('/api/wt/batches', exec.signal);
            return {
                batches: rows.map(b => ({
                    id: b.id,
                    name: b.name,
                    status: b.status,
                    runCount: b.runs?.length ?? 0,
                })),
            };
        },
        presentCall: () => ({ card: 'generic', title: '列出风洞批次', kind: 'read' }),
    }));
    ctx.tools.register(defineTool({
        name: 'wt_check',
        description: 'Run the quality checks over every run in a batch. Returns each run\'s grade, '
            + 'how many findings it raised, and how many items could not be assessed.',
        parameters: {
            batch_id: { type: 'number', required: true, description: 'Batch id from wt_batch_list.' },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    batchId: { type: 'number', required: true },
                    runs: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                runNo: { type: 'string', required: true },
                                grade: { type: 'string', required: true },
                                comparedWith: { type: 'string' },
                                problemCount: { type: 'number', required: true },
                                unavailableCount: { type: 'number', required: true },
                            },
                        },
                    },
                    flaggedTrends: { type: 'number', required: true },
                    trendCount: { type: 'number', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: [
                        `批次 #${value.batchId}，${value.runs.length} 个车次：`,
                        ...value.runs.map(r => `  ${r.runNo}　${r.grade}`
                            + `　异常 ${r.problemCount} 项　未评定 ${r.unavailableCount} 项`
                            + (r.comparedWith ? `　（与 ${r.comparedWith} 比对）` : '')),
                        `跨车次趋势：${value.trendCount} 条，其中 ${value.flaggedTrends} 条告警。`,
                    ].join('\n'),
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            const res = await sidecar.post(`/api/wt/batches/${args.batch_id}/check`, { rule_ids: [] }, exec.signal);
            const trends = res.trends ?? [];
            return {
                batchId: args.batch_id,
                runs: (res.runs ?? []).map(r => ({
                    runNo: r.run_no,
                    grade: r.grade,
                    ...r.compared_with ? { comparedWith: r.compared_with } : {},
                    problemCount: (r.findings ?? []).filter(f => NON_OK.has(f.level) && (f.status ?? 'evaluated') === 'evaluated').length,
                    unavailableCount: Object.values(r.features ?? {}).filter(f => f.status === 'unavailable').length,
                })),
                flaggedTrends: trends.filter(t => t.flagged).length,
                trendCount: trends.length,
            };
        },
        presentCall: args => ({ card: 'generic', title: `检查风洞批次 #${args.batch_id}` }),
    }));
    ctx.tools.register(defineTool({
        name: 'wt_findings',
        description: 'Show one run\'s findings in full: each non-ok verdict with its cause, impact '
            + 'and recommended action, plus every item that could not be assessed and why.',
        parameters: {
            batch_id: { type: 'number', required: true },
            run_no: { type: 'string', required: true, description: 'Run number, e.g. "91837".' },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    runNo: { type: 'string', required: true },
                    grade: { type: 'string', required: true },
                    problems: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                feature: { type: 'string', required: true },
                                level: { type: 'string', required: true },
                                value: { type: 'number' },
                                unit: { type: 'string' },
                                verdict: { type: 'string', required: true },
                                cause: { type: 'string', required: true },
                                impact: { type: 'string', required: true },
                                action: { type: 'string', required: true },
                            },
                        },
                    },
                    unavailable: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                feature: { type: 'string', required: true },
                                reason: { type: 'string', required: true },
                            },
                        },
                    },
                },
            },
            render: (_args, value) => {
                const lines = [`车次 ${value.runNo}：${value.grade}`];
                if (value.problems.length) {
                    lines.push('', '异常项：');
                    for (const p of value.problems) {
                        lines.push(`  · [${p.level}] ${p.feature}`
                            + (p.value !== undefined ? ` = ${p.value}${p.unit ?? ''}` : ''));
                        lines.push(`    判定：${p.verdict}`);
                        lines.push(`    原因分析：${p.cause}`);
                        lines.push(`    影响评估：${p.impact}`);
                        lines.push(`    处理建议：${p.action}`);
                    }
                }
                else {
                    lines.push('', '没有异常项。');
                }
                if (value.unavailable.length) {
                    lines.push('', '未评定项（输入不足，不代表合格）：');
                    for (const u of value.unavailable)
                        lines.push(`  · ${u.feature}：${u.reason}`);
                }
                return [{ type: 'text', text: lines.join('\n') }];
            },
            // Persisted so the card can keep 异常 and 未评定 visually separate on
            // replay. Parsing them back out of the rendered prose would tie the UI to
            // wording that exists for the model, not for the reader.
            presentationMeta: (_args, value) => ({
                runNo: value.runNo,
                grade: value.grade,
                problems: value.problems,
                unavailable: value.unavailable,
            }),
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(args, exec) {
            const b = await sidecar.get(`/api/wt/batches/${args.batch_id}`, exec.signal);
            const runs = b.result?.runs ?? [];
            const run = runs.find(r => r.run_no === args.run_no);
            if (!run) {
                const known = runs.map(r => r.run_no).slice(0, 12).join('、');
                throw new Error(`批次 #${args.batch_id} 里没有车次 ${args.run_no}`
                    + (known ? `。已有车次：${known}` : '。请先用 wt_check 执行检查。'));
            }
            return {
                runNo: run.run_no,
                grade: run.grade,
                problems: (run.findings ?? [])
                    .filter(f => NON_OK.has(f.level) && (f.status ?? 'evaluated') === 'evaluated')
                    .map(f => ({
                    feature: f.feature_name || f.feature || f.rule_id,
                    level: f.level_label || f.level,
                    ...typeof f.value === 'number' ? { value: f.value } : {},
                    ...f.unit ? { unit: f.unit } : {},
                    verdict: f.verdict ?? '',
                    cause: f.cause ?? '',
                    impact: f.impact ?? '',
                    action: f.action ?? '',
                })),
                unavailable: Object.entries(run.features ?? {})
                    .filter(([, v]) => v.status === 'unavailable')
                    .map(([k, v]) => ({ feature: k, reason: v.detail ?? '未说明' })),
            };
        },
        presentCall: args => ({
            card: 'generic', title: `查看车次 ${args.run_no} 的判定`, kind: 'read',
        }),
    }));
    ctx.tools.register(defineTool({
        name: 'wt_report',
        description: 'Generate the quality-check report or the shift record (跟班记录) for one run.',
        parameters: {
            batch_id: { type: 'number', required: true },
            run_no: { type: 'string', required: true },
            kind: {
                type: 'string',
                description: '"report" for the full quality report (default), "shift" for the shift record.',
            },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    reportId: { type: 'number', required: true },
                    filename: { type: 'string', required: true },
                    kind: { type: 'string', required: true },
                    characters: { type: 'number', required: true },
                    content: { type: 'string', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `已生成${value.kind === 'shift' ? '跟班记录' : '质量检查报告'}`
                        + `（#${value.reportId}，${value.filename}，${value.characters} 字）：\n\n${value.content}`,
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            const kind = args.kind === 'shift' ? 'shift' : 'report';
            const payload = { run_no: args.run_no, kind };
            if (kind === 'report') {
                payload['sections'] = ['overview', 'verdict', 'problems', 'unavailable', 'basis'];
            }
            const r = await sidecar.post(`/api/wt/batches/${args.batch_id}/report`, payload, exec.signal);
            return {
                reportId: r.id,
                filename: r.filename,
                kind,
                characters: r.content.length,
                content: r.content,
            };
        },
        presentCall: args => ({
            card: 'generic',
            title: `生成${args.kind === 'shift' ? '跟班记录' : '质量检查报告'}：车次 ${args.run_no}`,
        }),
    }));
}
