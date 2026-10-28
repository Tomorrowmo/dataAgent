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
import { defineTool } from '@deepseek-ai/dsh-tools';
export function applyExtensionTools(ctx, sidecar, timeoutMs) {
    ctx.systemPrompt.section({
        name: 'tool:dataagent-extend',
        order: 124,
        text: '遇到平台不认识的文件格式时，dataset_ingest 会告诉你一个暂存路径；'
            + '你可以自己写一个解析器（parse(path) 返回 DataFrame），用 parser_save 落地，'
            + '之后这个扩展名的文件都会自动走它。'
            + '数据脏（表头在第几行、单位混在数值里、多余空列）时，用 dataset_clean 写一段整理代码——'
            + '它会产出一个新数据集，原始数据不动，便于核对。'
            + '整理完必须看行数：整理是清理噪声，不该丢掉大部分数据。'
            + '工具报告丢失比例过高时，先预览新数据集核对再下结论，不要直接说整理成功。'
            + '如果某个列名反复出现且含义固定（比如 U(V) 就是电压），用 mapping_save 记下来，'
            + '不要每次重新猜。',
    });
    ctx.tools.register(defineTool({
        name: 'parser_save',
        description: 'Write a parser for a file format the platform does not recognise, and register '
            + 'it so every later file with that extension is parsed automatically. '
            + 'The code must define parse(path) returning a pandas DataFrame.',
        parameters: {
            staging_path: {
                type: 'string', required: true,
                description: 'The staging path dataset_ingest reported for the unrecognised file.',
            },
            extension: { type: 'string', required: true, description: 'File extension, e.g. ".ndax".' },
            code: { type: 'string', required: true, description: 'Python source defining parse(path).' },
            name: { type: 'string', description: 'Display name for the resulting dataset.' },
            description: { type: 'string' },
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
                    extension: { type: 'string', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `解析器已落地：${value.extension} 格式现在可以直接导入。`
                        + `\n本次解析结果存为数据集 #${value.datasetId}「${value.name}」`
                        + `（${value.rows} 行 × ${value.columns} 列）。`,
                }],
            presentationMeta: (_args, value) => ({
                datasetId: value.datasetId, extension: value.extension,
                rows: value.rows, columns: value.columns,
            }),
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            // The sidecar re-runs the parser on the staged file before it registers
            // anything: code that does not actually parse this file never becomes an
            // adapter, so a plausible-looking parser cannot poison later uploads.
            const body = {
                staging_path: args.staging_path,
                extension: args.extension,
                code: args.code,
                meta: {},
                description: args.description ?? '',
            };
            if (args.name !== undefined)
                body['name'] = args.name;
            const d = await sidecar.post('/api/datasets/approve-parser', body, exec.signal);
            return {
                datasetId: d.id,
                name: d.name,
                rows: d.rows,
                columns: d.columns,
                extension: args.extension,
            };
        },
        presentCall: args => ({
            card: 'generic', title: `注册 ${args.extension} 解析器`,
        }),
    }));
    ctx.tools.register(defineTool({
        name: 'dataset_clean',
        description: 'Tidy a messy dataset with a short Python cleaner. The result is registered as a '
            + 'new dataset and the messy original is left untouched. '
            + 'The code must define run(df) returning the cleaned DataFrame.',
        parameters: {
            dataset_id: { type: 'number', required: true },
            code: { type: 'string', required: true, description: 'Python source defining run(df).' },
            name: { type: 'string', description: 'Name for the cleaned dataset.' },
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
                    sourceDatasetId: { type: 'number', required: true },
                    sourceRows: { type: 'number', required: true },
                    sourceColumns: { type: 'number', required: true },
                    rowsLost: { type: 'number', required: true },
                    lossRatio: { type: 'number', required: true },
                    suspiciousLoss: { type: 'boolean', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: [
                        `整理完成：数据集 #${value.sourceDatasetId} → 新数据集 #${value.datasetId}`
                            + `「${value.name}」（${value.rows} 行 × ${value.columns} 列）。`,
                        `行数变化：${value.sourceRows} → ${value.rows}`
                            + (value.rowsLost > 0
                                ? `，少了 ${value.rowsLost} 行（${(value.lossRatio * 100).toFixed(1)}%）`
                                : '，没有丢行'),
                        value.suspiciousLoss
                            ? `⚠ 结果可疑（列数 ${value.sourceColumns} → ${value.columns}）。`
                                + '整理是清理噪声，不该丢掉大部分数据，也不该把多列表压成一列。'
                                + '请预览新数据集逐项核对：这些行列是真的该去掉，还是解析写错了把有效数据吃掉了。'
                                + '行数对上不等于内容对了——不要在没看过内容之前就说整理成功。'
                            : '',
                        '原始数据保持不动，可以对照核查。',
                    ].filter(Boolean).join('\n'),
                }],
            presentationMeta: (_args, value) => ({
                datasetId: value.datasetId, sourceDatasetId: value.sourceDatasetId,
                name: value.name, rows: value.rows, columns: value.columns,
                sourceRows: value.sourceRows, lossRatio: value.lossRatio,
                suspiciousLoss: value.suspiciousLoss,
            }),
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            // Row count is read BEFORE the clean so the comparison is against what was
            // actually there. A cleaner that silently drops most of the table returns a
            // perfectly valid dataset and a 200 — the loss is only visible if someone
            // counts, so the tool counts. This is the product's whole premise applied
            // to its own plumbing: a confident wrong answer is the failure mode.
            const before = await sidecar.get(`/api/datasets/${args.dataset_id}`, exec.signal);
            const sourceRows = typeof before.rows === 'number' ? before.rows : 0;
            const sourceCols = typeof before.columns === 'number' ? before.columns : 0;
            const body = {
                dataset_id: args.dataset_id,
                code: args.code,
            };
            if (args.name !== undefined)
                body['name'] = args.name;
            const d = await sidecar.post('/api/datasets/clean-approve', body, exec.signal);
            const rowsLost = Math.max(0, sourceRows - d.rows);
            const lossRatio = sourceRows > 0 ? rowsLost / sourceRows : 0;
            return {
                datasetId: d.id,
                name: d.name,
                rows: d.rows,
                columns: d.columns,
                sourceDatasetId: args.dataset_id,
                sourceRows,
                sourceColumns: sourceCols,
                rowsLost,
                lossRatio: Number(lossRatio.toFixed(4)),
                // 30% is a judgement call, not a law: below it, dropping blank and
                // header rows is ordinary tidying; above it, something needs a human's
                // eyes before the result is trusted.
                //
                // The column check exists because the row check alone can be satisfied
                // by a cleaner that keeps every row and destroys their content — a
                // guard on one dimension gets met on that dimension. Tidying a table
                // does not collapse it to a single column.
                suspiciousLoss: lossRatio > 0.3 || (sourceCols > 1 && d.columns < 2),
            };
        },
        presentCall: args => ({
            card: 'generic', title: `整理数据集 #${args.dataset_id}`,
        }),
    }));
    ctx.tools.register(defineTool({
        name: 'mapping_list',
        description: 'List the saved column-name → role rules that let the platform recognise this '
            + 'lab\'s naming conventions.',
        parameters: {},
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    mappings: {
                        type: 'array',
                        required: true,
                        items: {
                            type: 'object',
                            additionalProperties: false,
                            properties: {
                                id: { type: 'number', required: true },
                                pattern: { type: 'string', required: true },
                                role: { type: 'string', required: true },
                                label: { type: 'string' },
                                matchType: { type: 'string', required: true },
                                note: { type: 'string' },
                            },
                        },
                    },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: value.mappings.length
                        ? value.mappings.map(m => `${m.pattern} → ${m.role}${m.label ? `（${m.label}）` : ''}｜${m.matchType}`).join('\n')
                        : '还没有记录任何列名映射规则。',
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => true,
        async execute(_args, exec) {
            const rows = await sidecar.get('/api/mappings', exec.signal);
            return {
                mappings: rows.map(m => ({
                    id: m.id,
                    pattern: m.pattern,
                    role: m.role,
                    label: m.label ?? '',
                    matchType: m.match_type,
                    note: m.note ?? '',
                })),
            };
        },
        presentCall: () => ({ card: 'generic', title: '列出列名映射', kind: 'read' }),
    }));
    ctx.tools.register(defineTool({
        name: 'mapping_save',
        description: 'Record that a column name means a known role, so later files are understood '
            + 'without asking again. Example: pattern "U(V)" → role "voltage".',
        parameters: {
            pattern: { type: 'string', required: true, description: 'The column name as it appears in files.' },
            role: { type: 'string', required: true, description: 'Machine role key, e.g. "voltage".' },
            label: { type: 'string', description: 'Human-facing label, e.g. "电压 Voltage".' },
            note: { type: 'string', description: 'Why this mapping holds; useful when someone reviews it later.' },
            match_type: {
                type: 'string',
                description: '"normalized" (default), "exact", "contains" or "regex".',
            },
        },
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    id: { type: 'number', required: true },
                    pattern: { type: 'string', required: true },
                    role: { type: 'string', required: true },
                    matchType: { type: 'string', required: true },
                },
            },
            render: (_args, value) => [{
                    type: 'text',
                    text: `已记录映射：${value.pattern} → ${value.role}（匹配方式 ${value.matchType}）。`
                        + `\n以后含这个列名的文件会被自动识别。`,
                }],
        },
        timeoutMs,
        isConcurrencySafe: () => false,
        async execute(args, exec) {
            const m = await sidecar.post('/api/mappings', {
                pattern: args.pattern,
                role: args.role,
                label: args.label ?? '',
                note: args.note ?? '',
                match_type: args.match_type ?? 'normalized',
                is_public: true,
            }, exec.signal);
            return {
                id: m.id,
                pattern: m.pattern,
                role: m.role,
                matchType: m.match_type,
            };
        },
        presentCall: args => ({
            card: 'generic', title: `记录映射 ${args.pattern} → ${args.role}`,
        }),
    }));
}
