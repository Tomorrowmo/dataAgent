# -*- coding: utf-8 -*-
"""Generate the RLab Cortex product USER MANUAL (.docx) — a practical,
operation-oriented guide (login → upload → analyze → chart → extend), distinct
from the positioning-oriented white paper. Grounded in the real product.

Run:  python tools/gen_user_manual.py
"""
import os
from io import BytesIO
from PIL import Image as _PILImage
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "docs", "pitch", "assets")
OUT = os.path.join(ROOT, "docs", "pitch", "RLab_Cortex_产品使用手册.docx")

INK    = RGBColor(0x12, 0x1B, 0x2A)
MUTED  = RGBColor(0x55, 0x64, 0x74)
FAINT  = RGBColor(0x8A, 0x98, 0xA6)
ACCENT = RGBColor(0x03, 0x69, 0xA1)
VERITY = RGBColor(0x6D, 0x35, 0xD6)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
GREEN  = RGBColor(0x15, 0x80, 0x3D)

H_ACCENT, H_VERITY = "0369A1", "6D35D6"
H_LIGHT, H_PLIGHT, H_ROW, H_LINE, H_GREENL = "EAF2F8", "F1ECFB", "F4F8FB", "D9E4EC", "EAF6EE"
BODY_FONT = "微软雅黑"

doc = Document()
normal = doc.styles['Normal']
normal.font.name = BODY_FONT; normal.font.size = Pt(10.5); normal.font.color.rgb = INK
rpr = normal.element.get_or_add_rPr()
rfonts = rpr.find(qn('w:rFonts'))
if rfonts is None:
    rfonts = OxmlElement('w:rFonts'); rpr.append(rfonts)
for a in ('w:eastAsia', 'w:ascii', 'w:hAnsi'):
    rfonts.set(qn(a), BODY_FONT)
normal.paragraph_format.line_spacing = 1.5
for sec in doc.sections:
    sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.0); sec.left_margin = Cm(2.4); sec.right_margin = Cm(2.4)


def _ea(r, name=BODY_FONT):
    r.font.name = name
    rPr = r._element.get_or_add_rPr()
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts'); rPr.append(rf)
    for a in ('w:eastAsia', 'w:ascii', 'w:hAnsi'):
        rf.set(qn(a), name)

def _shade(cell, hexfill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hexfill)
    tcPr.append(shd)

def _cell_margins(cell, top=60, bottom=60, left=110, right=110):
    tcPr = cell._tc.get_or_add_tcPr(); m = OxmlElement('w:tcMar')
    for tag, val in (('top', top), ('bottom', bottom), ('start', left), ('end', right)):
        e = OxmlElement('w:' + tag); e.set(qn('w:w'), str(val)); e.set(qn('w:type'), 'dxa'); m.append(e)
    tcPr.append(m)

def _borders(table, color=H_LINE, sz=4):
    b = OxmlElement('w:tblBorders')
    for edge in ('top', 'bottom', 'left', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + edge); e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), str(sz)); e.set(qn('w:space'), '0'); e.set(qn('w:color'), color); b.append(e)
    table._tbl.tblPr.append(b)

def _no_borders(table):
    b = OxmlElement('w:tblBorders')
    for edge in ('top', 'bottom', 'left', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + edge); e.set(qn('w:val'), 'none'); b.append(e)
    table._tbl.tblPr.append(b)

def _widths(table, ws):
    table.autofit = False; table.allow_autofit = False
    for row in table.rows:
        for i, w in enumerate(ws):
            row.cells[i].width = Inches(w)

def _hrule(par, color=H_LINE, sz=8):
    pPr = par._p.get_or_add_pPr(); pbdr = OxmlElement('w:pBdr'); bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single'); bottom.set(qn('w:sz'), str(sz)); bottom.set(qn('w:space'), '4'); bottom.set(qn('w:color'), color)
    pbdr.append(bottom); pPr.append(pbdr)

def run(par, text, size=10.5, color=INK, bold=False, italic=False, font=BODY_FONT):
    r = par.add_run(text); r.font.size = Pt(size); r.font.color.rgb = color; r.bold = bold; r.italic = italic; _ea(r, font); return r

