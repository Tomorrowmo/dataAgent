// Tiny typed fetch wrapper. All requests go through Next.js' /api rewrite
// to the FastAPI backend; in production both run under the same origin.

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

const TOKEN_KEY = 'numetrix.token';
// In-memory fallback when localStorage is unavailable / throws (e.g. Safari
// private mode, or storage blocked) — keeps auth working without crashing.
let memToken: string | null = null;

export function setToken(token: string | null) {
  memToken = token;
  if (typeof window === 'undefined') return;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* localStorage unavailable — memToken covers this session */ }
}

export function getToken(): string | null {
  if (memToken) return memToken;
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

// OIDC login/logout are browser redirects (not fetch) — full-page navigate to
// these. They go through the same /api rewrite to the FastAPI backend.
export const OIDC_LOGIN_URL = '/api/auth/oidc/login';
export const OIDC_LOGOUT_URL = '/api/auth/oidc/logout';

class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(method: string, path: string, body?: Json | FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const r = await fetch(`/api${path}`, { method, headers, body: payload });
  const text = await r.text();
  const parsed = text ? safeJSON(text) : null;
  if (!r.ok) {
    const detail = (parsed && typeof parsed === 'object' && 'detail' in (parsed as object))
      ? (parsed as { detail: unknown }).detail
      : text;
    throw new ApiError(typeof detail === 'string' ? detail : `HTTP ${r.status}`, r.status, parsed);
  }
  return parsed as T;
}

function safeJSON(s: string): unknown {
  try { return JSON.parse(s); } catch { return s; }
}

export const api = {
  signup: (email: string, password: string, name: string) =>
    request<{ access_token: string; user_id: number; email: string; name: string }>(
      'POST', '/auth/signup', { email, password, name }),
  login: (email: string, password: string) =>
    request<{ access_token: string; user_id: number; email: string; name: string }>(
      'POST', '/auth/login', { email, password }),
  me: () => request<{
    id: number; email: string; name: string; is_admin: boolean;
    has_llm_key: boolean; llm_base_url: string; llm_model: string;
  }>('GET', '/auth/me'),
  saveLLMConfig: (api_key: string, base_url: string, model: string) =>
    request<{ ok: boolean; has_llm_key: boolean; llm_base_url: string; llm_model: string }>(
      'PUT', '/auth/llm-key', { api_key, base_url, model }),
  /** Version, changelog and linked documents for the「关于」panel. Public + warmup-open. */
  about: () => request<AboutInfo>('GET', '/about'),
  /** Whether login is delegated to the 统一认证中心 (OIDC). Drives the SSO button. */
  oidcConfig: () => request<{ enabled: boolean }>('GET', '/auth/oidc/config'),

  listDatasets: () => request<Dataset[]>('GET', '/datasets'),
  getDataset: (id: number) => request<Dataset>('GET', `/datasets/${id}`),
  uploadDataset: (file: File, name?: string, description?: string) => {
    const fd = new FormData();
    fd.append('file', file);
    if (name) fd.append('name', name);
    if (description) fd.append('description', description);
    return request<UploadResp>('POST', '/datasets', fd);
  },
  // Attach an image to the NEXT chat message (a chart/plot/diagram to analyze).
  // Returns a ref passed back to streamChat as image_ref.
  uploadChatImage: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<{ ref: string; name: string; ext: string }>('POST', '/chat/upload-image', fd);
  },
  // Deleting a dataset takes its whole derived subtree with it; pass dryRun to
  // find out how much that is before actually destroying anything.
  deleteDataset: (id: number, dryRun = false) =>
    request<{
      ok: boolean; count: number; descendants: number; kept_hit: number;
      freed_bytes: number; deleted: { id: number; name: string; kind: string; kept: boolean }[];
    }>('DELETE', `/datasets/${id}${dryRun ? '?dry_run=true' : ''}`),
  /** Keep a derived/intermediate dataset — promote it to a first-class source dataset. */
  promoteDataset: (id: number) => request<Dataset>('POST', `/datasets/${id}/promote`),
  /** Pin/unpin a derived dataset in place so auto-GC won't reclaim it. */
  keepDataset: (id: number, kept = true) => request<Dataset>('POST', `/datasets/${id}/keep`, { kept }),
  /** Instant, FREE deterministic first-read of a dataset (no LLM): what it is,
   *  grounded facts, and suggested next actions. Shown right after import. */
  profileDataset: (id: number) => request<DatasetProfile>('GET', `/datasets/${id}/profile`),
  /** Plain-language AI explanation of a dataset / analysis result. */
  explainDataset: (id: number) => request<{ explanation: string }>('POST', `/datasets/${id}/explain`),
  /** Reclaim un-kept intermediate datasets. dry_run previews the count. */
  gcDatasets: (dry_run = false) =>
    request<{ deleted: { id: number; name: string }[]; count: number; freed_bytes: number; dry_run: boolean }>(
      'POST', `/datasets/gc?dry_run=${dry_run ? 'true' : 'false'}`),
  /** Run an algorithm and save its table output as a derived dataset (with lineage). */
  runToDataset: (slug: string, params: Record<string, unknown>, dataset_id: number) =>
    request<{ id: number; name: string; rows: number; columns: number }>(
      'POST', '/algorithms/run-to-dataset', { slug, params, dataset_id }),

  /** @deprecated — replaced by streamParserGenerate. */
  generateParser: (staging_path: string, extension: string) =>
    request<ParserProposal>('POST', '/datasets/generate-parser', { staging_path, extension }),
  approveParser: (body: {
    staging_path: string;
    extension: string;
    code: string;
    meta?: Record<string, unknown>;
    name?: string;
    description?: string;
  }) => request<Dataset>('POST', '/datasets/approve-parser', body),
  listAdapters: () => request<FormatAdapter[]>('GET', '/datasets/adapters'),
  deleteAdapter: (id: number) => request<{ ok: boolean }>('DELETE', `/datasets/adapters/${id}`),

  listAlgorithms: (opts?: { category?: string; source?: string }) => {
    const qs = new URLSearchParams();
    if (opts?.category) qs.set('category', opts.category);
    if (opts?.source) qs.set('source', opts.source);
    const q = qs.toString();
    return request<Algorithm[]>('GET', `/algorithms${q ? `?${q}` : ''}`);
  },
  testAlgorithm: (code: string, params: Record<string, unknown>, dataset_id?: number) =>
    request<TestResult>('POST', '/algorithms/test', { code, params, dataset_id }),
  saveAlgorithm: (body: {
    code: string;
    name?: string;
    slug?: string;
    category?: string;
    description?: string;
    source?: 'user' | 'ai';
    params_schema?: Record<string, unknown>;
    test_report?: Record<string, unknown>;
    is_public?: boolean;
  }) => request<Algorithm>('POST', '/algorithms/save', body),
  generateAlgorithm: (description: string, dataset_id?: number) =>
    request<GenerationResult>('POST', '/algorithms/generate', { description, dataset_id }),
  /** Auto-correct a pasted snippet / uploaded .py into a conformant tool
   *  (top-level META + run(df, **params), sandbox-safe imports), then sandbox-test it. */
  autofixAlgorithm: (code: string, dataset_id?: number) =>
    request<GenerationResult>('POST', '/algorithms/autofix', { code, dataset_id }),
  runAlgorithm: (slug: string, params: Record<string, unknown>, dataset_id?: number) =>
    request<RunResult>('POST', '/algorithms/run', { slug, params, dataset_id }),
  /** Let AI rewrite an existing tool from a plain-language instruction (add/adjust
   *  a parameter or capability). Returns a fresh generation bundle; the draft's
   *  code + params are updated server-side when the rewrite passes its tests. */
  refineTool: (slug: string, instruction: string, dataset_id?: number) =>
    request<GenerationResult>('POST', '/algorithms/refine', { slug, instruction, dataset_id }),
  /** Keep (verify) or discard (delete) an AI-generated tool the agent auto-registered.
   *  On keep, optional edits make it a general/reusable tool (name, description,
   *  curated params schema). */
  confirmGeneratedTool: (slug: string, keep: boolean, edits?: { name?: string; description?: string; category?: string; params_schema?: Record<string, ParamSpec> }) =>
    request<{ ok: boolean; kept: boolean; slug: string; name?: string }>(
      'POST', '/algorithms/confirm-generated', { slug, keep, ...(edits || {}) }),

  cleanApprove: (dataset_id: number, code: string, name?: string) =>
    request<Dataset>('POST', '/datasets/clean-approve', { dataset_id, code, name }),
  /** Ask the LLM to suggest sensible params for an algorithm + dataset (+ optional NL intent). Fills the form; user still runs. */
  suggestParams: (slug: string, dataset_id?: number, intent?: string) =>
    request<{ params: Record<string, unknown>; explanations: Record<string, string>; note: string }>(
      'POST', '/algorithms/suggest-params', { slug, dataset_id, intent }),
  /** Explain a tool-execution error in plain Chinese (why + how to fix). */
  explainError: (slug: string, error: string, params: Record<string, unknown>, dataset_id?: number) =>
    request<{ explanation: string }>('POST', '/algorithms/explain-error', { slug, error, params, dataset_id }),
  /** Explain why an uploaded-but-unsaved algorithm failed its test (code + error,
   *  no slug needed — used by the upload view's "用人话解释" button). */
  explainTestError: (code: string, error: string, dataset_id?: number) =>
    request<{ explanation: string; hints?: { cause: string; fatal: boolean }[] }>(
      'POST', '/algorithms/explain-test-error', { code, error, dataset_id }),
  /** Interpret an algorithm result in plain Chinese. */
  explainResult: (slug: string, params: Record<string, unknown>, summary: Record<string, unknown>, dataset_id?: number) =>
    request<{ explanation: string }>('POST', '/algorithms/explain-result', { slug, params, summary, dataset_id }),
  /** Save a subset of a dataset as a new derived dataset: either explicit
   *  selected row indices, or server-side filters + sort + limit applied to the
   *  FULL dataset. */
  saveSubset: (id: number, body: {
    name?: string;
    row_indices?: number[];
    filters?: { column: string; op: string; value: unknown }[];
    sort?: { column: string; desc: boolean };
    limit?: number;
  }) => request<Dataset>('POST', `/datasets/${id}/subset`, body),
  /** Fetch the first N rows of a dataset on demand (more than the stored 10-row head). */
  datasetPreview: (id: number, limit = 50) =>
    request<{ columns: string[]; rows: Record<string, unknown>[]; total: number; shown: number }>(
      'GET', `/datasets/${id}/preview?limit=${limit}`),
  /** Preview a result parquet/CSV by path (a single-run output not yet saved as a dataset). */
  previewResultFile: (path: string, limit = 500) =>
    request<{ columns: string[]; rows: Record<string, unknown>[]; total: number; shown: number }>(
      'GET', `/datasets/preview-file?path=${encodeURIComponent(path)}&limit=${limit}`),
  /** 3D point-cloud geometry (X/Y/Z + a field's values) for mesh/CGNS datasets. */
  datasetPoints3d: (id: number, color?: string, maxPoints = 80000) =>
    request<Points3D>('GET', `/datasets/${id}/points3d?max_points=${maxPoints}${color ? `&color=${encodeURIComponent(color)}` : ''}`),
  /** One field's values (same downsample) for re-coloring the 3D view. */
  datasetColumn: (id: number, name: string, maxPoints = 80000) =>
    request<{ name: string; values: (number | null)[]; cmin: number; cmax: number }>(
      'GET', `/datasets/${id}/column?name=${encodeURIComponent(name)}&max_points=${maxPoints}`),

  createTemplate: (name: string, steps: TemplateStep[], description = '', graph?: FlowGraph) =>
    request<FlowTemplate>('POST', '/templates', { name, steps, description, graph: graph ?? {} }),
  listTemplates: () => request<FlowTemplate[]>('GET', '/templates'),
  deleteTemplate: (id: number) => request<{ ok: boolean }>('DELETE', `/templates/${id}`),
  updateTemplate: (id: number, body: { name?: string; description?: string; steps?: TemplateStep[]; graph?: FlowGraph }) =>
    request<FlowTemplate>('PUT', `/templates/${id}`, body),
  runTemplate: (id: number, dataset_id: number, save_result = true, param_overrides?: Record<string, Record<string, unknown>>) =>
    request<TemplateRunResult>('POST', `/templates/${id}/run`, { dataset_id, save_result, param_overrides: param_overrides ?? {} }),

  listConversations: () => request<Conversation[]>('GET', '/chat/conversations'),
  createConversation: (title?: string, dataset_id?: number) =>
    request<Conversation>('POST', '/chat/conversations', { title, dataset_id }),
  renameConversation: (id: number, title: string) =>
    request<Conversation>('PATCH', `/chat/conversations/${id}`, { title }),
  deleteConversation: (id: number) =>
    request<{ ok: boolean }>('DELETE', `/chat/conversations/${id}`),
  listMessages: (id: number) => request<ChatMessage[]>('GET', `/chat/conversations/${id}/messages`),
  /** Cross-turn pipeline head per dataset (for the chat continuation chip). */
  getPipeline: (id: number) =>
    request<{ pipeline_state: Record<string, { head_id: number; head_name: string; steps: number }> }>(
      'GET', `/chat/conversations/${id}/pipeline`),
  /** Clear cross-turn pipeline state → next message starts from original data. */
  resetPipeline: (id: number) => request<{ ok: boolean }>('POST', `/chat/conversations/${id}/reset-pipeline`),

  /** Drop an in-the-moment feedback note with the context it happened in. */
  submitFeedback: (body: {
    text: string;
    kind: FeedbackKind;
    view?: string;
    conversation_id?: number | null;
    dataset_id?: number | null;
    run_id?: number | null;
    context?: Record<string, unknown>;
    screenshot_b64?: string | null;
  }) => request<Feedback>('POST', '/feedback', {
    text: body.text,
    kind: body.kind,
    view: body.view ?? '',
    conversation_id: body.conversation_id ?? null,
    dataset_id: body.dataset_id ?? null,
    run_id: body.run_id ?? null,
    context: body.context ?? {},
    screenshot_b64: body.screenshot_b64 ?? null,
  }),
  listFeedback: () => request<Feedback[]>('GET', '/feedback'),
  /** Triage a note: new → triaged → done, or re-bucket its kind. */
  updateFeedback: (id: number, body: { status?: string; kind?: FeedbackKind }) =>
    request<Feedback>('PATCH', `/feedback/${id}`, body),

  /** Promote a correction into a reusable column-meaning rule (expert knowledge
   *  sedimentation). Pass feedback_id to auto-close that note. */
  createMapping: (body: { pattern: string; role: string; label?: string; note?: string; match_type?: string; is_public?: boolean; feedback_id?: number }) =>
    request<MappingRule>('POST', '/mappings', body),
  listMappings: () => request<MappingRule[]>('GET', '/mappings'),
  deleteMapping: (id: number) => request<{ ok: boolean }>('DELETE', `/mappings/${id}`),
  /** Consult: what do the visible rules say about these column names. */
  applyMappings: (columns: string[]) =>
    request<{ matches: MappingMatch[] }>('POST', '/mappings/apply', { columns }),

  // ── 风洞试验过程质量检查 ────────────────────────────────────────────
  wtHealth: () => request<{ ok: boolean; llm_configured: boolean; model: string; features: number; seed_rules: number }>('GET', '/wt/health'),

  wtCreateBatch: (files: File[], name?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));
    if (name) fd.append('name', name);
    return request<WtBatch>('POST', '/wt/batches', fd);
  },
  wtListBatches: () => request<WtBatch[]>('GET', '/wt/batches'),
  wtGetBatch: (id: number) => request<{ batch: WtBatch; result: WtBatchResult | null }>('GET', `/wt/batches/${id}`),
  wtDeleteBatch: (id: number) => request<{ ok: boolean }>('DELETE', `/wt/batches/${id}`),
  wtCheck: (id: number, body: { rule_ids?: string[]; tail_contracted?: boolean; balance_ranges?: Record<string, number>; trend_window?: number }) =>
    request<WtBatchResult>('POST', `/wt/batches/${id}/check`, {
      rule_ids: body.rule_ids ?? [], tail_contracted: body.tail_contracted ?? false,
      balance_ranges: body.balance_ranges ?? {}, trend_window: body.trend_window ?? 5,
    }),
  wtFrame: (id: number, run_no: string, table = 'ca') =>
    request<{ run_no: string; table: string; columns: string[]; rows: Record<string, number>[] }>(
      'GET', `/wt/batches/${id}/frame?run_no=${encodeURIComponent(run_no)}&table=${table}`),

  wtCurve: (id: number, run_no: string, x: string, ys: string[]) =>
    request<WtCurve>('POST', `/wt/batches/${id}/curve`, { run_no, x, ys }),
  wtCurveConclusion: (id: number, run_no: string, statistics: WtCurveStat[], meta: Record<string, unknown>) =>
    request<{ ok: boolean; text?: string; error?: string }>('POST', `/wt/batches/${id}/curve/conclusion`, { run_no, statistics, meta }),

  wtReportSections: () => request<{ sections: { key: string; name: string; desc: string }[] }>('GET', '/wt/report-sections'),
  wtMakeReport: (id: number, body: { run_no?: string; kind?: string; sections?: string[]; title?: string; author?: string; narratives?: Record<string, string>; include_curve?: boolean }) =>
    request<{ id: number; run_no: string; kind: string; content: string; filename: string }>('POST', `/wt/batches/${id}/report`, body),
  wtSaveReport: (rid: number, edited: string) => request<{ ok: boolean }>('PUT', `/wt/reports/${rid}`, { edited }),
  wtListReports: () => request<WtReportRow[]>('GET', '/wt/reports'),
  /** Download an exported report.
   *
   *  A plain `<a href>` cannot carry the Bearer token, so the anchor form of
   *  this returned 401 for every real user while looking perfectly fine in
   *  code review. Fetch it with auth, then hand the browser a blob URL. */
  wtDownloadReport: async (rid: number, fmt = 'txt') => {
    const token = getToken();
    const r = await fetch(`/api/wt/reports/${rid}/export?fmt=${fmt}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!r.ok) throw new Error(`导出失败 HTTP ${r.status}`);
    const cd = r.headers.get('content-disposition') ?? '';
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const plain = /filename="?([^";]+)"?/i.exec(cd);
    const name = star ? decodeURIComponent(star[1]) : (plain?.[1] ?? `report.${fmt}`);
    return { blob: await r.blob(), filename: name };
  },

  wtFeatures: () => request<{ features: WtFeature[]; catalog_markdown: string; format_doc: string; extractor_contract: string }>('GET', '/wt/features'),
  wtRules: () => request<{ rules: WtRule[] }>('GET', '/wt/rules'),
  wtCreateRule: (rule: WtRuleInput) => request<WtRule>('POST', '/wt/rules', rule),
  wtUpdateRule: (rowId: number, rule: WtRuleInput) => request<WtRule>('PUT', `/wt/rules/${rowId}`, rule),
  wtDeleteRule: (rowId: number) => request<{ ok: boolean }>('DELETE', `/wt/rules/${rowId}`),
  wtRestoreDefaultRules: () => request<{ ok: boolean }>('POST', '/wt/rules/restore-defaults', {}),
  wtDraftRule: (requestText: string) => request<WtDraftResp>('POST', '/wt/rules/draft', { request: requestText }),
  wtTriage: (requestText: string) => request<{ ok: boolean; matched?: boolean; feature?: string | null; confidence?: number; why?: string; new_feature_brief?: string; error?: string }>('POST', '/wt/rules/triage', { request: requestText }),
  wtPreviewRule: (rule: WtRuleInput, batch_id: number) =>
    request<{ ok: boolean; rule: WtRule; preview: { run_no: string; findings: WtFinding[] }[] }>('POST', '/wt/rules/preview', { rule, batch_id }),

  wtGenExtractor: (requestText: string, batch_id?: number, run_no?: string) =>
    request<WtExtractorGen>('POST', '/wt/extractors/generate', { request: requestText, batch_id: batch_id ?? null, run_no: run_no ?? '' }),
  wtSaveExtractor: (body: { code: string; name: string; slug: string; description?: string; test_report?: unknown }) =>
    request<{ ok: boolean; feature_key: string; updated: boolean }>('POST', '/wt/extractors', body),
  wtListExtractors: () => request<{ extractors: WtExtractor[] }>('GET', '/wt/extractors'),

  wtBalances: () => request<{ units: string[]; balances: WtBalance[] }>('GET', '/wt/balances'),
  wtAddBalance: (body: { name: string; ranges: Record<string, number>; note?: string }) =>
    request<WtBalance>('POST', '/wt/balances', body),
  wtDeleteBalance: (id: number) => request<{ ok: boolean }>('DELETE', `/wt/balances/${id}`),
  wtImportBalances: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<{ ok: boolean; added: number; updated: number }>('POST', '/wt/balances/import', fd);
  },

  // ── 多车次对比（20260225《车次及马赫数绘图》需求）────────────────────
  wtRuns: (id: number) => request<WtRunList>('GET', `/wt/batches/${id}/runs`),
  wtMatrix: (id: number) => request<WtMatrix>('GET', `/wt/batches/${id}/matrix`),
  /** Plan vs actual — only the 车次表 can show a run that is missing. */
  wtCoverage: (id: number) => request<WtCoverage>('GET', `/wt/batches/${id}/coverage`),
  wtCompareRuns: (id: number, body: {
    run_nos: string[]; x: string; ys: string[];
    baseline?: string | null; mode?: string; sort_by?: string[];
  }) => request<WtCompare>('POST', `/wt/batches/${id}/compare/runs`, body),
  wtCompareState: (id: number, body: {
    run_nos: string[]; state_var: string; ys: string[]; alphas: number[];
    baseline?: string | null; mode?: string;
    run_nos_2?: string[]; alphas_2?: number[];
    group_label?: string; group_label_2?: string;
  }) => request<WtCompare>('POST', `/wt/batches/${id}/compare/state`, body),
  wtEffectiveness: (id: number, body: { surface: string; alphas: number[]; coeffs?: string[] }) =>
    request<WtEffectiveness>('POST', `/wt/batches/${id}/compare/effectiveness`, body),
  wtResponse: (id: number, body: { surface: string; alphas: number[]; coeffs?: string[] }) =>
    request<WtResponse>('POST', `/wt/batches/${id}/compare/response`, body),
  wtSymmetry: (id: number, body: { surface: string; alphas: number[]; coeffs?: string[] }) =>
    request<WtSymmetry>('POST', `/wt/batches/${id}/compare/symmetry`, body),
  wtRepeatability: (id: number) => request<WtRepeatability>('GET', `/wt/batches/${id}/repeatability`),
  /** Download the plotted numbers as CSV (BOM'd for Excel on Windows). */
  wtCompareExport: async (id: number, body: Record<string, unknown>) => {
    const token = getToken();
    const r = await fetch(`/api/wt/batches/${id}/compare/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`导出失败 HTTP ${r.status}`);
    const cd = r.headers.get('content-disposition') ?? '';
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    return { blob: await r.blob(), filename: star ? decodeURIComponent(star[1]) : 'compare.csv' };
  },

  wtAsk: (batch_id: number, run_no: string, question: string) =>
    request<{ ok: boolean; text?: string; error?: string }>('POST', '/wt/ask', { batch_id, run_no, question }),
  wtSummarize: (batch_id: number, run_no: string) =>
    request<{ ok: boolean; text?: string; error?: string }>('POST', '/wt/summarize', { batch_id, run_no }),
};

