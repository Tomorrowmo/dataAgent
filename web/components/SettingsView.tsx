'use client';

import HomeExamplesEditor from '@/components/HomeExamplesEditor';
import { useEffect, useState } from 'react';
import { BrainCircuit, Save, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { api, type RetentionPolicy } from '@/lib/api';
import { useT } from '@/lib/i18n';

type PresetId = 'deepseek' | 'qwen' | 'anthropic' | 'openai' | 'custom';

type Preset = {
  id: PresetId;
  label: string;
  base_url: string;
  default_model: string;
  model_options: string[];
  key_hint: string;
  docs: string;
};

const PRESETS: Preset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    base_url: 'https://api.deepseek.com/v1',
    // deepseek-chat / deepseek-reasoner retire 2026-07-24 15:59 UTC — both are
    // now modes of deepseek-v4-flash. Kept in the list so existing users can
    // still see what they had stored, but no longer offered as the default.
    default_model: 'deepseek-v4-flash',
    model_options: ['deepseek-v4-flash', 'deepseek-v4-pro'],
    key_hint: 'sk-...',
    docs: 'https://platform.deepseek.com',
  },
  {
    id: 'qwen',
    label: 'Qwen / 通义千问 (DashScope)',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    default_model: 'qwen-plus',
    model_options: ['qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen3-coder-plus', 'qwen-coder-plus'],
    key_hint: 'sk-...',
    docs: 'https://dashscope.console.aliyun.com',
  },
  {
    // Not an OpenAI-compatible endpoint — the backend detects `claude*` /
    // anthropic.com and routes through the official Anthropic SDK instead.
    id: 'anthropic',
    label: 'Claude / Anthropic',
    base_url: 'https://api.anthropic.com',
    default_model: 'claude-opus-4-8',
    model_options: ['claude-opus-4-8', 'claude-sonnet-5', 'claude-haiku-4-5'],
    key_hint: 'sk-ant-...',
    docs: 'https://console.anthropic.com',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini',
    model_options: ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1'],
    key_hint: 'sk-...',
    docs: 'https://platform.openai.com',
  },
  {
    id: 'custom',
    label: 'Custom (any OpenAI-compatible endpoint)',
    base_url: '',
    default_model: '',
    model_options: [],
    key_hint: 'Bearer token',
    docs: '',
  },
];

function presetFor(base_url: string): PresetId {
  if (!base_url) return 'deepseek';
  const hit = PRESETS.find((p) => p.id !== 'custom' && p.base_url === base_url);
  return hit?.id ?? 'custom';
}

