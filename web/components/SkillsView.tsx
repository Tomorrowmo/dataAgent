'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Puzzle, Upload, Loader2, CheckCircle2, AlertTriangle, Sparkles, Trash2, Power, FileText,
  ChevronDown, Pencil, Check, X, Send, Undo2, Bot, Wrench, BookOpen, CircleDot,
} from 'lucide-react';
import { api, importSkillStream, type Skill, type SkillCard, type SkillImportEvent } from '@/lib/api';

// 技能 Skills: import a skill package and watch it being read (live steps), then
// review its description card — readable sections, each editable in place, plus
// an AI panel that adjusts the card from plain language. Every change saves
// immediately (with undo); enabling the skill is one click.

const STATUS: Record<Skill['status'], { label: string; cls: string }> = {
  draft: { label: '草稿 · 待启用', cls: 'bg-amber-100 text-amber-800' },
  active: { label: '已启用', cls: 'bg-emerald-100 text-emerald-700' },
  disabled: { label: '已停用', cls: 'bg-ink-100 text-ink-500' },
};

type ImportState = { filename: string; events: SkillImportEvent[]; done: boolean };

const scriptKind = (x: Skill['scripts'][number]) => x.kind ?? (x.ok ? 'tool' : 'reference');

const EMPTY_CARD: SkillCard = { name: '', summary: '', when_to_use: [], inputs: [], steps: [], outputs: [], tools: [], cautions: [] };