// ── 风洞领域类型 ────────────────────────────────────────────────────────
export type WtLevel = 'ok' | 'notice' | 'warning' | 'critical';

export interface WtBatch {
  id: number; name: string; status: string; error: string;
  runs: { run_no: string; files: Record<string, string>; meta: Record<string, unknown> }[];
  config: Record<string, unknown>;
  created_at: string; checked_at?: string;
}

export interface WtFinding {
  rule_id: string; rule_name: string; feature: string; feature_name: string;
  level: WtLevel; level_label: string; value: number | null; unit: string;
  verdict: string; action: string; cause: string; impact: string;
  detail: string; method: string; refs: string[];
  extras: Record<string, unknown>;
  status: 'evaluated' | 'unavailable' | 'skipped';
}

export interface WtFeatureValue {
  key: string; name: string; unit: string; value: number | null;
  status: string; detail: string; extras: Record<string, unknown>; method: string;
}

export interface WtRunResult {
  run_no: string;
  meta: Record<string, unknown>;
  grade: string; level: WtLevel;
  compared_with: string | null; chain_broken: boolean;
  counts: Record<string, number>;
  features: Record<string, WtFeatureValue>;
  findings: WtFinding[];
}

export interface WtTrend {
  feature: string; name: string; unit: string;
  runs: string[]; values: number[];
  monotone_run: number; trend: string; flagged: boolean;
  reference: string; note: string;
}