export default function SettingsView() {
  const t = useT();
  const [hasKey, setHasKey] = useState(false);
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');

  const [presetId, setPresetId] = useState<PresetId>('deepseek');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [key, setKey] = useState('');

  const [isAdmin, setIsAdmin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  const preset = PRESETS.find((p) => p.id === presetId)!;

  useEffect(() => {
    api.me().then((u) => {
      setHasKey(u.has_llm_key);
      setIsAdmin(!!u.is_admin);
      setEmail(u.email);
      setName(u.name);
      const detected = presetFor(u.llm_base_url || '');
      setPresetId(detected);
      setBaseUrl(u.llm_base_url || '');
      setModel(u.llm_model || '');
    }).catch(() => {});
  }, []);

  function pickPreset(id: PresetId) {
    setPresetId(id);
    setSaved(false);
    const p = PRESETS.find((x) => x.id === id)!;
    if (id !== 'custom') {
      setBaseUrl(p.base_url);
      if (!model || !p.model_options.includes(model)) setModel(p.default_model);
    } else {
      setBaseUrl('');
      setModel('');
    }
  }

  async function save() {
    setBusy(true); setError(''); setSaved(false);
    try {
      const r = await api.saveLLMConfig(key, baseUrl, model);
      setHasKey(r.has_llm_key);
      setKey('');
      setSaved(true);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-xl font-semibold mb-1">{t('set.title')}</h2>
      <p className="text-sm text-ink-500 mb-6">{t('set.sub')}</p>

      <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 mb-5">
        <h3 className="font-medium mb-2">{t('set.account')}</h3>
        <div className="text-sm text-ink-700">{t('set.email')} <span className="font-mono">{email}</span></div>
        <div className="text-sm text-ink-700">{t('set.name')} {name || <span className="text-ink-500">{t('set.nameNone')}</span>}</div>
      </div>

      <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5">
        <div className="flex items-center gap-2 mb-2">
          <BrainCircuit className="w-4 h-4 text-brand-600" />
          <h3 className="font-medium">{t('set.llm.title')}</h3>
        </div>
        <p className="text-sm text-ink-500 mb-4">
          {t('set.llm.desc')} <strong>{hasKey ? t('set.llm.keySet') : t('set.llm.keyMissing')}</strong>.
        </p>

        <label className="block text-xs font-medium text-ink-700 mb-1">{t('set.llm.provider')}</label>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => pickPreset(p.id)}
              className={`text-left text-xs px-3 py-2 rounded-lg border ${
                presetId === p.id
                  ? 'border-brand-500 bg-brand-50 text-brand-700 font-medium'
                  : 'border-ink-200 hover:bg-ink-50'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        <label className="block text-xs font-medium text-ink-700 mb-1">{t('set.llm.baseUrl')}</label>
        <input
          type="text"
          value={baseUrl}
          onChange={(e) => { setBaseUrl(e.target.value); setSaved(false); }}
          placeholder={preset.id === 'custom' ? 'https://your-endpoint/v1' : preset.base_url}
          className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm font-mono mb-3 focus:outline-none focus:border-brand-500"
        />

        <label className="block text-xs font-medium text-ink-700 mb-1">{t('set.llm.model')}</label>
        {preset.model_options.length > 0 ? (
          <div className="flex gap-2 items-center mb-3">
            <select
              value={preset.model_options.includes(model) ? model : '__custom'}
              onChange={(e) => { if (e.target.value !== '__custom') setModel(e.target.value); setSaved(false); }}
              className="border border-ink-200 rounded-lg px-2 py-2 text-sm bg-white"
            >
              {preset.model_options.map((m) => <option key={m} value={m}>{m}</option>)}
              <option value="__custom">{t('set.llm.custom')}</option>
            </select>
            <input
              type="text"
              value={model}
              onChange={(e) => { setModel(e.target.value); setSaved(false); }}
              placeholder="model id"
              className="flex-1 border border-ink-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-brand-500"
            />
          </div>
        ) : (
          <input
            type="text"
            value={model}
            onChange={(e) => { setModel(e.target.value); setSaved(false); }}
            placeholder="e.g. llama3.1:8b"
            className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm font-mono mb-3 focus:outline-none focus:border-brand-500"
          />
        )}

        <label className="block text-xs font-medium text-ink-700 mb-1">{t('set.llm.apiKey')}</label>
        <input
          type="password"
          value={key}
          onChange={(e) => { setKey(e.target.value); setSaved(false); }}
          placeholder={hasKey ? t('set.llm.keyExists') : preset.key_hint}
          className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-brand-500"
        />
        <div className="text-xs text-ink-500 mt-2">
          {preset.docs && <>{t('set.llm.docHint')} <a className="text-brand-600 hover:underline" href={preset.docs} target="_blank" rel="noreferrer">{preset.docs}</a>. </>}
          {t('set.llm.clearHint')}
        </div>

        <button onClick={save} disabled={busy} className={`mt-4 px-4 py-2 rounded-xl font-medium flex items-center gap-2 ${saved ? 'bg-emerald-600 text-white' : 'bg-brand-600 text-white hover:bg-brand-700'} disabled:opacity-50`}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : saved ? <CheckCircle2 className="w-4 h-4" /> : <Save className="w-4 h-4" />}
          {busy ? t('set.llm.saving') : saved ? t('set.llm.saved') : t('set.llm.save')}
        </button>
        {error && <div className="mt-3 text-sm text-red-600 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {error}</div>}
      </div>
      {isAdmin && <RetentionSettings />}
      {isAdmin && <HomeExamplesEditor />}
    </div>
  );
}

/** Admins: how long un-kept intermediate results live (改进清单-3 · R4). */
function RetentionSettings() {
  const [p, setP] = useState<RetentionPolicy | null>(null);
  const [msg, setMsg] = useState('');
  useEffect(() => { api.retentionPolicy().then(setP).catch(() => {}); }, []);
  if (!p) return null;
  const field = (k: keyof RetentionPolicy, label: string, hint: string) => (
    <label className="block">
      <span className="text-sm text-ink-800">{label}</span>
      <span className="ml-2 text-xs text-ink-500">{hint}</span>
      <div className="mt-1 flex items-center border border-ink-300 rounded h-8 w-40 overflow-hidden">
        <input type="number" min={1} value={p[k]} onChange={(e) => setP({ ...p, [k]: Math.max(1, Number(e.target.value) || 1) })}
          className="flex-1 min-w-0 h-full px-2 text-right font-mono text-sm border-0" />
        <span className="px-2 h-full inline-flex items-center border-l border-ink-200 bg-ink-50 text-xs text-ink-600">天</span>
      </div>
    </label>
  );
  return (
    <div className="bg-white rounded-md border border-ink-200 p-5 mt-5 space-y-3">
      <h3 className="font-medium">中间结果保留（管理员）</h3>
      <p className="text-xs text-ink-600 leading-relaxed">未保留的中间结果到期后删除数据，运行记录和血缘保留。到期前提醒用户；用户确认过提醒才删除，从未确认的最迟在兜底期限删除。已保留和正在使用的数据永不自动清理。</p>
      {field('retention_days', '保留期', '每份中间结果从产生起')}
      {field('notice_days', '提前提醒', '到期前多少天出现在「即将清理」')}
      {field('max_days', '兜底期限', '从未确认提醒时，创建后多少天删除')}
      <div className="flex items-center gap-3">
        <button onClick={async () => { try { setP(await api.setRetentionPolicy(p)); setMsg('已保存'); } catch (e) { setMsg((e as Error).message); } }}
          className="h-8 px-3 rounded border border-brand-600 bg-brand-600 text-white text-sm hover:bg-brand-700">保存</button>
        {msg && <span className="text-xs text-ink-600">{msg}</span>}
      </div>
    </div>
  );
}