def para(text="", size=10.5, color=INK, bold=False, align=None, after=7, before=0, indent=True):
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(after); p.paragraph_format.space_before = Pt(before); p.paragraph_format.line_spacing = 1.5
    if align is not None:
        p.alignment = align
    if text:
        run(p, text, size=size, color=color, bold=bold)
    if indent and align is None:
        pPr = p._p.get_or_add_pPr(); ind = pPr.find(qn('w:ind'))
        if ind is None:
            ind = OxmlElement('w:ind'); pPr.append(ind)
        ind.set(qn('w:firstLineChars'), '200'); ind.set(qn('w:firstLine'), '420')
    return p

def h1(num, text, color=VERITY):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(18); p.paragraph_format.space_after = Pt(2); p.paragraph_format.keep_with_next = True
    p.style = doc.styles['Heading 1']
    r = p.add_run(f"{num}　{text}"); r.font.size = Pt(16); r.bold = True; r.font.color.rgb = color; _ea(r)
    _hrule(p, color=H_VERITY if color == VERITY else H_ACCENT, sz=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)

def h2(text, color=ACCENT):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(11); p.paragraph_format.space_after = Pt(3); p.paragraph_format.keep_with_next = True
    p.style = doc.styles['Heading 2']
    r = p.add_run(text); r.font.size = Pt(12); r.bold = True; r.font.color.rgb = color; _ea(r)

def bullets(items, after=4, lead=ACCENT):
    for it in items:
        p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(after); p.paragraph_format.left_indent = Cm(0.6); p.paragraph_format.first_line_indent = Cm(-0.35); p.paragraph_format.line_spacing = 1.45
        run(p, "▪ ", size=10.5, color=lead, bold=True)
        if isinstance(it, tuple):
            run(p, it[0], bold=True); run(p, it[1])
        else:
            run(p, it)

def steps(items, after=4):
    for i, it in enumerate(items, 1):
        p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(after); p.paragraph_format.left_indent = Cm(0.8); p.paragraph_format.first_line_indent = Cm(-0.8); p.paragraph_format.line_spacing = 1.45
        bx = run(p, f" {i} ", size=9, color=WHITE, bold=True)
        # number badge via highlight-ish: just colored brackets
        p.runs[0].text = f"{i}. "
        run(p, "", )
        if isinstance(it, tuple):
            run(p, it[0], bold=True); run(p, it[1])
        else:
            run(p, it)
        p.runs[0].font.color.rgb = ACCENT; p.runs[0].bold = True

_fig = [0]; _tab = [0]
def _seq(par, name, n, color=FAINT):
    r = par.add_run(); rr = r._r
    for tag, attr, val in (('w:fldChar', 'w:fldCharType', 'begin'),):
        e = OxmlElement(tag); e.set(qn(attr), val); rr.append(e)
    it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve'); it.text = f' SEQ {name} \\* ARABIC '; rr.append(it)
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'separate'); rr.append(e)
    t = OxmlElement('w:t'); t.text = str(n); rr.append(t)
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); rr.append(e)
    r.font.size = Pt(8.5); r.font.color.rgb = color; r.bold = True; _ea(r)

def figcap(text):
    _fig[0] += 1
    cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER; cap.paragraph_format.space_after = Pt(11); cap.paragraph_format.space_before = Pt(2)
    run(cap, "图 ", size=8.5, color=FAINT, bold=True); _seq(cap, "Figure", _fig[0]); run(cap, "　" + text, size=8.5, color=FAINT, italic=True)

def tabcap(text):
    _tab[0] += 1
    cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER; cap.paragraph_format.space_before = Pt(8); cap.paragraph_format.space_after = Pt(3); cap.paragraph_format.keep_with_next = True
    run(cap, "表 ", size=8.5, color=MUTED, bold=True); _seq(cap, "Table", _tab[0], color=MUTED); run(cap, "　" + text, size=8.5, color=MUTED, bold=True)