export interface WtBatchResult {
  runs: WtRunResult[];
  config: Record<string, unknown>;
  trends: WtTrend[];
  notes: string[];
  summary: {
    run_count: number;
    totals: Record<string, number>;
    failed_runs: string[]; warned_runs: string[]; grade: string;
  };
}

export interface WtCurveStat {
  key: string; label: string; n: number;
  slope_per_deg: number; r2: number;
  min: { x: number; y: number }; max: { x: number; y: number };
  range: number; max_nonlinearity: { x: number; deviation: number };
  monotone: boolean;
}

export interface WtCurve {
  ok: boolean; run_no: string; x_key: string; x_label: string;
  series: { key: string; label: string; x: number[]; y: number[] }[];
  available_columns: { key: string; label: string }[];
  flow: Record<string, number>; mach: number | null; model: string;
  statistics: WtCurveStat[];
}

export interface WtBand {
  level: WtLevel; lo: number | null; hi: number | null;
  verdict: string; action: string; cause: string; impact: string;
}

export interface WtRule {
  id?: number; rule_id: string; name: string; feature: string;
  object: string; note: string; refs: string[]; enabled: boolean;
  source: string; applies_when_mach: string; bands: WtBand[];
  builtin_id?: string; changelog?: unknown[]; updated_at?: string;
}

