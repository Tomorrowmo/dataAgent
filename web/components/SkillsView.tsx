'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Package, Upload, FolderOpen, Loader2, CheckCircle2, AlertTriangle, Trash2,
  Play, Download, BookOpen, ShieldAlert, FileText, ChevronRight, RefreshCw,
  Stethoscope, XCircle, Info, Sparkles,
} from 'lucide-react';
import {
  api, type Dataset, type SkillDetail, type SkillInstallReport, type SkillPack,
  type SkillRunResult, type SkillSuggestion, type SkillTool, type SkillVerdict,
} from '@/lib/api';
import Markdown from '@/components/Markdown';

const STAGE_ZH: Record<string, string> = {
  extract: '取包', manifest: '读清单', static_check: '静态检查', trust: '信任判定',
  smoke_test: '自检运行', install: '落盘安装', register: '登记', error: '出错',
};

// 技能包 = 用户自己写的方法(SKILL.md)+ 可执行的工具。这个页面要回答三件事:
// 装了什么、能不能信(安装报告每一步)、怎么用(文档 + 直接试跑一次)。
// 「验一下」是独立入口:网上下的包先体检,不写进系统也能知道能不能用。
export default function SkillsView() {
  const [packs, setPacks] = useState<SkillPack[]>([]);
  const [selSlug, setSelSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<'' | 'check' | 'install' | 'example'>('');
  const [report, setReport] = useState<SkillInstallReport | null>(null);
  const [reportTitle, setReportTitle] = useState('');
  const [installErr, setInstallErr] = useState('');
  const [dirPath, setDirPath] = useState('');
  const [allowCommand, setAllowCommand] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [specOpen, setSpecOpen] = useState(false);
  const [spec, setSpec] = useState('');
  const installRef = useRef<HTMLInputElement>(null);
  const checkRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async (keep?: string) => {
    const list = await api.listSkills().catch(() => [] as SkillPack[]);
    setPacks(list);
    setSelSlug((cur) => keep ?? (cur && list.some((p) => p.slug === cur) ? cur : list[0]?.slug ?? null));
  }, []);

  useEffect(() => {
    refresh();
    api.me().then((m) => setIsAdmin(!!m.is_admin)).catch(() => {});
  }, [refresh]);

  useEffect(() => {
    if (!selSlug) { setDetail(null); return; }
    setLoading(true);
    api.getSkill(selSlug).then(setDetail).catch(() => setDetail(null)).finally(() => setLoading(false));
  }, [selSlug]);

  async function run(kind: 'check' | 'install', opts: { file?: File; path?: string }) {
    const dryRun = kind === 'check';
    setBusy(kind); setInstallErr(''); setReport(null);
    setReportTitle(dryRun ? '体检结果(没有写入任何文件)' : '安装结果');
    try {
      const r = await api.installSkill({ ...opts, allowCommand, dryRun });
      setReport({ ...r.report, verified: r.skill?.is_verified ?? r.report.verified });
      if (!dryRun && r.skill) await refresh(r.skill.slug);
    } catch (e) {
      setInstallErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy('');
      if (installRef.current) installRef.current.value = '';
      if (checkRef.current) checkRef.current.value = '';
    }
  }

  async function installExample() {
    setBusy('example'); setInstallErr(''); setReport(null); setReportTitle('示例包安装结果');
    try {
      const r = await api.installSkillExample('battery-health');
      setReport(r.report);
      if (r.skill) await refresh(r.skill.slug);
    } catch (e) {
      setInstallErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(''); }
  }

  async function toggle(pack: SkillPack) {
    await api.setSkillEnabled(pack.slug, !pack.enabled).catch(() => {});
    await refresh(pack.slug);
  }

  async function remove(pack: SkillPack) {
    if (!confirm(`卸载技能包「${pack.name}」?包内文件会一起删除,此操作不可撤销。`)) return;
    await api.deleteSkill(pack.slug).catch(() => {});
    setSelSlug(null);
    await refresh();
  }

  async function downloadTemplate() {
    try {
      const { blob, filename } = await api.downloadSkillTemplate('battery-health');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  }

  async function openSpec() {
    setSpecOpen(true);
    if (!spec) {
      const r = await api.skillSpec().catch(() => null);
      setSpec(r?.content || '规范文档没找到。');
    }
  }

  return (
    <div className="flex h-full">
      {/* ── 左:已装的包 + 安装/体检 ─────────────────────────────────── */}
      <div className="w-full md:w-[300px] shrink-0 border-r border-ink-200 bg-ink-50/40 flex flex-col">
        <div className="p-3 border-b border-ink-200 space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Package className="w-4 h-4 text-brand-600" /> 技能包
            <button onClick={() => refresh()} title="刷新" className="ml-auto text-ink-400 hover:text-ink-700">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
          <p className="text-xs text-ink-500">装你自己的方法,AI 遇到对口的活会照着做。</p>
          <div className="flex gap-1.5">
            <button onClick={openSpec}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 flex items-center justify-center gap-1">
              <BookOpen className="w-3.5 h-3.5" /> 写法规范
            </button>
            <button onClick={downloadTemplate}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 flex items-center justify-center gap-1">
              <Download className="w-3.5 h-3.5" /> 下载模板
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-2 space-y-1.5">
          {packs.length === 0 && (
            <div className="text-xs text-ink-400 p-3 text-center">还没有装任何技能包。</div>
          )}
          {packs.map((p) => (
            <button key={p.slug} onClick={() => setSelSlug(p.slug)}
              className={`w-full text-left px-2.5 py-2 rounded-lg border transition ${
                selSlug === p.slug ? 'bg-white border-brand-300 shadow-sm' : 'border-transparent hover:bg-white/70'
              } ${p.enabled ? '' : 'opacity-60'}`}>
              <div className="flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${p.enabled ? 'bg-emerald-500' : 'bg-ink-300'}`} />
                <span className="text-sm font-medium truncate">{p.name}</span>
                {!p.is_verified && <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />}
              </div>
              <div className="text-[11px] text-ink-500 mt-0.5 line-clamp-2">{p.description}</div>
              <div className="text-[11px] text-ink-400 mt-1 flex gap-2 flex-wrap">
                <span>v{p.version}</span>
                <span>{p.tool_count > 0 ? `${p.tool_count} 个工具` : '纯知识'}</span>
                {p.trust === 'command' && <span className="text-amber-600">自带程序</span>}
                {p.trust === 'script' && <span className="text-ink-500">通用包</span>}
                {!p.enabled && <span className="text-ink-500 font-medium">已停用</span>}
              </div>
            </button>
          ))}
        </div>

        {/* 装包区:先体检、后安装 —— 网上下的包建议先体检 */}
        <div className="p-3 border-t border-ink-200 space-y-2 bg-white">
          <div className="text-xs font-medium text-ink-600">装一个包</div>
          <input ref={installRef} type="file" accept=".zip" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) run('install', { file: f }); }} />
          <input ref={checkRef} type="file" accept=".zip" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) run('check', { file: f }); }} />

          <div className="flex gap-1.5">
            <button onClick={() => checkRef.current?.click()} disabled={!!busy}
              title="只做体检,不写入任何文件"
              className="flex-1 text-xs px-2 py-2 rounded-lg border border-brand-300 text-brand-700 bg-brand-50 hover:bg-brand-100 disabled:opacity-50 flex items-center justify-center gap-1.5">
              {busy === 'check' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Stethoscope className="w-3.5 h-3.5" />}
              验一下 zip
            </button>
            <button onClick={() => installRef.current?.click()} disabled={!!busy}
              className="flex-1 text-xs px-2 py-2 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center justify-center gap-1.5">
              {busy === 'install' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              安装 zip
            </button>
          </div>

          <input value={dirPath} onChange={(e) => setDirPath(e.target.value)}
            placeholder="或填服务器上的目录路径(边改边装)"
            className="w-full text-xs px-2 py-1.5 rounded-lg border border-ink-200" />
          <div className="flex gap-1.5">
            <button onClick={() => dirPath.trim() && run('check', { path: dirPath.trim() })}
              disabled={!!busy || !dirPath.trim()}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 disabled:opacity-40 flex items-center justify-center gap-1">
              <Stethoscope className="w-3.5 h-3.5" /> 验目录
            </button>
            <button onClick={() => dirPath.trim() && run('install', { path: dirPath.trim() })}
              disabled={!!busy || !dirPath.trim()}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 disabled:opacity-40 flex items-center justify-center gap-1">
              <FolderOpen className="w-3.5 h-3.5" /> 装目录
            </button>
          </div>

          {isAdmin && (
            <label className="text-[11px] text-ink-500 flex items-center gap-1"
              title="包里自带可执行程序时才需要;这类包不受静态检查约束">
              <input type="checkbox" checked={allowCommand} onChange={(e) => setAllowCommand(e.target.checked)} />
              允许自带可执行程序
            </label>
          )}

          {installErr && (
            <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2 whitespace-pre-wrap max-h-48 overflow-auto">
              <div className="font-medium mb-1 flex items-center gap-1"><XCircle className="w-3.5 h-3.5" /> 装不了</div>
              {installErr}
            </div>
          )}
          {report && (
            <div className="space-y-2">
              {report.verdict && <VerdictCard verdict={report.verdict} title={reportTitle} />}
              <details className="text-[11px]">
                <summary className="cursor-pointer text-ink-500 hover:text-ink-700">看每一步的检查明细</summary>
                <div className="mt-1"><ReportPanel report={report} /></div>
              </details>
            </div>
          )}
        </div>
      </div>

      {/* ── 右:详情 / 新手引导 ───────────────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-auto">
        {loading && <div className="p-6 text-sm text-ink-400 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> 读取中…</div>}
        {!loading && !detail && <Onboarding onInstallExample={installExample} busy={busy === 'example'} onSpec={openSpec} onTemplate={downloadTemplate} />}
        {!loading && detail && (
          <SkillDetailPanel detail={detail} onToggle={() => toggle(detail)} onRemove={() => remove(detail)} />
        )}
      </div>

      {specOpen && (
        <div className="fixed inset-0 bg-black/40 z-50 grid place-items-center p-6" onClick={() => setSpecOpen(false)}>
          <div className="bg-white rounded-xl max-w-3xl w-full max-h-[85vh] overflow-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-3">
              <BookOpen className="w-4 h-4 text-brand-600" />
              <div className="font-medium">技能包接入规范</div>
              <button onClick={() => setSpecOpen(false)} className="ml-auto text-sm text-ink-500 hover:text-ink-800">关闭</button>
            </div>
            <div className="prose-tight skill-doc text-sm text-ink-800"><Markdown>{spec}</Markdown></div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── 结论卡:先回答"能不能用",再说要改什么 ───────────────────────────
function VerdictCard({ verdict: v, title }: { verdict: SkillVerdict; title: string }) {
  const good = v.installable && v.self_check_passed;
  // 颜色必须是静态类名 —— Tailwind 不会为拼接出来的 `bg-${x}-50` 生成样式。
  const TONE = {
    bad: { box: 'border-rose-200', bar: 'bg-rose-50 text-rose-700' },
    warn: { box: 'border-amber-200', bar: 'bg-amber-50 text-amber-700' },
    good: { box: 'border-emerald-200', bar: 'bg-emerald-50 text-emerald-700' },
  } as const;
  const tone = TONE[!v.installable ? 'bad' : good ? 'good' : 'warn'];
  const headline = !v.installable ? '这个包装不了'
    : good ? '可以用' : '能装,但有没通过的项';
  return (
    <div className={`text-[11px] border rounded-lg overflow-hidden ${tone.box}`}>
      <div className={`px-2 py-1.5 font-medium ${tone.bar} flex items-center gap-1.5`}>
        {!v.installable ? <XCircle className="w-3.5 h-3.5" />
          : good ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
        {headline}
        <span className="ml-auto font-normal text-ink-500">{title}</span>
      </div>
      <div className="p-2 space-y-1.5 bg-white">
        <div className="flex gap-1.5">
          <Info className="w-3 h-3 mt-0.5 text-ink-400 shrink-0" />
          <div>
            <b>AI 能拿到:</b>{v.gives}
            {v.doc_chars > 0 && <>(说明书 {v.doc_chars} 字)</>}
            {v.tools_total > 0 && <>;工具 {v.tools_ok.length}/{v.tools_total} 项自检通过</>}
          </div>
        </div>
        {v.tools_failed.length > 0 && (
          <div className="text-rose-700">没通过的工具:{v.tools_failed.join('、')}</div>
        )}
        {v.command_tools.length > 0 && (
          <div className="text-amber-700 flex gap-1"><ShieldAlert className="w-3 h-3 mt-0.5 shrink-0" />
            自带可执行程序:{v.command_tools.join('、')} —— 需管理员放行,且不受静态检查约束。</div>
        )}
        {v.blockers.length > 0 && (
          <div className="text-rose-700">
            <div className="font-medium">拦住它的原因:</div>
            {v.blockers.map((b, i) => <div key={i}>· {b}</div>)}
          </div>
        )}
        {v.fixes.length > 0 && (
          <div className="text-ink-600">
            <div className="font-medium">建议改这些:</div>
            {v.fixes.map((f, i) => <div key={i}>· {f}</div>)}
          </div>
        )}
        {v.warnings.length > 0 && (
          <details>
            <summary className="cursor-pointer text-ink-500">其他提醒 ({v.warnings.length})</summary>
            {v.warnings.map((w, i) => <div key={i} className="text-ink-500">· {w}</div>)}
          </details>
        )}
      </div>
    </div>
  );
}

// ── 新手引导:三步 + 一键装示例 ──────────────────────────────────────
function Onboarding({ onInstallExample, busy, onSpec, onTemplate }: {
  onInstallExample: () => void; busy: boolean; onSpec: () => void; onTemplate: () => void;
}) {
  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6">
      <div className="text-center space-y-2">
        <Package className="w-10 h-10 text-ink-300 mx-auto" />
        <h2 className="text-lg font-semibold">把你自己的做法装进来</h2>
        <p className="text-sm text-ink-500">
          内置算法只是一个函数。技能包装的是<b>一整套做法</b>:什么数据才够判、按什么顺序做、
          用什么判据下结论 —— AI 遇到对口的活会先读它,再照着做。
        </p>
      </div>

      <button onClick={onInstallExample} disabled={busy}
        className="w-full px-4 py-3 rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center justify-center gap-2">
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        先装一个示例包看看效果(电池循环健康度评估)
      </button>

      <ol className="space-y-3 text-sm">
        {[
          ['照着模板改', <>点左边「下载模板」拿到示例包,改 <code>SKILL.md</code>:第一段写清<b>什么时候用它</b>,正文写你判断的顺序和判据。</>],
          ['声明工具(可选)', <>要算东西就在 <code>skill.yaml</code> 里声明工具,入口写 <code>模块:函数</code>,函数签名是 <code>run(df, **params)</code>。只写知识不写工具也完全可以。</>],
          ['先验后装', <>把目录路径填到左边点「验目录」——不写入任何文件,直接告诉你能不能用、AI 会拿到什么、要改什么。确认没问题再点「装目录」。</>],
          ['回对话里用', <>装完在聊天里正常提问即可。AI 命中场景会自动 <code>read_skill</code> 读你的说明书,然后按它做,不需要你每次交代。</>],
        ].map(([title, body], i) => (
          <li key={i} className="flex gap-3">
            <span className="w-6 h-6 shrink-0 rounded-full bg-ink-100 text-ink-600 grid place-items-center text-xs font-medium">{i + 1}</span>
            <div><b>{title as string}</b><div className="text-ink-600 mt-0.5">{body}</div></div>
          </li>
        ))}
      </ol>

      <div className="text-xs text-ink-500 bg-ink-50 rounded-xl p-3 space-y-1.5">
        <div className="font-medium text-ink-700">网上下的包能直接用吗?</div>
        <div>
          能装,但要看它是什么:Claude Code / 各类 agent 那种<b>纯 SKILL.md 的知识包</b>基本可以直接装,
          装进来就是给 AI 的一份方法说明;<b>要能算东西</b>,得有 <code>skill.yaml</code> 声明工具 —— 别人的包
          多半没有,需要你补上几行。
        </div>
        <div>
          安全上:python 工具在沙箱子进程里跑(禁联网、禁起子进程、禁删文件),包里用不上的脚本只会提醒不会执行;
          <b>自带可执行程序的包不受这些约束</b>,来源不明就别开那个开关。拿不准时先点「验一下」——它不写入任何文件。
        </div>
        <div className="flex gap-3 pt-1">
          <button onClick={onSpec} className="text-brand-600 hover:underline">读写法规范</button>
          <button onClick={onTemplate} className="text-brand-600 hover:underline">下载模板包</button>
        </div>
      </div>
    </div>
  );
}

// ── 安装报告:每一步都摊开,失败在哪一眼看到 ──────────────────────────
function ReportPanel({ report }: { report: SkillInstallReport }) {
  return (
    <div className="text-[11px] border border-ink-200 rounded-lg overflow-hidden">
      <div className={`px-2 py-1 font-medium ${report.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
        {report.ok ? '检查全部通过' : '检查有未通过项'} · {report.duration_s}s
      </div>
      <div className="divide-y divide-ink-100 max-h-60 overflow-auto">
        {report.stages.map((s, i) => (
          <div key={i} className="px-2 py-1 flex gap-1.5">
            {s.ok ? <CheckCircle2 className="w-3 h-3 text-emerald-500 mt-0.5 shrink-0" />
                  : <AlertTriangle className="w-3 h-3 text-rose-500 mt-0.5 shrink-0" />}
            <div className="min-w-0">
              <span className="text-ink-700">{STAGE_ZH[s.stage] ?? s.stage}</span>
              <span className="text-ink-500"> — {s.detail}</span>
            </div>
          </div>
        ))}
        {report.warnings.map((w, i) => (
          <div key={`w${i}`} className="px-2 py-1 text-amber-700 bg-amber-50">提醒:{w}</div>
        ))}
      </div>
    </div>
  );
}

// ── 详情:文档 / 工具(可直接试跑)/ 安装报告 / 文件 ────────────────────
function SkillDetailPanel({ detail, onToggle, onRemove }: {
  detail: SkillDetail; onToggle: () => void; onRemove: () => void;
}) {
  const [tab, setTab] = useState<'doc' | 'tools' | 'report' | 'files'>('doc');
  const [descOpen, setDescOpen] = useState(false);
  const [refFile, setRefFile] = useState<string | null>(null);
  const [refText, setRefText] = useState('');

  useEffect(() => { setTab('doc'); setRefFile(null); setDescOpen(false); }, [detail.slug]);

  async function openRef(f: string) {
    setRefFile(f);
    const r = await api.skillDoc(detail.slug, f).catch(() => null);
    setRefText(r?.content || r?.error || '');
  }

  const refs = detail.doc.references ?? [];

  const sameText = (a: string, b: string) => a.trim().replace(/\s+/g, '') === b.trim().replace(/\s+/g, '');
  const showWhen = detail.when_to_use && !sameText(detail.when_to_use, detail.description);
  const verdict = detail.install_report?.verdict;
  // 体检结论只在"有问题"时占版面;一切正常时它只是重复状态行,反而稀释重点。
  const verdictNeedsAttention = !!verdict && (!verdict.installable || !verdict.self_check_passed
    || (verdict.tools_failed?.length ?? 0) > 0);

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      {/* ① 标题行 —— 名字 + 状态,一眼看到底是什么、AI 用不用它 */}
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-xl font-semibold">{detail.name}</h2>
            <span className="text-xs text-ink-400">v{detail.version} · {detail.slug}</span>
          </div>
          <p className={`text-sm text-ink-600 mt-1.5 ${descOpen ? '' : 'line-clamp-2'}`}>
            {detail.description}
          </p>
          {detail.description.length > 110 && (
            <button onClick={() => setDescOpen((v) => !v)} className="text-[11px] text-brand-600 hover:underline">
              {descOpen ? '收起' : '展开完整描述'}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onToggle}
            title={detail.enabled
              ? 'AI 在对话里看得到这个包,命中场景会主动用它。点一下停用。'
              : 'AI 在对话里完全看不到它(包还在,仍可手动试跑)。点一下启用。'}
            className={`text-xs px-2.5 py-1.5 rounded-lg border font-medium transition ${
              detail.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                             : 'border-ink-300 bg-ink-100 text-ink-600 hover:bg-ink-200'}`}>
            {detail.enabled ? '✓ AI 会用它' : '已停用'}
          </button>
          <button onClick={onRemove} title="卸载" className="p-1.5 rounded-lg text-ink-400 hover:text-rose-600 hover:bg-rose-50">
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ② 一行状态 —— 三个只读指示灯,点开才展开细节 */}
      <StateChips detail={detail} />

      {/* ③ 什么时候用 + 触发词 —— 折叠起来,需要时才看 */}
      {(showWhen || detail.triggers.length > 0) && (
        <details className="text-xs text-ink-600 bg-ink-50 rounded-lg px-3 py-2">
          <summary className="cursor-pointer text-ink-500 select-none">
            AI 什么时候会选中它{detail.triggers.length > 0 ? `(${detail.triggers.length} 个触发词)` : ''}
          </summary>
          {showWhen && <p className="mt-1.5 leading-relaxed">{detail.when_to_use}</p>}
          {detail.triggers.length > 0 && (
            <div className="flex gap-1 flex-wrap mt-2">
              {detail.triggers.map((t) => (
                <span key={t} className="px-1.5 py-0.5 rounded bg-white border border-ink-200 text-ink-600">{t}</span>
              ))}
            </div>
          )}
        </details>
      )}

      {/* ④ 只有出问题时,体检结论才抢版面 */}
      {verdictNeedsAttention && verdict && (
        <VerdictCard verdict={verdict} title="安装时的体检结论" />
      )}

      <div className="flex gap-1 border-b border-ink-200">
        {([['doc', '说明书'], ['tools', `工具 (${detail.tools.length})`], ['report', '安装报告'], ['files', `文件 (${detail.files.length})`]] as const).map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-3 py-1.5 text-sm -mb-px border-b-2 ${tab === id ? 'border-brand-600 text-brand-700' : 'border-transparent text-ink-500 hover:text-ink-800'}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'doc' && (
        <div className="space-y-3">
          <div className="prose-tight skill-doc text-sm text-ink-800">
            <Markdown>{detail.doc.content || '(这个包没有正文)'}</Markdown>
          </div>
          {refs.length > 0 && (
            <div className="border-t border-ink-100 pt-3">
              <div className="text-xs font-medium text-ink-600 mb-1.5 flex items-center gap-1">
                <FileText className="w-3.5 h-3.5" /> 参考资料(AI 按需读取)
              </div>
              <div className="space-y-1">
                {refs.map((f) => (
                  <button key={f} onClick={() => openRef(f)}
                    className="text-xs text-brand-600 hover:underline flex items-center gap-1">
                    <ChevronRight className="w-3 h-3" /> {f}
                  </button>
                ))}
              </div>
              {refFile && (
                <div className="mt-2 p-3 bg-ink-50 rounded-lg">
                  <div className="text-[11px] text-ink-500 mb-1">{refFile}</div>
                  <div className="prose-tight skill-doc text-sm text-ink-800"><Markdown>{refText}</Markdown></div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'tools' && (
        <div className="space-y-3">
          {!detail.enabled && (
            <div className="text-xs text-ink-600 bg-ink-100 border border-ink-200 rounded-lg p-2.5">
              这个包<b>已停用</b>:AI 在对话里看不到它,也不会主动用它。下面的「试跑一次」是你手动
              触发的,照常能跑 —— 想让 AI 用它,把右上角的「已停用」勾成「启用中」。
            </div>
          )}
          {detail.tools.length === 0 && (
            <div className="text-sm text-ink-500 bg-ink-50 rounded-lg p-3">
              这个包只有知识,没有可执行的工具 —— AI 会读它的说明书,但算东西还得用内置算法。
              想让它能算,在包里加一个 <code>skill.yaml</code> 声明工具即可(见「写法规范」第 3 节)。
            </div>
          )}
          {detail.tools.map((t) => <ToolCard key={t.slug} pack={detail} tool={t} />)}
        </div>
      )}

      {tab === 'report' && (
        <div className="space-y-3">
          {detail.install_report?.verdict && (
            <VerdictCard verdict={detail.install_report.verdict} title="安装时的体检结论" />
          )}
          <ReportPanel report={detail.install_report} />
        </div>
      )}

      {tab === 'files' && (
        <div className="text-xs font-mono text-ink-600 space-y-0.5">
          <div className="text-ink-400 mb-1">{detail.root}</div>
          {detail.files.map((f) => <div key={f}>{f}</div>)}
        </div>
      )}
    </div>
  );
}


// 一个技能包同时有三种互不相干的状态。之前排成三行,和标题、描述、体检卡一起
// 五块并列 —— 每块都在喊,等于都没喊。现在压成一行小 chip,点开才展开解释。
function StateChips({ detail }: { detail: SkillDetail }) {
  const [open, setOpen] = useState(false);
  const needsGate = detail.trust === 'script' || detail.trust === 'command';
  const chips = [
    { key: 'enabled', ok: detail.enabled, label: detail.enabled ? 'AI 会用它' : 'AI 看不到它',
      detail: detail.enabled
        ? '命中它的适用场景时,AI 先读它的说明书再照着做。'
        : '已停用:AI 在对话里完全看不到这个包。包还在,「工具」页仍可手动试跑,随时能点回来。' },
    { key: 'verified', ok: detail.is_verified, label: detail.is_verified ? '自检通过' : '自检未过',
      detail: detail.is_verified
        ? '装的时候:工具能导入,作者声明的测试也跑过了。'
        : '装的时候没全过 —— 工具可能跑不通。AI 会被告知这一点,失败时应如实说明。' },
    ...(needsGate ? [{
      key: 'gate', ok: null as boolean | null,
      label: detail.trust === 'command' ? '自带程序需授权' : '包内脚本需授权',
      detail: '真的执行脚本/程序需要服务端开启 SKILLS_ALLOW_COMMAND_RUNTIME;不开也不影响 AI 读它的知识。',
    }] : []),
    { key: 'content', ok: null as boolean | null,
      label: `说明书 ${detail.doc_chars} 字 · ${detail.tools.length > 0 ? `${detail.tools.length} 个工具` : '纯知识'}`,
      detail: 'AI 平时只看到这个包的一句话描述;命中场景才会把说明书正文读进去。' },
  ];
  return (
    <div className="text-xs">
      <div className="flex items-center gap-1.5 flex-wrap">
        {chips.map((c) => (
          <span key={c.key}
            className={`px-2 py-0.5 rounded-full border flex items-center gap-1 ${
              c.ok === null ? 'border-ink-200 bg-ink-50 text-ink-600'
                : c.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
            {c.ok === null ? <Info className="w-3 h-3" />
              : c.ok ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
            {c.label}
          </span>
        ))}
        <button onClick={() => setOpen((v) => !v)} className="text-ink-400 hover:text-ink-600 ml-0.5">
          {open ? '收起说明' : '这些是什么意思?'}
        </button>
      </div>
      {open && (
        <div className="mt-2 border border-ink-200 rounded-lg divide-y divide-ink-100">
          {chips.map((c) => (
            <div key={c.key} className="flex gap-2 px-2.5 py-1.5">
              <span className="w-28 shrink-0 text-ink-500">{c.label}</span>
              <span className="text-ink-600">{c.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// 「告诉系统哪一列是它」—— 一次纠正 → 一条映射规则 → 以后任何技能包、任何数据集
// 遇到同名列都自动认。规则默认共享(is_public),所以是一个人教、全员受益。
function TeachMapping({ items, columns, onTaught }: {
  items: { param: string; role: string; wanted: string; label: string }[];
  columns: string[];
  onTaught: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState('');

  async function teach() {
    const chosen = Object.entries(picks).filter(([, v]) => v);
    if (chosen.length === 0) return;
    setBusy(true);
    try {
      for (const [role, col] of chosen) {
        const it = items.find((x) => x.role === role);
        await api.teachColumnMapping({
          pattern: col, role,
          label: it?.wanted || role,
          note: `在「${col}」上教过:它就是 ${it?.wanted || role}`,
        });
      }
      setDone(`记住了 ${chosen.length} 条。以后任何技能包遇到同名列都会自动认出来。`);
      setPicks({});
      onTaught();
    } catch (e) {
      setDone(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="text-[11px] border border-brand-200 bg-brand-50 rounded-lg px-2 py-1.5">
      <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 text-brand-700">
        <BookOpen className="w-3.5 h-3.5" />
        猜不出来?告诉它哪一列是什么 —— 教一次,以后都认
      </button>
      {open && (
        <div className="mt-1.5 space-y-1.5">
          {items.map((it) => (
            <label key={it.role} className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-ink-600" title={it.label}>
                「{it.wanted}」是哪一列
              </span>
              <select
                value={picks[it.role] ?? ''}
                onChange={(e) => setPicks((p) => ({ ...p, [it.role]: e.target.value }))}
                className="flex-1 min-w-0 border border-ink-200 rounded px-2 py-1 bg-white">
                <option value="">(这份数据里没有)</option>
                {columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          ))}
          <div className="flex items-center gap-2">
            <button onClick={teach} disabled={busy}
              className="text-[11px] px-2 py-1 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
              {busy ? '记录中…' : '记住这个对应关系'}
            </button>
            {done && <span className="text-ink-600">{done}</span>}
          </div>
          <p className="text-ink-500">
            只在这份数据真的<b>含有那个量</b>时才教它。它确实没有(比如质量过程数据里没有循环号),
            换一份数据才是对的 —— 硬指一个列会让结论从根上错。
          </p>
        </div>
      )}
    </div>
  );
}

// 一个工具:参数表 + 直接试跑。装完能当场跑一次,是"这包到底能不能用"最短的验证路径。
// 关键一条:选完数据集就按**这份数据真实的列名**把参数填好 —— 工具的默认值写的是作者
// 那份数据的列名,让用户自己去猜,等于把作者的私有约定摊派给了用户。挑不出来时如实说
// "这份数据不适合这个工具",绝不填一个能跑但没意义的值。
function ToolCard({ pack, tool }: { pack: SkillPack; tool: SkillTool }) {
  const [open, setOpen] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dsId, setDsId] = useState<number | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [sugg, setSugg] = useState<SkillSuggestion | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SkillRunResult | null>(null);
  const [showLogs, setShowLogs] = useState(false);

  const schema = tool.params_schema ?? {};
  const toolName = tool.slug.split('.').slice(1).join('.');

  useEffect(() => {
    if (open && datasets.length === 0) {
      api.listDatasets().then((ds) => { setDatasets(ds); setDsId((c) => c ?? ds[0]?.id ?? null); }).catch(() => {});
    }
  }, [open, datasets.length]);

  // 面板一打开、或换了数据集 → 立刻按真实列名重算推荐值(确定性,不花钱、不等 LLM)
  const applySuggestion = useCallback(async (id: number | null) => {
    setSuggesting(true);
    try {
      const sg = await api.suggestSkillParams(pack.slug, toolName, id);
      setSugg(sg);
      setValues(Object.fromEntries(
        Object.entries(sg.params).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : String(v ?? '')]),
      ));
    } catch { setSugg(null); } finally { setSuggesting(false); }
  }, [pack.slug, toolName]);

  useEffect(() => {
    if (open) applySuggestion(tool.needs_data ? dsId : null);
  }, [open, dsId, tool.needs_data, applySuggestion]);

  async function run() {
    setBusy(true); setRes(null); setShowLogs(false);
    const params: Record<string, unknown> = {};
    for (const [k, spec] of Object.entries(schema)) {
      const raw = values[k];
      if (raw === undefined || raw === '') continue;
      params[k] = spec.type === 'integer' ? parseInt(raw, 10)
        : spec.type === 'number' ? parseFloat(raw)
        : spec.type === 'boolean' ? raw === 'true'
        : spec.type === 'array' ? raw.split(',').map((x) => x.trim()).filter(Boolean)
        : raw;
    }
    try {
      setRes(await api.runSkillTool(pack.slug, toolName, { dataset_id: tool.needs_data ? dsId : null, params }));
    } catch (e) {
      setRes({ status: 'error', error: e instanceof Error ? e.message : String(e),
               duration_ms: 0, summary: {}, logs: '', result_rows: 0 });
    } finally { setBusy(false); }
  }

  const fitTone = sugg?.fit === 'mismatch' ? 'bg-rose-50 text-rose-700 border-rose-200'
    : sugg?.fit === 'partial' ? 'bg-amber-50 text-amber-700 border-amber-200'
    : 'bg-emerald-50 text-emerald-700 border-emerald-200';

  return (
    <div className="border border-ink-200 rounded-xl overflow-hidden">
      <button onClick={() => setOpen((o) => !o)} className="w-full text-left px-3 py-2 hover:bg-ink-50">
        <div className="flex items-center gap-2">
          <code className="text-xs bg-ink-100 px-1.5 py-0.5 rounded">{tool.slug}</code>
          <span className="text-sm">{tool.name}</span>
          {tool.runtime === 'command' && <span className="text-[11px] text-amber-600">自带程序</span>}
          <span className="ml-auto text-[11px] text-ink-400">{tool.returns}</span>
        </div>
        <div className="text-xs text-ink-500 mt-0.5">{tool.description}</div>
      </button>
      {open && (
        <div className="border-t border-ink-100 p-3 space-y-2 bg-ink-50/50">
          {tool.needs_data && (
            <label className="text-xs flex items-center gap-2">
              <span className="shrink-0">数据集</span>
              <select value={dsId ?? ''} onChange={(e) => setDsId(Number(e.target.value))}
                className="flex-1 min-w-0 text-xs border border-ink-200 rounded px-2 py-1 bg-white">
                {datasets.map((d) => (
                  <option key={d.id} value={d.id} title={d.name}>
                    {d.name.length > 48 ? `${d.name.slice(0, 48)}…` : d.name}
                    {d.rows ? ` (${d.rows} 行)` : ''}
                  </option>
                ))}
              </select>
              {suggesting && <Loader2 className="w-3.5 h-3.5 animate-spin text-ink-400 shrink-0" />}
            </label>
          )}

          {sugg && Object.keys(schema).length > 0 && (
            <div className={`text-[11px] border rounded-lg px-2 py-1.5 ${fitTone}`}>
              <div className="flex items-start gap-1.5">
                {sugg.fit === 'mismatch' ? <XCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  : sugg.fit === 'partial' ? <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  : <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
                <div>
                  {sugg.note}
                  {sugg.missing.length > 0 && <div className="mt-0.5">没对上的:{sugg.missing.join(';')}</div>}
                </div>
              </div>
            </div>
          )}

          {/* 猜不出来不是终点:指一次,系统就记住"这列是什么量",以后任何包都认。
              这是把用户的一次纠正沉淀成可复用知识的入口 —— 也是唯一真正解决
              "同一个量、名字千奇百怪"的层。 */}
          {sugg && sugg.teachable?.length > 0 && sugg.columns.length > 0 && (
            <TeachMapping
              items={sugg.teachable}
              columns={sugg.columns}
              onTaught={() => applySuggestion(tool.needs_data ? dsId : null)}
            />
          )}

          {Object.entries(schema).map(([k, spec]) => {
            const opts = sugg?.options?.[k];
            const why = sugg?.explanations?.[k];
            return (
              <label key={k} className="text-xs flex items-start gap-2">
                <span className="w-32 shrink-0 truncate pt-1" title={spec.description}>
                  {k}{spec.required ? ' *' : ''}
                </span>
                <span className="flex-1 min-w-0">
                  {Array.isArray(spec.enum) && spec.enum.length > 0 ? (
                    // 工具自己声明了取值范围(通用包的 run_script 就靠这个列出包内脚本)
                    <select value={values[k] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                      className="w-full border border-ink-200 rounded px-2 py-1 bg-white">
                      <option value="">(不填)</option>
                      {spec.enum.map((c) => <option key={String(c)} value={String(c)}>{String(c)}</option>)}
                    </select>
                  ) : opts && opts.length > 0 ? (
                    // 选列的参数直接给这份数据的真实列名,不让用户手打
                    <select value={values[k] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                      className="w-full border border-ink-200 rounded px-2 py-1 bg-white">
                      <option value="">(不填)</option>
                      {opts.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  ) : (
                    <input
                      value={values[k] ?? (spec.default !== undefined ? String(spec.default) : '')}
                      onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                      placeholder={spec.description || spec.type}
                      className="w-full border border-ink-200 rounded px-2 py-1 bg-white"
                    />
                  )}
                  {why && <span className="block text-[10px] text-ink-400 mt-0.5">{why}</span>}
                </span>
              </label>
            );
          })}

          <div className="flex items-center gap-2">
            <button onClick={run} disabled={busy}
              className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1.5">
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} 试跑一次
            </button>
            {sugg && (
              <button onClick={() => applySuggestion(tool.needs_data ? dsId : null)}
                className="text-[11px] text-brand-600 hover:underline">按这份数据重新推荐</button>
            )}
          </div>

          {res && (
            <div className={`text-[11px] rounded-lg p-2 border ${res.status === 'ok' ? 'bg-emerald-50 border-emerald-200' : 'bg-rose-50 border-rose-200'}`}>
              <div className="font-medium mb-1">
                {res.status === 'ok' ? `成功 · ${res.duration_ms}ms` : '失败'}
              </div>
              <pre className="whitespace-pre-wrap max-h-56 overflow-auto">
                {res.status === 'ok' ? JSON.stringify(res.summary, null, 2) : res.error}
              </pre>
              {res.warning && <div className="mt-1 text-ink-600">{res.warning}</div>}
              {res.status === 'error' && res.hint && <div className="mt-1 text-ink-600">{res.hint}</div>}
              {res.status === 'error' && res.logs && (
                <button onClick={() => setShowLogs((v) => !v)} className="mt-1 text-ink-500 hover:underline">
                  {showLogs ? '收起技术细节' : '看技术细节(traceback)'}
                </button>
              )}
              {showLogs && res.logs && (
                <pre className="mt-1 whitespace-pre-wrap max-h-56 overflow-auto text-ink-500">{res.logs}</pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
