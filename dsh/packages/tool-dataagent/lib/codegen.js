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
import { createHash } from 'node:crypto';
import { defineTool } from '@deepseek-ai/dsh-tools';
/** Stable identity of the exact bytes that were tested. */
function codeHash(code) {
    return createHash('sha256').update(code, 'utf8').digest('hex').slice(0, 16);
}
/**
 * Marker for "a human was asked and said no".
 *
 * Distinct from every transport failure so the catch below cannot mistake a
 * real refusal for a missing UI, which would turn a decline into a save.
 */
class SaveDeclined extends Error {
}
/** Recognise the seam's "there is nobody to ask" verdict. */
function isNoProvider(e) {
    return typeof e === 'object' && e !== null
        && e.code === 'NO_PROVIDER';
}
/**
 * Register the codegen tools.
 *
 * `passed` is plugin-closure state holding the hashes of code that cleared the
 * sandbox in this process. It is deliberately not persisted: a restart should
 * force a re-test rather than let a stale approval carry over.
 */
export function applyCodegenTools(ctx, sidecar, timeoutMs) {
    const passed = new Map();
    // Optional dependency, captured through a nested fiber rather than declared in
    // `inject`: a composition without the user-questions service must still get
    // the tools, with the sandbox gate intact and the human gate absent. Reading
    // an undeclared service off `ctx` throws in cordis, so the handle is taken
    // here while the service is live and dropped when it goes away.
    let questions;
    ctx.inject(['userQuestions'], (qctx) => {
        qctx.effect(() => {
            questions = qctx.userQuestions;
            return () => { questions = undefined; };
        }, 'tool-dataagent: user-questions handle');
    });
    ctx.systemPrompt.section({
        name: 'tool:dataagent-codegen',
        order: 122,
        text: '当现有算法都不适用时，你可以自己写一个 Python 算法：文件里要有顶层 META 字典'
            + '（含 name/slug/category/description/params_schema/returns）和 run(df, **params) 函数。'
            + '流程是固定的，不能跳步：先用 algo_test 在沙箱里针对真实数据集测试，'
            + '通过后才能用 algo_save 入库。algo_save 会拒绝没测过、或测完又改动过的代码。'
            + '沙箱禁止 import os、eval、网络访问这类操作，写代码时不要用。'
            + '优先使用 algo_list 里已有的经典算法——自己写的代码没有那些算法的验证历史。',
    });
    ctx.tools.register(defineTool({
        name: 'algo_test',
        description: 'Validate and run a Python algorithm in the sandbox against a real dataset. '
            + 'Required before algo_save. The code needs a top-level META dict and a run(df, **params) function.',
        parameters: {
            code: { type: 'string', required: true, description: 'Complete Python source.' },
            dataset_id: { type: 'number', description: 'Dataset to test against. Strongly recommended.' },
            params: {
                type: 'object', additionalProperties: true, properties: {},
                description: 'Parameters to call run() with.',
            },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    codeHash: { type: 'string', required: true },
                    accepted: { type: 'boolean', required: true },
                    validationErrors: { type: 'array', required: true, items: { type: 'string' } },
                    imports: { type: 'array', required: true, items: { type: 'string' } },
                    hasRun: { type: 'boolean', required: true },
                    hasMeta: { type: 'boolean', required: true },
                    executionStatus: { type: 'string', required: true },
                    executionError: { type: 'string' },
                    durationMs: { type: 'number' },
                    detectedSlug: { type: 'string' },
                    detectedName: { type: 'string' },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.accepted
                        ? `沙箱测试通过（${value.durationMs ?? '?'} ms）。`
                            + `识别到算法 ${value.detectedSlug ?? '(未声明 slug)'}「${value.detectedName ?? ''}」。`
                            + `\n代码指纹 ${value.codeHash} —— algo_save 时必须用同一份代码，改动即失效。`
                        : ['沙箱测试未通过，不能入库。',
                            value.validationErrors.length
                                ? `静态校验：${value.validationErrors.join('；')}` : '',
                            !value.hasRun ? '缺少 run(df, **params) 函数。' : '',
                            !value.hasMeta ? '缺少顶层 META 字典。' : '',
                            value.executionError ? `执行错误：${value.executionError}` : '',
                        ].filter(Boolean).join('\n'),
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(args, exec) {
            const body = {
                code: args.code,
                params: (args.params ?? {}),
            };
            if (args.dataset_id !== undefined)
                body['dataset_id'] = args.dataset_id;
            const r = await sidecar.post('/api/algorithms/test', body, exec.signal);
            const hash = codeHash(args.code);
            const status = r.execution?.status ?? 'unknown';
            const accepted = r.validation.ok && r.validation.has_run && r.validation.has_meta
                && status === 'ok';
            if (accepted)
                passed.set(hash, { code: args.code, meta: r.meta ?? {} });
            else
                passed.delete(hash);
            const slug = typeof r.meta?.['slug'] === 'string' ? r.meta['slug'] : undefined;
            const nm = typeof r.meta?.['name'] === 'string' ? r.meta['name'] : undefined;
            return {
                codeHash: hash,
                accepted,
                validationErrors: [...r.validation.errors ?? []],
                imports: [...r.validation.imports ?? []],
                hasRun: r.validation.has_run,
                hasMeta: r.validation.has_meta,
                executionStatus: status,
                ...r.execution?.error ? { executionError: r.execution.error } : {},
                ...typeof r.execution?.duration_ms === 'number'
                    ? { durationMs: r.execution.duration_ms } : {},
                ...slug ? { detectedSlug: slug } : {},
                ...nm ? { detectedName: nm } : {},
            };
        },
        presentCall: () => ({ card: 'generic', title: '沙箱测试算法代码' }),
    }));
    ctx.tools.register(defineTool({
        name: 'algo_save',
        description: 'Persist a sandbox-tested algorithm so it becomes permanently callable. '
            + 'Only code that passed algo_test unchanged can be saved, and the human is asked to approve.',
        parameters: {
            code: { type: 'string', required: true, description: 'The exact code that passed algo_test.' },
            slug: { type: 'string', description: 'Overrides META slug.' },
            name: { type: 'string', description: 'Overrides META name.' },
            category: { type: 'string', description: 'Overrides META category.' },
            description: { type: 'string', description: 'Overrides META description.' },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    id: { type: 'number', required: true },
                    slug: { type: 'string', required: true },
                    name: { type: 'string', required: true },
                    category: { type: 'string', required: true },
                    verified: { type: 'boolean', required: true },
                    humanApproved: { type: 'boolean', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `算法已入库：${value.slug}「${value.name}」（分类 ${value.category}，#${value.id}）。`
                        + `\n沙箱验证：${value.verified ? '通过' : '未标记'}`
                        + `｜人工批准：${value.humanApproved ? '是' : '无 UI，未经人工确认'}`
                        + `\n现在可以用 algo_run 调用它。`,
                }],
            presentationMeta: (_args, value) => ({
                slug: value.slug, name: value.name, category: value.category,
                verified: value.verified, humanApproved: value.humanApproved,
            }),
        },
        timeoutMs,
        // Writes to the algorithm registry.
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            const hash = codeHash(args.code);
            const record = passed.get(hash);
            if (record === undefined) {
                // The gate. Naming the hash makes the failure diagnosable: the model can
                // see that the bytes it is trying to save are not the bytes it tested.
                throw new Error(`这段代码（指纹 ${hash}）没有通过沙箱测试，不能入库。`
                    + '请先用 algo_test 测试这一份完全相同的代码；测试之后再修改代码会使指纹失效，需要重测。');
            }
            // Human approval when a UI is mounted. Headless runs keep the sandbox gate
            // and record the absence of a human decision rather than implying one.
            let humanApproved = false;
            const APPROVE = '批准入库';
            if (questions !== undefined) {
                const metaSlug = typeof record.meta['slug'] === 'string' ? record.meta['slug'] : '';
                const slug = args.slug ?? metaSlug;
                try {
                    const answer = await questions.ask({
                        questions: [{
                                id: 'algo-save-approval',
                                header: '算法入库',
                                question: `是否把算法「${args.name ?? record.meta['name'] ?? slug}」加入你的算法库？`,
                                detail: `slug: ${slug}\n代码指纹: ${hash}\n沙箱测试: 已通过\n\n`
                                    + '入库后它会成为一个可以被反复调用的永久工具。',
                                options: [
                                    { label: APPROVE, description: '加入算法库，以后可直接调用' },
                                    { label: '不入库', description: '这次先不保存' },
                                ],
                            }],
                    });
                    const picked = answer.answers.find((a) => a.id === 'algo-save-approval');
                    humanApproved = picked?.selected.includes(APPROVE) === true;
                    if (!humanApproved) {
                        throw new SaveDeclined('用户没有批准入库。代码在本次会话里仍可用，但没有成为永久算法。');
                    }
                }
                catch (e) {
                    // "没有人可问" 和 "问了，人说不" 是两件必须分开的事。前者是部署形态
                    // （headless 没有 UI），后者是一次真实的拒绝——把它们合并会让无人值守
                    // 的运行看起来像被批准过，或者让用户的否决被当成环境故障忽略掉。
                    if (e instanceof SaveDeclined)
                        throw new Error(e.message);
                    if (!isNoProvider(e))
                        throw e;
                    humanApproved = false;
                }
            }
            const body = {
                code: args.code,
                source: 'ai',
                test_report: { all_tests_passed: true, code_hash: hash, human_approved: humanApproved },
            };
            if (args.slug !== undefined)
                body['slug'] = args.slug;
            if (args.name !== undefined)
                body['name'] = args.name;
            if (args.category !== undefined)
                body['category'] = args.category;
            if (args.description !== undefined)
                body['description'] = args.description;
            const saved = await sidecar.post('/api/algorithms/save', body, exec.signal);
            return {
                id: saved.id,
                slug: saved.slug,
                name: saved.name,
                category: saved.category,
                verified: saved.verified,
                humanApproved,
            };
        },
        presentCall: args => ({
            card: 'generic',
            title: `入库算法 ${args.slug ?? '(取自 META)'}`,
        }),
    }));
}