export type WtRuleInput = Omit<WtRule, 'id' | 'builtin_id' | 'changelog' | 'updated_at'>;

export interface WtFeature {
  key: string; name: string; unit: string; requires: string[];
  needs_prev_run: boolean; description: string; method: string;
}

export interface WtDraftResp {
  ok: boolean; rule?: WtRule; problems?: string[] | null;
  reasoning?: string; threshold_source?: string;
  error?: string; needs_new_feature?: string; next_action?: string;
}

export interface WtExtractorGen {
  ok: boolean; code?: string; meta?: { name?: string; slug?: string; description?: string };
  feature_key?: string; attempts?: number; error?: string;
  tests?: unknown[]; attempt_log?: unknown[];
}

export interface WtExtractor {
  id: number; slug: string; name: string; description: string;
  feature_key: string; verified: boolean; version: number; code: string;
}

export interface WtBalance {
  id: number; name: string; ranges: Record<string, number>; note: string;
}

export interface WtReportRow {
  id: number; batch_id: number | null; run_no: string; kind: string;
  title: string; edited: boolean; updated_at: string;
}

export type ChangelogEntry = {
  version: string;
  date: string;
  title: string;
  summary?: string;
  /** bucket name (新增 / 优化 / 修复 …) → list of change descriptions */
  changes: Record<string, string[]>;
};
export type AboutDoc = { key: string; title: string; subtitle: string; view: string; download: string; filename: string };
export type AboutInfo = {
  version: string;
  product: string;
  product_note: string;
  changelog: ChangelogEntry[];
  documents: AboutDoc[];
};