def table(headers, rows, widths=None, accent=H_ACCENT, first_col_bold=True, fs=9.5, cap=None):
    if cap:
        tabcap(cap)
    t = doc.add_table(rows=1, cols=len(headers)); t.alignment = WD_TABLE_ALIGNMENT.CENTER; _borders(t)
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]; _shade(c, accent); _cell_margins(c); c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        pp = c.paragraphs[0]; pp.paragraph_format.space_after = Pt(0); run(pp, h, size=fs + .5, color=WHITE, bold=True)
    for ri, rv in enumerate(rows):
        cells = t.add_row().cells
        for ci, v in enumerate(rv):
            c = cells[ci]; _cell_margins(c); c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if ri % 2 == 1:
                _shade(c, H_ROW)
            pp = c.paragraphs[0]; pp.paragraph_format.space_after = Pt(0); pp.paragraph_format.line_spacing = 1.3
            run(pp, str(v), size=fs, bold=(first_col_bold and ci == 0))
    if widths:
        _widths(t, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def callout(title, body, fill=H_LIGHT, bar=H_ACCENT, tcolor=ACCENT):
    t = doc.add_table(rows=1, cols=2); _no_borders(t); t.alignment = WD_TABLE_ALIGNMENT.CENTER; _widths(t, [0.10, 6.3])
    bc, body_c = t.rows[0].cells; _shade(bc, bar); _shade(body_c, fill); _cell_margins(body_c, top=110, bottom=110, left=200, right=160)
    p = body_c.paragraphs[0]; p.paragraph_format.space_after = Pt(3)
    if title:
        run(p, title, color=tcolor, bold=True)
    if body:
        bp = body_c.add_paragraph(); bp.paragraph_format.space_after = Pt(0); bp.paragraph_format.line_spacing = 1.45; run(bp, body, size=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def _img(path, maxw=1600):
    im = _PILImage.open(path)
    if im.width > maxw:
        im = im.resize((maxw, round(im.height * maxw / im.width)), _PILImage.LANCZOS)
    bio = BytesIO()
    im.save(bio, format="PNG"); bio.seek(0)
    return bio

def figure(filename, caption, width=6.0):
    path = os.path.join(ASSETS, filename)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(6); p.paragraph_format.space_after = Pt(2)
    if os.path.exists(path):
        p.add_run().add_picture(_img(path), width=Inches(width))
    else:
        run(p, f"[缺图: {filename}]", color=FAINT, italic=True)
    figcap(caption)

def add_toc():
    p = doc.add_paragraph(); r = p.add_run(); rr = r._r
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'begin'); rr.append(e)
    it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve'); it.text = 'TOC \\o "1-2" \\h \\z \\u'; rr.append(it)
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'separate'); rr.append(e)
    t = OxmlElement('w:t'); t.text = "（在 Word 中按 Ctrl+A 后 F9 更新目录）"; rr.append(t)
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); rr.append(e)

def pb():
    doc.add_page_break()

# ════════════════════════════════════════════════════════ COVER
doc.add_paragraph().paragraph_format.space_after = Pt(36)
eb = doc.add_paragraph(); run(eb, "ROMTEK CORTEX · 用户文档", size=11, color=ACCENT, bold=True); eb.paragraph_format.space_after = Pt(6)
tp = doc.add_paragraph(); tp.paragraph_format.space_after = Pt(2); run(tp, "RLab Cortex", size=38, color=VERITY, bold=True, font="Segoe UI Semibold")
st = doc.add_paragraph(); st.paragraph_format.space_after = Pt(4); run(st, "产品使用手册", size=22, color=INK, bold=True); _hrule(st, color=H_VERITY, sz=14)
tl = doc.add_paragraph(); tl.paragraph_format.space_before = Pt(10); tl.paragraph_format.space_after = Pt(20); tl.paragraph_format.line_spacing = 1.6
run(tl, "面向使用者的操作指南：从登录、上传数据、对话分析，到调用算法、扩展工具、出图与导出，"
        "一步步把 RLab Cortex 用起来。", size=12.5, color=MUTED)
figure("clean_home.png", "RLab Cortex 起始页：拖入数据即可开始分析", width=6.2)
mt = doc.add_table(rows=1, cols=2); _no_borders(mt); mt.alignment = WD_TABLE_ALIGNMENT.CENTER; _widths(mt, [3.2, 3.2])
for cell, items in ((mt.rows[0].cells[0], [("适用版本", "v1.0.0"), ("产品", "RLab Cortex"), ("形态", "Web 应用，可私有化部署")]),
                    (mt.rows[0].cells[1], [("适用对象", "工程师 / 科研人员 / 试用专家"), ("出品", "RLab · Cortex 智能体矩阵"), ("文档版本", "v1.0 ｜ 2026-06")])):
    first = True
    for k, v in items:
        p = cell.paragraphs[0] if first else cell.add_paragraph(); first = False
        p.paragraph_format.space_after = Pt(5); p.paragraph_format.line_spacing = 1.3
        run(p, f"{k}　", size=9, color=FAINT, bold=True); run(p, v, size=9.5)