export default function SkillsView() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [imp, setImp] = useState<ImportState | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [toggling, setToggling] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reload = () => api.listSkills().then(setSkills).catch(() => {});
  useEffect(() => { reload(); }, []);

  async function onPick(f?: File) {
    if (!f) return;
    setOpenId(null);
    setImp({ filename: f.name, events: [], done: false });
    try {
      await importSkillStream(f, (e) => {
        setImp((s) => (s ? { ...s, events: [...s.events, e], done: e.stage === 'saved' || e.stage === 'error' } : s));
        if (e.stage === 'saved') {
          // Land on the new skill's page to review and enable it.
          reload().then(() => { setOpenId(e.skill.id); setImp(null); });
        }
      });
    } catch (e) {
      setImp((s) => (s ? { ...s, events: [...s.events, { stage: 'error', message: (e as Error).message }], done: true } : s));
    }
  }

  async function toggle(s: Skill) {
    setToggling(s.id);
    try { await api.updateSkill(s.id, { status: s.status === 'active' ? 'disabled' : 'active' }); await reload(); }
    finally { setToggling(null); }
  }

  const importing = !!imp && !imp.done;
  const fileInput = (
    <input ref={fileRef} type="file" accept=".zip,.md,.txt" className="hidden"
      onChange={(e) => { onPick(e.target.files?.[0]); e.target.value = ''; }} />
  );

  // ── detail page ──
  const open = skills.find((s) => s.id === openId);
  if (open) {
    return (
      <div className="h-full overflow-y-auto scroll-hide">
        {fileInput}
        <div className="sticky top-0 z-10 bg-white/90 backdrop-blur border-b border-ink-200 px-5 py-2">
          <button onClick={() => { setOpenId(null); reload(); }} className="text-sm text-brand-700 hover:text-brand-900">← 所有技能</button>
        </div>
        <SkillDetail key={open.id} skill={open} justImported={false}
          onChanged={(s) => { if (!s) { setOpenId(null); } reload(); }} />
      </div>
    );
  }

  // ── gallery ──
  const mine = skills.filter((s) => !s.is_default);
  const defaults = skills.filter((s) => s.is_default);
  return (
    <div className="h-full overflow-y-auto scroll-hide"
      onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDragOver(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false); }}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); if (!importing) onPick(e.dataTransfer.files?.[0]); }}>
      {fileInput}
      <div className="max-w-6xl mx-auto px-5 py-6 space-y-6">
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex-1 min-w-[240px]">
            <h1 className="text-xl font-semibold flex items-center gap-2"><Puzzle className="w-5 h-5 text-brand-600" />技能 Skills</h1>
            <p className="text-sm text-ink-500 mt-1">把你的专业分析方法交给智能体：启用后，在对话输入框上方的「Skills」里勾选，智能体就按这个方法来分析。</p>
          </div>
          <button onClick={() => fileRef.current?.click()} disabled={importing}
            className="flex items-center gap-1.5 bg-brand-600 text-white text-sm px-4 py-2 rounded-xl hover:bg-brand-700 disabled:opacity-60">
            {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} {importing ? '正在导入…' : '添加 Skill'}
          </button>
        </div>

        {imp ? (
          <div className="rounded-2xl ring-1 ring-brand-200 bg-white">
            <ImportProgress state={imp} onRetry={() => fileRef.current?.click()} onClose={() => setImp(null)} />
          </div>
        ) : (
          <button onClick={() => fileRef.current?.click()}
            className={`w-full rounded-2xl border-2 border-dashed py-6 px-4 text-sm flex flex-col items-center gap-1.5 transition ${
              dragOver ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-ink-200 bg-white text-ink-500 hover:border-brand-300 hover:bg-brand-50/40'}`}>
            <Upload className="w-6 h-6 text-brand-500" />
            <span className="font-medium text-ink-700">把 skill 的 .zip 或 SKILL.md 拖到这里</span>
            <span className="text-xs">也可以点击选择文件 · zip 里包含 SKILL.md，可附带脚本和参考资料</span>
          </button>
        )}

        <section>
          <h2 className="text-sm font-medium text-ink-600 mb-2">我的 Skills <span className="text-ink-400">({mine.length})</span></h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {mine.map((s) => <SkillTile key={s.id} s={s} busy={toggling === s.id} onOpen={() => setOpenId(s.id)} onToggle={() => toggle(s)} />)}
            <button onClick={() => fileRef.current?.click()} disabled={importing}
              className="rounded-2xl border-2 border-dashed border-ink-200 text-ink-400 hover:border-brand-300 hover:text-brand-600 min-h-[150px] flex flex-col items-center justify-center gap-1 text-sm disabled:opacity-50">
              <Upload className="w-5 h-5" /> 添加 Skill
            </button>
          </div>
        </section>

        {defaults.length > 0 && (
          <section>
            <h2 className="text-sm font-medium text-ink-600 mb-2">平台默认 <span className="text-ink-400">· 所有用户可用，可停用</span></h2>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {defaults.map((s) => <SkillTile key={s.id} s={s} busy={toggling === s.id} onOpen={() => setOpenId(s.id)} onToggle={() => toggle(s)} />)}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

const FIT_TAG: Record<string, { label: string; cls: string }> = {
  full: { label: '完全可用', cls: 'text-emerald-700 bg-emerald-50 ring-emerald-100' },
  partial: { label: '部分可用', cls: 'text-amber-800 bg-amber-50 ring-amber-100' },
  low: { label: '平台上基本无法执行', cls: 'text-red-700 bg-red-50 ring-red-100' },
};

/** One skill in the gallery: what it is, whether it's on, how well it fits —
 *  enabled / disabled can be switched right here; drafts go through review. */
function SkillTile({ s, busy, onOpen, onToggle }: { s: Skill; busy: boolean; onOpen: () => void; onToggle: () => void }) {
  const nTool = s.scripts.filter((x) => scriptKind(x) === 'tool').length;
  const nRef = s.scripts.filter((x) => scriptKind(x) === 'reference').length;
  const fit = s.config?.platform_fit?.level ? FIT_TAG[s.config.platform_fit.level] : null;
  const on = s.status === 'active';
  return (
    <div onClick={onOpen} role="button"
      className={`group text-left rounded-2xl ring-1 bg-white p-4 cursor-pointer transition hover:-translate-y-0.5 hover:shadow-sm flex flex-col gap-2 min-h-[150px] ${
        s.status === 'draft' ? 'ring-amber-200' : 'ring-ink-200 hover:ring-brand-300'}`}>
      <div className="flex items-start gap-2">
        <Puzzle className={`w-4 h-4 mt-0.5 shrink-0 ${on ? 'text-brand-600' : 'text-ink-400'}`} />
        <div className="font-medium text-sm text-ink-800 flex-1 min-w-0 line-clamp-2">{s.config?.name || s.name}</div>
        {s.status === 'draft' ? (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 shrink-0">待启用</span>
        ) : (
          <button onClick={(e) => { e.stopPropagation(); onToggle(); }} disabled={busy} title={on ? '点击停用' : '点击启用'}
            className={`relative w-9 h-5 rounded-full shrink-0 transition ${on ? 'bg-emerald-500' : 'bg-ink-300'} disabled:opacity-50`}>
            <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${on ? 'left-[18px]' : 'left-0.5'}`} />
          </button>
        )}
      </div>
      <div className="text-xs text-ink-500 line-clamp-3 flex-1">{s.config?.summary || s.description || '（还没有说明）'}</div>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        {fit && <span className={`px-1.5 py-0.5 rounded ring-1 ${fit.cls}`}>{fit.label}</span>}
        {nTool > 0 && <span className="px-1.5 py-0.5 rounded bg-ink-50 ring-1 ring-ink-200 text-ink-600">{nTool} 个平台工具</span>}
        {nRef > 0 && <span className="px-1.5 py-0.5 rounded bg-ink-50 ring-1 ring-ink-200 text-ink-500">{nRef} 个参考脚本</span>}
        {s.status === 'draft' && <span className="text-amber-700 ml-auto group-hover:underline">查看并启用 →</span>}
        {s.status === 'disabled' && <span className="text-ink-400 ml-auto">已停用</span>}
      </div>
    </div>
  );
}

/* ═════════════ live import ═════════════ */

function ImportProgress({ state, onRetry, onClose }: { state: ImportState; onRetry: () => void; onClose: () => void }) {
  const ev = <K extends SkillImportEvent['stage']>(k: K) =>
    state.events.find((e) => e.stage === k) as Extract<SkillImportEvent, { stage: K }> | undefined;
  const err = ev('error');
  const recv = ev('received');
  const ex = ev('extracted');
  const md = ev('skill_md');
  const sc = ev('scripts');
  const rf = ev('references');
  const ai = ev('ai_reading');
  const card = ev('card');
  const saved = ev('saved');
  const nTool = sc?.items.filter((i) => i.kind === 'tool').length ?? 0;
  const nRef = sc?.items.filter((i) => i.kind === 'reference').length ?? 0;

  const steps: { key: string; title: string; done: boolean; body?: React.ReactNode }[] = [
    { key: 'r', done: !!recv, title: `收到文件 ${state.filename}${recv ? `（${(recv.size / 1024).toFixed(1)} KB）` : ''}` },
    {
      key: 'x', done: !!ex, title: ex ? `解压完成：${ex.count} 个可用文件` : '解压并检查文件',
      body: ex && (
        <details className="text-xs text-ink-500"><summary className="cursor-pointer select-none">查看文件</summary>
          <div className="font-mono mt-1 space-y-0.5">{ex.files.map((f) => <div key={f}>{f}</div>)}</div></details>
      ),
    },
    { key: 'm', done: !!md, title: md ? `找到 SKILL.md：「${md.name}」（${md.chars} 字）` : '寻找 SKILL.md',
      body: md?.description && <div className="text-xs text-ink-500">{md.description}</div> },
    {
      key: 's', done: !!sc,
      title: sc ? (sc.items.length ? `识别脚本：${nTool} 个可作为平台工具，${nRef} 个作为参考` : '没有附带脚本') : '识别脚本',
      body: sc && sc.items.length > 0 && <div className="space-y-1">{sc.items.map((i) => <ScriptLine key={i.path} path={i.path} kind={i.kind} note={i.note} />)}</div>,
    },
    { key: 'f', done: !!rf, title: rf ? (rf.items.length ? `参考资料：${rf.items.length} 份` : '没有参考资料') : '整理参考资料',
      body: rf && rf.items.length > 0 && <div className="text-xs text-ink-500 font-mono">{rf.items.map((r) => r.path).join('、')}</div> },
    { key: 'a', done: !!card,
      title: card ? (card.source === 'ai' ? 'AI 已生成说明卡，并检查了在本平台的适配度' : '未配置 AI 模型：已从 SKILL.md 直接提取说明') : (ai?.msg || 'AI 阅读并生成说明卡'),
      body: card?.fit?.level ? <FitBanner fit={card.fit} compact /> : undefined },
    { key: 'v', done: !!saved, title: saved ? '已保存为草稿' : '保存' },
  ];
  const current = steps.findIndex((s) => !s.done);

  return (
    <div className="max-w-2xl p-6">
      <div className="flex items-center gap-2 mb-4">
        <Puzzle className="w-5 h-5 text-brand-600" />
        <h2 className="text-lg font-semibold flex-1">导入 skill</h2>
        {err && <button onClick={onClose} className="text-xs text-ink-400 hover:text-ink-600">关闭</button>}
      </div>
      <ol className="space-y-3">
        {steps.map((s, i) => {
          const running = !err && i === current;
          if (!s.done && !running) {
            return <li key={s.key} className="flex gap-2.5 text-sm text-ink-300"><CircleDot className="w-4 h-4 mt-0.5 shrink-0" />{s.title}</li>;
          }
          return (
            <li key={s.key} className="flex gap-2.5">
              {s.done ? <CheckCircle2 className="w-4 h-4 mt-0.5 text-emerald-600 shrink-0" />
                : err ? <AlertTriangle className="w-4 h-4 mt-0.5 text-red-500 shrink-0" />
                  : <Loader2 className="w-4 h-4 mt-0.5 text-brand-600 animate-spin shrink-0" />}
              <div className="min-w-0 flex-1 space-y-1">
                <div className={`text-sm ${s.done ? 'text-ink-800' : 'text-brand-700'}`}>{s.title}</div>
                {s.body}
              </div>
            </li>
          );
        })}
      </ol>
      {err && (
        <div className="mt-4 rounded-lg bg-red-50 ring-1 ring-red-100 text-red-700 text-sm p-3">
          导入失败：{err.message}
          <button onClick={onRetry} className="ml-2 underline">重新选择文件</button>
        </div>
      )}
    </div>
  );
}

function ScriptLine({ path, kind, note }: { path: string; kind: 'tool' | 'reference'; note?: string }) {
  const tool = kind === 'tool';
  return (
    <div className={`text-xs rounded-md px-2 py-1.5 ring-1 ${tool ? 'ring-emerald-100 bg-emerald-50/50' : 'ring-ink-200 bg-ink-50/60'}`}>
      <div className="flex items-center gap-1.5 min-w-0">
        {tool ? <Wrench className="w-3.5 h-3.5 text-emerald-600 shrink-0" /> : <BookOpen className="w-3.5 h-3.5 text-ink-500 shrink-0" />}
        <span className="font-mono truncate">{path}</span>
        <span className={`ml-auto shrink-0 px-1.5 py-0.5 rounded ${tool ? 'bg-emerald-100 text-emerald-700' : 'bg-ink-100 text-ink-600'}`}>{tool ? '平台工具' : '参考脚本'}</span>
      </div>
      {note && <div className="text-ink-500 mt-1">{note}</div>}
    </div>
  );
}

function FitBanner({ fit, compact = false }: { fit: NonNullable<SkillCard['platform_fit']>; compact?: boolean }) {
  if (!fit.level) return null;
  const m = {
    full: { cls: 'bg-emerald-50 ring-emerald-200 text-emerald-800', label: '在本平台完全可用' },
    partial: { cls: 'bg-amber-50 ring-amber-200 text-amber-900', label: '在本平台部分可用' },
    low: { cls: 'bg-red-50 ring-red-200 text-red-800', label: '在本平台基本无法执行' },
  }[fit.level];
  return (
    <div className={`rounded-lg ring-1 ${m.cls} ${compact ? 'px-2.5 py-1.5 text-xs' : 'p-3 text-sm'}`}>
      <div className="font-medium">{m.label}{fit.summary ? `：${fit.summary}` : ''}</div>
      {fit.missing.length > 0 && (
        <div className={compact ? 'mt-0.5' : 'mt-1.5'}>
          <span className="opacity-80">平台上缺少：</span>
          <ul className="list-disc pl-5">{fit.missing.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

/* ═════════════ review / edit ═════════════ */

const LIST_SECTIONS: { key: 'when_to_use' | 'inputs' | 'steps' | 'outputs' | 'cautions'; label: string; ordered?: boolean }[] = [
  { key: 'when_to_use', label: '适用场景' },
  { key: 'inputs', label: '需要的数据' },
  { key: 'steps', label: '分析步骤', ordered: true },
  { key: 'outputs', label: '产出' },
  { key: 'cautions', label: '注意事项' },
];

function SkillDetail({ skill, justImported, onChanged }: { skill: Skill; justImported: boolean; onChanged: (s?: Skill) => void }) {
  // Older / hand-made cards may miss fields — fill them so every section renders.
  const card: SkillCard = { ...EMPTY_CARD, ...(skill.config as Partial<SkillCard>) };
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState('');
  const tools = skill.scripts.filter((x) => scriptKind(x) === 'tool');
  const refScripts = skill.scripts.filter((x) => scriptKind(x) === 'reference');
  const st = STATUS[skill.status];
  const live = (msg: string) => setNote(skill.status === 'active' ? `${msg}，下一条对话消息生效` : msg);

  async function saveCard(next: SkillCard, msg = '已保存') {
    const s = await api.updateSkill(skill.id, { config: next });
    live(msg);
    onChanged(s);
  }
  async function setStatus(status: 'active' | 'disabled') {
    setBusy(status); setNote('');
    try {
      const s = await api.updateSkill(skill.id, { status });
      setNote(status === 'active'
        ? `已启用${tools.length ? `，${tools.length} 个脚本已注册为平台工具` : ''}。在对话输入框上方的「Skills」里勾选即可使用。`
        : '已停用，对话里不再可选。');
      onChanged(s);
    } catch (e) { setNote('操作失败：' + (e as Error).message); }
    finally { setBusy(''); }
  }

  return (
    <div className="p-5 xl:p-6">
      <div className="flex flex-wrap items-start gap-3 mb-3">
        <Puzzle className="w-6 h-6 text-brand-600 mt-0.5" />
        <div className="flex-1 min-w-0">
          <InlineText value={card.name || skill.name} className="text-lg font-semibold" onSave={(v) => saveCard({ ...card, name: v }, '名称已保存')} />
          <div className="flex flex-wrap items-center gap-1.5 mt-1 text-xs">
            <span className={`px-2 py-0.5 rounded-full ${st.cls}`}>{st.label}</span>
            {skill.is_default && <span className="px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 ring-1 ring-brand-100">平台默认</span>}
            <span className="text-ink-400 font-mono">{skill.slug} · 来自 {skill.source_filename}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {skill.status !== 'active' ? (
            <button disabled={!!busy} onClick={() => setStatus('active')}
              className="px-4 py-2 rounded-xl bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1.5">
              {busy === 'active' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Power className="w-4 h-4" />} 启用
            </button>
          ) : (
            <button disabled={!!busy} onClick={() => setStatus('disabled')}
              className="px-3 py-2 rounded-xl ring-1 ring-ink-200 text-sm text-ink-700 hover:bg-ink-50 disabled:opacity-50 flex items-center gap-1.5">
              <Power className="w-4 h-4" /> 停用
            </button>
          )}
          {!skill.is_default && (
            <button disabled={!!busy} title="删除" onClick={async () => {
              if (!window.confirm(`删除 skill「${card.name || skill.name}」？它注册的工具也会一起删除。`)) return;
              await api.deleteSkill(skill.id);
              onChanged();
            }} className="p-2 rounded-xl ring-1 ring-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"><Trash2 className="w-4 h-4" /></button>
          )}
        </div>
      </div>
      {skill.status === 'draft' && (
        <div className="text-sm text-amber-900 bg-amber-50 ring-1 ring-amber-200 rounded-xl px-3 py-2 mb-3">
          {justImported ? '导入完成。' : ''}这是草稿：看一下下面的说明，不对的地方直接点「编辑」改，或者让右边的 AI 改；改动会立即保存。没问题就点右上角「启用」。
        </div>
      )}
      {skill.is_default && <div className="text-xs text-ink-500 mb-3">平台自带的通用 skill，所有用户默认可用；可以修改说明或停用，但不能删除。</div>}
      {note && <div className={`text-xs mb-3 ${note.startsWith('操作失败') ? 'text-red-600' : 'text-emerald-700'}`}>{note}</div>}

      <div className="flex gap-5 max-xl:flex-col">
        <div className="flex-1 min-w-0 space-y-4">
          <Section title="一句话说明">
            <InlineText value={card.summary} multiline placeholder="（还没有说明）" onSave={(v) => saveCard({ ...card, summary: v })} />
          </Section>
          {card.platform_fit?.level ? <Section title="平台适配"><FitBanner fit={card.platform_fit} /></Section> : null}
          {LIST_SECTIONS.map((sec) => (
            <Section key={sec.key} title={sec.label}>
              <InlineList items={card[sec.key]} ordered={sec.ordered} onSave={(v) => saveCard({ ...card, [sec.key]: v })} />
            </Section>
          ))}
          <Section title="附带的脚本">
            {skill.scripts.length === 0 ? <div className="text-sm text-ink-400">没有脚本 —— 计算会用平台已有的算法。</div> : (
              <div className="space-y-1.5">
                {[...tools, ...refScripts].map((x) => {
                  const purpose = card.tools.find((t) => t.file === x.path)?.purpose;
                  return (
                    <div key={x.path}>
                      <ScriptLine path={x.path} kind={scriptKind(x)}
                        note={[x.tool_slug ? `已注册为平台工具 ${x.tool_slug}。` : '', purpose || x.note || ''].filter(Boolean).join(' ')} />
                      {!x.ok && x.errors.length > 0 && (
                        <details className="text-[11px] text-ink-400 ml-2 mt-0.5">
                          <summary className="cursor-pointer select-none">为什么不能在平台上直接运行</summary>
                          <ul className="list-disc pl-5 font-mono">{x.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Section>
          <Section title="参考资料">
            {skill.references.length === 0 ? <div className="text-sm text-ink-400">无</div>
              : skill.references.map((r) => (
                <div key={r.path} className="text-sm text-ink-600 flex items-center gap-1.5"><FileText className="w-3.5 h-3.5" />{r.path}<span className="text-ink-400 text-xs">（{r.chars} 字）</span></div>
              ))}
          </Section>
          <details>
            <summary className="text-xs text-ink-500 cursor-pointer select-none inline-flex items-center gap-1"><ChevronDown className="w-3 h-3" />SKILL.md 原文</summary>
            <pre className="mt-2 text-[12px] whitespace-pre-wrap bg-ink-50 rounded-lg p-3 max-h-96 overflow-auto">{skill.instructions || '（空）'}</pre>
          </details>
        </div>

        <SkillAIPanel skill={skill} onChanged={(s, msg) => { live(msg); onChanged(s); }} />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-ink-500 mb-1">{title}</div>
      {children}
    </div>
  );
}

function InlineText({ value, onSave, multiline = false, placeholder = '', className = 'text-sm text-ink-800' }: {
  value: string; onSave: (v: string) => Promise<void>; multiline?: boolean; placeholder?: string; className?: string;
}) {
  const [edit, setEdit] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (edit === null) {
    return (
      <div className={`group flex items-start gap-1.5 ${className}`}>
        <span className={`whitespace-pre-wrap ${value ? '' : 'text-ink-400'}`}>{value || placeholder}</span>
        <button onClick={() => setEdit(value)} title="编辑" className="opacity-0 group-hover:opacity-100 text-ink-400 hover:text-brand-600 shrink-0 mt-1"><Pencil className="w-3.5 h-3.5" /></button>
      </div>
    );
  }
  const save = async () => { setBusy(true); try { await onSave(edit.trim()); setEdit(null); } finally { setBusy(false); } };
  return (
    <div className="flex items-start gap-1.5">
      {multiline
        ? <textarea autoFocus value={edit} onChange={(e) => setEdit(e.target.value)} rows={3} className="flex-1 border border-brand-300 rounded-lg px-2.5 py-1.5 text-sm" />
        : <input autoFocus value={edit} onChange={(e) => setEdit(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEdit(null); }}
            className="flex-1 border border-brand-300 rounded-lg px-2.5 py-1.5 text-sm" />}
      <button onClick={save} disabled={busy} title="保存" className="p-1.5 rounded-md bg-brand-600 text-white disabled:opacity-50">
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
      </button>
      <button onClick={() => setEdit(null)} title="取消" className="p-1.5 rounded-md ring-1 ring-ink-200 text-ink-500"><X className="w-3.5 h-3.5" /></button>
    </div>
  );
}

function InlineList({ items, ordered, onSave }: { items: string[]; ordered?: boolean; onSave: (v: string[]) => Promise<void> }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (edit === null) {
    const List = ordered ? 'ol' : 'ul';
    return (
      <div className="group relative rounded-lg hover:bg-ink-50/70 -mx-2 px-2 py-1">
        {items.length === 0 ? <div className="text-sm text-ink-400">（无）</div> : (
          <List className={`text-sm text-ink-800 space-y-0.5 pl-5 ${ordered ? 'list-decimal' : 'list-disc'}`}>
            {items.map((x, i) => <li key={i}>{x}</li>)}
          </List>
        )}
        <button onClick={() => setEdit(items.join('\n'))}
          className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 text-xs text-ink-500 hover:text-brand-600 inline-flex items-center gap-1 bg-white ring-1 ring-ink-200 rounded-md px-1.5 py-0.5">
          <Pencil className="w-3 h-3" /> 编辑
        </button>
      </div>
    );
  }
  const save = async () => {
    setBusy(true);
    try { await onSave(edit.split('\n').map((x) => x.trim()).filter(Boolean)); setEdit(null); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-1.5">
      <textarea autoFocus value={edit} onChange={(e) => setEdit(e.target.value)} rows={Math.max(3, edit.split('\n').length + 1)}
        className="w-full border border-brand-300 rounded-lg px-2.5 py-1.5 text-sm leading-relaxed" />
      <div className="flex items-center gap-2 text-xs">
        <button onClick={save} disabled={busy} className="px-2.5 py-1 rounded-md bg-brand-600 text-white disabled:opacity-50 inline-flex items-center gap-1">
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
        </button>
        <button onClick={() => setEdit(null)} className="px-2.5 py-1 rounded-md ring-1 ring-ink-200 text-ink-600">取消</button>
        <span className="text-ink-400">每行一条</span>
      </div>
    </div>
  );
}

/* ═════════════ AI adjusts the card ═════════════ */

type AiMsg = { id: number; role: 'user' | 'ai'; text: string; prev?: SkillCard; undone?: boolean; error?: boolean };

const QUICK = ['写得更简洁', '适用场景写具体一点', '补充注意事项', '重新检查平台适配'];

function SkillAIPanel({ skill, onChanged }: { skill: Skill; onChanged: (s: Skill, msg: string) => void }) {
  const [msgs, setMsgs] = useState<AiMsg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }); }, [msgs]);

  async function send(text: string) {
    const t = text.trim();
    if (!t || busy) return;
    setInput('');
    const prev = skill.config;
    setMsgs((m) => [...m, { id: nextId.current++, role: 'user', text: t }]);
    setBusy(true);
    try {
      const r = await api.adjustSkill(skill.id, t);
      setMsgs((m) => [...m, { id: nextId.current++, role: 'ai', text: r.reply, prev }]);
      onChanged(r.skill, 'AI 已修改并保存');
    } catch (e) {
      setMsgs((m) => [...m, { id: nextId.current++, role: 'ai', text: (e as Error).message, error: true }]);
    } finally { setBusy(false); }
  }

  async function undo(m: AiMsg) {
    if (!m.prev) return;
    const s = await api.updateSkill(skill.id, { config: m.prev });
    setMsgs((x) => x.map((y) => (y.id === m.id ? { ...y, undone: true } : y)));
    onChanged(s, '已撤销这次修改');
  }

  return (
    <div className="xl:w-[340px] shrink-0 rounded-2xl ring-1 ring-violet-100 bg-violet-50/30 flex flex-col xl:sticky xl:top-4 xl:self-start xl:max-h-[calc(100vh-7rem)] min-h-[320px]">
      <div className="px-3 py-2 border-b border-violet-100 flex items-center gap-1.5 text-sm font-medium text-violet-800">
        <Sparkles className="w-4 h-4" /> 让 AI 调整说明
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto scroll-hide p-3 space-y-2.5">
        {msgs.length === 0 && (
          <div className="text-xs text-ink-500 space-y-2">
            <p>用一句话说要怎么改，AI 会直接改好左边的说明并保存；不满意可以撤销。</p>
            <div className="flex flex-wrap gap-1.5">
              {QUICK.map((q) => <button key={q} onClick={() => send(q)} className="px-2 py-1 rounded-full ring-1 ring-violet-200 text-violet-700 bg-white hover:bg-violet-50">{q}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m) => m.role === 'user' ? (
          <div key={m.id} className="flex justify-end"><div className="max-w-[90%] bg-violet-600 text-white text-sm rounded-2xl rounded-tr-sm px-3 py-1.5">{m.text}</div></div>
        ) : (
          <div key={m.id} className="flex gap-1.5">
            <Bot className="w-4 h-4 text-violet-600 shrink-0 mt-1" />
            <div className={`max-w-[90%] text-sm rounded-2xl rounded-tl-sm px-3 py-1.5 ring-1 ${m.error ? 'bg-red-50 ring-red-100 text-red-700' : 'bg-white ring-violet-100 text-ink-800'}`}>
              {m.text}
              {m.prev && (m.undone
                ? <div className="text-xs text-ink-400 mt-1">已撤销</div>
                : <button onClick={() => undo(m)} className="mt-1 text-xs text-violet-700 inline-flex items-center gap-1 underline hover:no-underline"><Undo2 className="w-3 h-3" />撤销这次修改</button>)}
            </div>
          </div>
        ))}
        {busy && <div className="flex items-center gap-1.5 text-xs text-ink-500"><Loader2 className="w-3.5 h-3.5 animate-spin" />AI 正在修改…</div>}
      </div>
      <div className="p-2 border-t border-violet-100 flex gap-1.5 items-end">
        <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={2}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
          placeholder="例如：注意事项加一条「只对比同一张图的两个版本」"
          className="flex-1 resize-none border border-violet-200 rounded-xl px-2.5 py-1.5 text-sm bg-white focus:outline-none focus:border-violet-400" />
        <button onClick={() => send(input)} disabled={!input.trim() || busy} className="p-2 rounded-xl bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-40"><Send className="w-4 h-4" /></button>
      </div>
    </div>
  );
}