export type MappingRule = {
  id: number;
  pattern: string;
  match_type: string;
  role: string;
  label: string;
  note: string;
  source: string;
  feedback_id: number | null;
  is_public: boolean;
  hit_count: number;
  created_at: string;
};
export type MappingMatch = { column: string; role: string; label: string; rule_id: number; source: string; match_type: string };

export type FeedbackKind = 'cannot' | 'wrong' | 'distrust' | 'idea';
export type Feedback = {
  id: number;
  kind: FeedbackKind;
  text: string;
  view: string;
  conversation_id: number | null;
  dataset_id: number | null;
  run_id: number | null;
  context: Record<string, unknown>;
  status: string;
  created_at: string;
  has_screenshot: boolean;
};

/** Authenticated fetch of a feedback screenshot → object URL for an <img src>.
 *  (An <img> tag can't send the bearer header, so we fetch the blob ourselves.)
 *  Caller should URL.revokeObjectURL when done. */
export async function fetchFeedbackScreenshot(id: number): Promise<string> {
  const token = getToken();
  const r = await fetch(`/api/feedback/${id}/screenshot`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!r.ok) throw new Error(`screenshot HTTP ${r.status}`);
  const blob = await r.blob();
  return URL.createObjectURL(blob);
}

export type Dataset = {
  id: number;
  name: string;
  description: string;
  filename: string;
  file_format: string;
  rows: number;
  columns: number;
  size_bytes: number;
  schema: {
    columns?: { name: string; dtype: string; n_unique?: number; n_missing?: number }[];
    head?: Record<string, unknown>[];
  };
  kind?: 'source' | 'derived';
  derived_from?: number | null;
  lineage?: { from?: number; from_name?: string; op?: { slug?: string; label?: string; params?: Record<string, unknown> } };
  kept?: boolean;
};