pb()

# ════════════════════════════════════════════════════════ TOC
ht = doc.add_paragraph(); run(ht, "目　录", size=16, color=VERITY, bold=True); _hrule(ht, color=H_VERITY, sz=10); ht.paragraph_format.space_after = Pt(6)
for it in [
    "01　产品简介与界面总览", "02　快速开始：五分钟跑通第一份分析", "03　数据接入与数据集管理",
    "04　对话式分析", "05　算法库", "06　扩展你自己的算法", "07　流程模板（可复用小应用）",
    "08　可视化", "09　设置与大模型（BYOK）", "10　反馈、版本与产品文档", "11　常见问题（FAQ）", "附录　内置算法速查表",
]:
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(5); p.paragraph_format.left_indent = Cm(0.3); run(p, it, size=11)
pb()

# ════════════════════════════════════════════════════════ 01 概览
h1("01", "产品简介与界面总览")
para("RLab Cortex 是一款面向工程师与科研人员的可验证数据分析智能体：把任意格式的数据拖进来，AI 自动读懂，"
     "用内置算法、你自己的代码或 AI 现场生成的工具完成分析，每一步都可追溯、可复算，并能沉淀为团队可复用的资产。"
     "本手册介绍如何把它用起来。")
h2("界面总览")
para("登录后进入工作台。左侧是图标导航栏，在以下视图之间切换；右侧为当前视图的工作区。")
table(["视图", "作用", "你在这里做什么"], [
    ["对话", "对话式分析智能体", "用自然语言提问，让 AI 选数据、选方法、出图"],
    ["数据集", "数据接入与管理", "上传文件、查看字段与血缘、预览与导出"],
    ["算法库", "内置 + 自有 + AI 算法", "浏览 29 个内置算法、配参试运行、上传或 AI 生成新算法"],
    ["流程模板", "可复用分析流程", "把跑通的流程存为模板，换数据一键复跑（运行·小程序）"],
    ["反馈收件箱", "管理员专用", "集中查看与分流用户反馈（仅管理员可见）"],
    ["设置", "账号与大模型", "配置 BYOK 大模型、查看版本/更新日志/产品文档"],
], widths=[1.1, 1.9, 3.4], cap="左侧导航的六个主视图")
callout("提示", "右下角常驻「反馈」按钮在任意视图都能点：随手记录“做不到 / 做错了 / 不敢信 / 想法”，会自动带上当前上下文。", fill=H_PLIGHT, bar=H_VERITY, tcolor=VERITY)
pb()

# ════════════════════════════════════════════════════════ 02 快速开始
h1("02", "快速开始：五分钟跑通第一份分析", color=ACCENT)
para("不需要任何配置，跟着下面五步即可完成第一份可追溯的分析。")
steps([
    ("注册 / 登录　", "用邮箱和密码注册并登录，进入工作台。"),
    ("准备数据　", "进入「数据集」，把 CSV / Excel 文件拖进上传区；或在「对话」起始页直接点一个示例场景（自带样例数据）。"),
    ("用大白话提问　", "进入「对话」，例如输入“这几个参数里哪个对结果影响最大？”或“帮我把这列噪声平滑一下”。"),
    ("看 AI 动手　", "智能体会自动判断输入/输出列、挑选合适的算法并执行，右侧实时显示每一步的想法、调用与结果。"),
    ("得到结论与图　", "AI 给出带数值的结论与图表；每一步都可回看，结果可继续作为下一步输入，或存为流程模板复用。"),
])
callout("无需记任何算法名", "你只描述意图（“平滑”“找异常”“看关联”“降维”），由智能体决定用 Savitzky-Golay、IQR、PCA 还是别的方法——这正是产品的设计取向。")
pb()

