'use client';

import { useEffect, useState } from 'react';
import { Key, Save, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';
import { useT } from '@/lib/i18n';

type PresetId = 'deepseek' | 'qwen' | 'openai' | 'custom';

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
    default_model: 'deepseek-chat',
    model_options: ['deepseek-chat', 'deepseek-reasoner'],
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

  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  const preset = PRESETS.find((p) => p.id === presetId)!;

  useEffect(() => {
    api.me().then((u) => {
      setHasKey(u.has_llm_key);
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
          <Key className="w-4 h-4 text-brand-600" />
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
    </div>
  );
}
