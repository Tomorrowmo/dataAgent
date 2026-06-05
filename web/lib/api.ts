// Tiny typed fetch wrapper. All requests go through Next.js' /api rewrite
// to the FastAPI backend; in production both run under the same origin.

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

const TOKEN_KEY = 'numetrix.token';

export function setToken(token: string | null) {
  if (typeof window === 'undefined') return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

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

  listDatasets: () => request<Dataset[]>('GET', '/datasets'),
  getDataset: (id: number) => request<Dataset>('GET', `/datasets/${id}`),
  uploadDataset: (file: File, name?: string, description?: string) => {
    const fd = new FormData();
    fd.append('file', file);
    if (name) fd.append('name', name);
    if (description) fd.append('description', description);
    return request<UploadResp>('POST', '/datasets', fd);
  },
  deleteDataset: (id: number) => request<{ ok: boolean }>('DELETE', `/datasets/${id}`),
  /** Keep a derived/intermediate dataset — promote it to a first-class source dataset. */
  promoteDataset: (id: number) => request<Dataset>('POST', `/datasets/${id}/promote`),
  /** Pin/unpin a derived dataset in place so auto-GC won't reclaim it. */
  keepDataset: (id: number, kept = true) => request<Dataset>('POST', `/datasets/${id}/keep`, { kept }),
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
};

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
    body: JSON.stringify({ message, dataset_id, dataset_ids }),
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