# ════════════════════════════════════════════════════════ 03 数据接入
h1("03", "数据接入与数据集管理")
h2("支持的格式")
bullets([
    ("表格数据　", "CSV、TSV、Excel（.xlsx/.xls，多工作表自动拆成多个数据集）、Parquet、JSON。"),
    ("仿真 / 网格　", "CGNS、VTK、STL（经 VTK 解析为点 + 场数据）；Tecplot ASCII 探针数据自动识别。"),
    ("任意私有格式　", "若不被原生支持，可让 AI 现场生成解析器，确认后保存为该扩展名的适配器，长期复用。"),
])
h2("上传与首读")
steps([
    "进入「数据集」→ 把文件拖入上传区，或点击选择文件。",
    "上传后系统立即给出无需大模型的「首读 Profile」：它是什么、字段类型、缺失情况，以及建议的下一步。",
    "遇到不认识的格式时，会提示生成自定义解析器：试解析 → 你确认结果无误 → 保存适配器。",
])
h2("字段、血缘与导出")
bullets([
    ("字段结构　", "列名、类型、唯一值数、缺失数，以及前若干行预览。"),
    ("数据血缘（lineage）　", "每个派生数据集都记录“由哪个上游数据、经过哪一步算法而来”，可逐级回溯到原始文件。"),
    ("派生与保留　", "分析产生的中间结果会作为带血缘的派生数据集；未钉住的派生集会在宽限期后自动回收，重要的可「保留」钉住。"),
    ("导出　", "数据集与结果可导出，便于落地到报告或其他工具。"),
])
figure("clean_dataset_chart.png", "数据集预览：自动识别字段、绘制多通道时序曲线，并给出字段结构", width=6.0)
pb()

# ════════════════════════════════════════════════════════ 04 对话
h1("04", "对话式分析", color=ACCENT)
para("「对话」是使用 RLab Cortex 最主要的方式。你用自然语言描述意图，智能体在一轮里完成“理解—选工具—执行—呈现”。")
h2("怎么提问")
bullets([
    "直接说目标，不必指定算法。例如：“哪个输入对输出影响最大？”“两个量之间有规律吗？”“有没有异常点？”",
    "起始页提供一组场景启动器（信号去噪 / 影响因素 / 拟合关系 / 异常检测 / 关联分析 / 降维），每个都带样例数据，点一下即可体验。",
    "可在对话中指定数据集；也可同时选多个数据集做对比。",
])
h2("流水线与追问续接")
bullets([
    ("自动组流水线　", "同一轮里，一个工具的输出会自动接到下一个工具的输入，组成可见的处理流水线。"),
    ("跨轮续接　", "系统记住上一阶段结果，你再说“在这个基础上再插值一下”，会接着上一步继续，而不是回到原始数据。"),
    ("全程留痕　", "想法、工具调用、工具结果、最终答复逐条显示并落库，事后可完整回放，定位到具体某一步。"),
])
callout("结果可信，是因为可复核", "对话给出的不只是一个数字，而是一条可回放的链路：用了哪个数据、走了哪几步、每步什么参数。评审时复核链路即可。", fill=H_PLIGHT, bar=H_VERITY, tcolor=VERITY)
pb()

# ════════════════════════════════════════════════════════ 05 算法库
h1("05", "算法库")
para("「算法库」收录 29 个内置算法，按类别浏览，可在线配参、试运行，并把结果存为流程模板。详细清单见文末附录。")
table(["类别", "包含"], [
    ["结构整理（4）", "转置、派生列、删列、分组聚合"],
    ["预处理（3）", "归一化、缺失填充、异常检测（IQR / Z-score / Dixon）"],
    ["滤波与信号（7）", "巴特沃斯 / 高斯 / 中值 / 移动平均 / Savitzky-Golay 滤波、FFT 频谱、寻峰"],
    ["回归与拟合（5）", "线性 / 多项式回归、曲线拟合、相关性、插值（含 RBF）"],
    ["降维与分析（3）", "PCA（线性 / 核）、灵敏度排序、K-means 聚类"],
], widths=[1.5, 4.7], accent=H_VERITY, cap="内置算法的六大类别（合计 29 个）")
h2("使用步骤")
steps([
    "进入「算法库」→ 按类别筛选，点选一个算法。",
    "在右侧表单填参数；不确定时可让 AI 根据你的数据与意图建议参数。",
    "选一个数据集，点运行；查看结果摘要（如 R²、RMSE、主频、解释方差等）。",
    "满意的话，可把这步或整条流程存为流程模板，便于以后复用。",
])
figure("30_algo_library.png", "算法库：29 个内置算法按类别浏览，可在线配参与试运行", width=6.0)
pb()