/** A suggested next action; `slug` maps to a recipe (→ chat) or in-view action. */
export type ProfileSuggestion = { slug: string; why: string };

/** Deterministic first-read of a dataset (see /datasets/{id}/profile). */
export type DatasetProfile = {
  kind: 'mesh' | 'timeseries' | 'wide_numeric' | 'grouped' | 'tabular';
  headline: string;
  facts: string[];
  roles: Partial<Record<'numeric' | 'datetime' | 'categorical' | 'text' | 'coord' | 'bool', string[]>>;
  missing: { name: string; pct: number }[];
  suggestions: ProfileSuggestion[];
  /** Expert column-meaning rules that fired on this dataset (the consult result). */
  semantic?: { column: string; role: string; label: string; rule_id: number; source: string; match_type: string }[];
};

export type Algorithm = {
  slug: string;
  name: string;
  category: string;
  description: string;
  source: 'builtin' | 'user' | 'ai';
  params_schema: Record<string, ParamSpec>;
  returns: string;
  verified: boolean;
  id?: number;
};

export type ParamSpec = {
  type?: string;
  default?: unknown;
  required?: boolean;
  description?: string;
  enum?: string[];
  items?: string;
  minimum?: number;
  maximum?: number;
};

export type RunResult = {
  status: 'ok' | 'error';
  error: string;
  duration_ms: number;
  summary: Record<string, unknown>;
  logs: string;
  result_path: string | null;
  result_rows: number;
  run_id?: number;
};