# ════════════════════════════════════════════════════════ 06 扩展算法
h1("06", "扩展你自己的算法", color=ACCENT)
para("RLab Cortex 可以“自我扩展”：把你信赖的代码搬进来，或让 AI 现场生成新工具。所有外来代码都先经安全沙箱验证，再成为可复用的能力。")
h2("两条途径")
bullets([
    ("上传自有算法　", "把你的 Python 方法整理为 run(df, **params) + META 形态上传；通过静态校验与测试后入库，即可在对话中调用、被流程模板编排、并可版本化。"),
    ("用 AI 生成　", "在「算法库 → 用 AI 生成」里用自然语言描述需求，系统按安全工具规范写出 Python、在沙箱跑通验证，你确认后才保存。"),
])
h2("安全沙箱（你不需要操作，但值得了解）")
bullets([
    "外来代码绝不在服务主进程执行，而是落到隔离子进程；",
    "只放行 numpy / pandas / scipy / sklearn 等科学计算库，禁用文件、网络、危险内建；",
    "运行设有墙钟超时、CPU 与内存上限、输出截断；大模型密钥对沙箱不可见。",
])
figure("clean_ai_generate.png", "用 AI 生成算法：描述需求 → 沙箱跑通验证 → 确认入库", width=6.2)
pb()

# ════════════════════════════════════════════════════════ 07 流程模板
h1("07", "流程模板（可复用小应用）")
para("把一段跑通的分析固化为流程模板，换一份数据即可整套复跑——相当于把“某位专家的标准作业流程”做成人人可用的小应用。")
h2("常用操作")
steps([
    "在对话或算法库里跑通一段分析后，将其保存为流程模板（记录有序的步骤：动作 + 算法 + 参数）。",
    "在「流程模板」里用可视化画布（FlowCanvas）增删步骤、调整顺序、修改参数。",
    "用「运行·小程序」模式：选择数据集、按需覆盖运行时参数，点运行即可整套复跑。",
    "每一步可选物化为带血缘的派生数据集，便于回溯与继续分析。",
])
figure("clean_template_runapp.png", "流程模板的“运行·小程序”模式：换数据即跑，非专家也能一键复用", width=6.0)
pb()

# ════════════════════════════════════════════════════════ 08 可视化
h1("08", "可视化", color=ACCENT)
para("分析过程中可随时出图。基础图表在前端即可交互调整，复杂图表由 AI 现场生成。")
table(["能力", "说明"], [
    ["内置交互图表", "折线 / 散点 / 柱状，支持在前端切换 x/y/系列、对长数据自动下采样"],
    ["AI 生成图表", "雷达 / 极坐标、热力、等高线、3D 曲面 / 散点、箱线 / 小提琴、平行坐标、桑基等任意图形"],
    ["多数据集叠加", "把同名指标跨多个数据集叠加到一张图上对比"],
    ["批量出图", "按数据集或按列一次生成多张图"],
    ["3D / 网格", "对 CGNS / VTK 等网格数据用 3D 查看器渲染"],
], widths=[1.7, 4.5], cap="可视化能力一览")
pb()

# ════════════════════════════════════════════════════════ 09 设置 BYOK
h1("09", "设置与大模型（BYOK）")
para("RLab Cortex 默认使用内置大模型即可工作。若希望走你自己的模型与密钥（数据与模型不出内网、或控制成本），可在「设置」里配置 BYOK（Bring Your Own Key）。")
h2("配置步骤")
steps([
    "进入「设置」→「LLM 服务商（自带 Key）」。",
    "选择服务商：DeepSeek、通义千问（DashScope）、OpenAI，或「Custom」填任意 OpenAI 兼容端点。",
    "确认 Base URL，选择或填写模型名（如 deepseek-chat）。",
    "填入 API Key（已配置过则可留空保持原值），点「保存」。下一条消息即生效，无需重启。",
])
figure("clean_byok.png", "BYOK 设置：在 DeepSeek / 通义千问 / OpenAI / 任意兼容端点之间切换", width=6.0)
callout("提示", "BYOK 让企业可以使用自建或指定的大模型，既满足合规要求，也避免“token 账单失控”的顾虑。", fill=H_LIGHT, bar=H_ACCENT)
pb()

# ════════════════════════════════════════════════════════ 10 反馈/版本/文档
h1("10", "反馈、版本与产品文档", color=ACCENT)
h2("提交反馈")
bullets([
    ("随手反馈　", "点右下角「反馈」按钮，选一类（做不到 / 做错了 / 不敢信 / 想法），写一句，Ctrl+Enter 发送；系统自动带上当前视图、会话、数据集、运行与可选截图。"),
    ("管理员收件箱　", "管理员可在「反馈收件箱」按状态（待处理 / 已查看 / 已完成）与类型分流，并跳回反馈发生的现场。"),
])
h2("查看版本与更新日志")
para("左侧导航栏底部常驻当前版本号（如 v1.0.0）；点它或进入「设置 →关于」，可查看当前版本与「更新日志」——即本版相比上一版的新增、优化与修复。")
h2("下载产品文档")
para("在「设置 →关于 →产品文档」处，可直接下载《产品使用手册》（本文）与《产品白皮书》。")
callout("版本号从哪来", "版本号是后端的单一事实源（/api/health 与 /api/about 一致对外报告）；更新日志由结构化清单维护，并可用 tools/gen_changelog.py 从 git 提交自动起草新版本条目。", fill=H_LIGHT, bar=H_ACCENT)
pb()

# ════════════════════════════════════════════════════════ 11 FAQ
h1("11", "常见问题（FAQ）")
faqs = [
    ("上传的文件格式不被支持怎么办？", "让系统生成自定义解析器：它会试解析并给出预览，你确认无误后保存为该扩展名的适配器，之后同类文件自动套用。"),
    ("AI 选错了列或用错了方法怎么办？", "在对话里直接纠正（“这列其实是电压”“改用保峰平滑”）；纠正可经反馈沉淀为可复用的规则，下次自动套用。"),
    ("结果可信吗？怎么核对？", "每一步都可回放：用了哪个数据、走了哪几步、每步什么参数。复核这条链路即可，而不必盲信模型。"),
    ("我的私有算法安全吗？", "外来代码只在隔离子进程中运行，禁用网络与文件访问，设有资源上限，且拿不到大模型密钥。"),
    ("可以私有化部署吗？", "可以。系统支持从单机到 Kubernetes 的部署，数据与模型均可不出内网；详询交付方。"),
    ("怎么换成我们自己的大模型？", "见第 9 章 BYOK：在设置里填入自有服务商、端点、模型与密钥即可。"),
]
for q, a in faqs:
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(1); p.paragraph_format.space_before = Pt(6)
    run(p, "Q　", color=VERITY, bold=True); run(p, q, bold=True)
    pa = doc.add_paragraph(); pa.paragraph_format.space_after = Pt(5); pa.paragraph_format.left_indent = Cm(0.7); pa.paragraph_format.line_spacing = 1.45
    run(pa, "A　", color=ACCENT, bold=True); run(pa, a)
pb()

# ════════════════════════════════════════════════════════ 附录
h1("附录", "内置算法速查表", color=ACCENT)
para("下表为 29 个内置算法的速查（slug 为系统内部标识）。用户上传与 AI 生成的算法会随使用持续增加，不在此列。")
table(["类别", "算法（中文 · slug）"], [
    ["结构整理", "转置 transpose、派生列 derived_column、删列 drop_columns、分组聚合 group_aggregate"],
    ["预处理", "归一化 normalize、缺失填充 fill_missing、异常检测 outlier_detect"],
    ["滤波与信号", "移动平均 moving_average、中值 median_filter、高斯 gaussian_filter、Savitzky-Golay savgol_filter、巴特沃斯 butterworth_filter、FFT 频谱 fft_frequency_analysis、寻峰 find_peaks"],
    ["回归与拟合", "线性回归 linear_regression、多项式回归 polynomial_regression、曲线拟合 curve_fit、相关性 correlation、插值 interpolate"],
    ["降维与分析", "PCA pca、灵敏度 sensitivity、K-means 聚类 kmeans_cluster"],
], widths=[1.2, 5.0], accent=H_VERITY, fs=9, cap="内置算法速查表（29 个）")

doc.add_paragraph().paragraph_format.space_after = Pt(8)
cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER; _hrule(cp, color=H_LINE, sz=6)
end = doc.add_paragraph(); end.alignment = WD_ALIGN_PARAGRAPH.CENTER
run(end, "RLab · Cortex 智能体矩阵　｜　RLab Cortex 产品使用手册 v1.0", size=9, color=MUTED)

try:
    doc.save(OUT); saved = OUT
except PermissionError:
    saved = os.path.join(os.path.dirname(OUT), "RLab_Cortex_产品使用手册_修订版.docx"); doc.save(saved)
    print("WARN: 原文件被占用，已另存修订版。")
print("SAVED:", saved)
print("figures:", _fig[0], "tables:", _tab[0])