export type TestResult = {
  validation: { ok: boolean; errors: string[]; imports: string[]; has_run?: boolean; has_meta?: boolean };
  execution: RunResult;
  meta?: Record<string, unknown>;
};

export type GenerationResult = {
  code: string;
  meta: Record<string, unknown>;
  tests: { case: number; status: string; error: string; duration_ms: number; summary: Record<string, unknown> }[];
  all_tests_passed: boolean;
};

export type Conversation = { id: number; title: string; dataset_id: number | null };

export type TemplateStep = { action: string; slug?: string; params?: Record<string, unknown>; label?: string };
export type FlowGraphNode = { id: string; slug?: string; params?: Record<string, unknown>; label?: string; kind?: 'input' | 'step'; position: { x: number; y: number } };
export type FlowGraphEdge = { source: string; target: string };
/** Params promoted to "fill at replay time": the user is prompted for these in a
 *  form before the pipeline runs, instead of them being baked into the template.
 *  `stepIndex`/`slug`/`label`/`default` are stamped at save so a standalone run
 *  page (mini-program) needs no canvas/topo logic to build the form + overrides. */
export type FlowRuntimeParam = { nodeId: string; param: string; stepIndex?: number; slug?: string; label?: string; default?: unknown };
export type FlowGraph = { nodes?: FlowGraphNode[]; edges?: FlowGraphEdge[]; runtime?: FlowRuntimeParam[] };
export type FlowTemplate = { id: number; name: string; description: string; steps: TemplateStep[]; n_steps: number; graph?: FlowGraph };
export type TemplateRunResult = {
  steps: { i: number; label: string; slug?: string; status: string; error?: string; rows?: number; summary?: Record<string, unknown>; dataset_id?: number; report?: boolean }[];
  final: { rows: number; columns: string[]; preview: Record<string, unknown>[] };
  derived_chain?: { id: number; name: string; label: string; rows: number; columns: number; report?: boolean }[];
  new_dataset?: { id: number; name: string; rows: number; columns: number } | null;
};

export type ChatMessage = { id: number; role: string; content: string; meta: Record<string, unknown> };

export type Points3D = {
  n: number; total: number;
  x: number[]; y: number[]; z: number[];
  fields: string[]; color_field: string | null;
  color: (number | null)[] | null; cmin: number; cmax: number;
};

export type UploadResp = {
  status: 'ok' | 'needs_parser';
  dataset?: Dataset;
  datasets?: Dataset[]; // multi-sheet Excel → one dataset per worksheet
  needs_parser?: {
    staging_path: string;
    extension: string;
    filename: string;
    size_bytes: number;
    display_name?: string | null;
    description?: string;
  };
};

export type ParserProposal = {
  status: 'ok' | 'error';
  error: string;
  duration_ms: number;
  code: string;
  meta: Record<string, unknown>;
  result_rows: number;
  summary: Record<string, unknown>;
  preview: Record<string, unknown>[];
  staging_path: string;
};

export type FormatAdapter = {
  id: number;
  extension: string;
  name: string;
  description: string;
  is_verified: boolean;
  sample_size_bytes: number;
};

export type ParserEvent =
  | { event: 'attempt_start'; n: number; max: number }
  | { event: 'token'; n: number; delta: string }
  | { event: 'code_ready'; n: number; duration_ms: number; code: string; meta: Record<string, unknown>; size: number }
  | { event: 'validated'; n: number; imports: string[] }
  | { event: 'attempt_failed'; n: number; stage: string; duration_ms?: number; error: string }
  | { event: 'success'; n: number; duration_ms: number; code: string; meta: Record<string, unknown>; summary: Record<string, unknown>; result_rows: number; result_path?: string; preview: Record<string, unknown>[]; staging_path: string }
  | { event: 'give_up'; attempts: number; errors: string[]; last_code?: string }
  | { event: 'fatal'; error: string };

export async function streamParserGenerate(
  staging_path: string,
  extension: string,
  onEvent: (e: ParserEvent) => void,
): Promise<void> {
  const token = getToken();
  const r = await fetch('/api/datasets/generate-parser', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ staging_path, extension }),
  });
  if (!r.ok || !r.body) {
    const text = await r.text();
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 300)}`);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      if (block.startsWith('data:')) {
        try { onEvent(JSON.parse(block.slice(5).trim())); } catch { /* ignore */ }
      }
    }
  }
}

/** Stream the AI data-cleaner for a messy dataset. Reuses the parser event shape. */
export async function streamDatasetClean(
  datasetId: number,
  onEvent: (e: ParserEvent) => void,
): Promise<void> {
  const token = getToken();
  const r = await fetch(`/api/datasets/${datasetId}/clean`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!r.ok || !r.body) {
    const text = await r.text();
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 300)}`);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      if (block.startsWith('data:')) {
        try { onEvent(JSON.parse(block.slice(5).trim())); } catch { /* ignore */ }
      }
    }
  }
}

export async function streamChat(
  convId: number,
  message: string,
  dataset_id: number | null,
  onEvent: (e: { kind: string; payload: Record<string, unknown> }) => void,
  dataset_ids?: number[],
  signal?: AbortSignal,
  image_ref?: string | null,
): Promise<void> {
  const token = getToken();
  // SSE must bypass the Next dev rewrites proxy — it BUFFERS streaming responses,
  // so the whole answer would arrive at once instead of token-by-token. In dev
  // (port 3000) hit the backend directly (CORS allows :3000); in prod the app is
  // same-origin / behind a streaming-capable proxy, so stay relative.
  const base = (typeof window !== 'undefined' && window.location.port === '3000')
    ? `${window.location.protocol}//${window.location.hostname}:8077` : '';
  const r = await fetch(`${base}/api/chat/conversations/${convId}/send`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message, dataset_id, dataset_ids, image_ref: image_ref ?? undefined }),
    signal,
  });
  if (!r.ok || !r.body) {
    const text = await r.text();
    throw new Error(`chat HTTP ${r.status}: ${text}`);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nlIdx;
    while ((nlIdx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, nlIdx).trim();
      buf = buf.slice(nlIdx + 2);
      if (block.startsWith('data:')) {
        const payload = block.slice(5).trim();
        try {
          onEvent(JSON.parse(payload));
        } catch {
          /* ignore */
        }
      }
    }
  }
}

// ── 多车次对比类型 ──────────────────────────────────────────────────────
export interface WtRunState {
  M: number | null; BETA: number | null; PHI: number | null;
  dz: number | null; dy: number | null; dx: number | null; XU?: number | null;
}

export interface WtRunList {
  runs: {
    run_no: string; state: WtRunState; state_text: string;
    has_da: boolean; n_alpha: number; alpha_range: [number, number] | null;
  }[];
  count: number;
  machs: number[];
  state_vars: { key: string; label: string }[];
  columns: { key: string; label: string }[];
}

export interface WtMatrix {
  blocks: {
    label: string; mach: number | null; beta: number | null;
    run_count: number; runs: string[]; baseline_run: string | null;
    dz: number[]; dy: number[]; dx: number[];
  }[];
  block_count: number;
  without_baseline: string[];
  note: string;
}

export interface WtCompare {
  ok: boolean; mode: string; baseline: string | null;
  x_key: string; x_label: string;
  series: {
    run_no?: string; coefficient: string; label: string; group?: string;
    alpha?: number; state?: WtRunState; state_text?: string;
    x: number[]; y: number[]; runs?: string[];
  }[];
  legend?: ({ run_no: string } & WtRunState)[];
  available_columns: { key: string; label: string }[];
  notes: string[];
  two_groups?: boolean;
}

export interface WtEffectiveness {
  ok: boolean; surface: string; coefficients: string[]; alphas: number[];
  rows: {
    mach: number; beta: number; alpha: number; surface: string;
    deflection: number; run_no: string; baseline_run: string;
    coefficient: string; value: number; baseline_value: number;
    delta: number; derivative_per_deg: number;
  }[];
  notes: string[]; method: string;
}

export interface WtResponse {
  ok: boolean; surface: string; method: string;
  blocks: {
    mach: number; beta: number; alpha: number; coefficient: string;
    baseline_run: string; deflections: number[]; deltas: number[]; runs: string[];
    linear_slope_per_deg: number | null; linear_range_deg: number;
    max_deflection: number; saturation_ratio: number | null;
  }[];
}

export interface WtSymmetry {
  ok: boolean; surface: string; k_mad: number;
  median_asymmetry: number; robust_sigma: number;
  pairs: {
    mach: number; beta: number; alpha: number; coefficient: string;
    deflection: number; run_pos: string; run_neg: string;
    delta_pos: number; delta_neg: number; sum: number;
    asymmetry: number; flagged: boolean; score: number | null;
  }[];
  flagged: WtSymmetry['pairs'];
  method: string; note: string;
}

export interface WtRepeatability {
  groups: { label: string; runs: string[]; n: number; sd: Record<string, number> }[];
  pooled_sd: Record<string, number>;
  pooled_2sd: Record<string, number>;
  pooled_dof: Record<string, number>;
  outliers: { run_no: string; group: string; coefficient: string; note: string }[];
  singleton_runs: string[];
  group_count: number;
  repeated_group_count: number;
  notes: string[];
  reference: string;
  table: { coefficient: string; s_r: number; two_s_r: number; dof: number }[];
}

export interface WtCoverage {
  ok: boolean;
  error?: string;
  planned?: number;
  present?: string[];
  present_count?: number;
  missing?: { run_no: string; mach: number | null; label: string; note: string }[];
  superseded?: { run_no: string; mach: number | null; label: string; replaced_by: string[]; note: string }[];
  unplanned?: string[];
  not_flown_count?: number;
  machs?: number[];
  notes?: string[];
  headline?: string;
  state_mismatches?: { run_no: string; plan: Record<string, number | null>; actual: Record<string, number | null>; note: string }[];
  state_check?: string;
  plan_source?: string;
}
