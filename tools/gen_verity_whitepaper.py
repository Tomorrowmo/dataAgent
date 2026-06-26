# -*- coding: utf-8 -*-
"""
Generate the RLab Cortex product white-paper (.docx) with python-docx.
Content is grounded in the repo's real docs + code-verified feature inventory.
Run:  python tools/gen_verity_whitepaper.py
"""
import os
from io import BytesIO
from PIL import Image as _PILImage
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "docs", "pitch", "assets")
OUT = os.path.join(ROOT, "docs", "pitch", "RLab_Cortex_产品白皮书.docx")

# ── palette ─────────────────────────────────────────────────────────────────
INK      = RGBColor(0x12, 0x1B, 0x2A)   # near-black body
MUTED    = RGBColor(0x55, 0x64, 0x74)   # secondary
FAINT    = RGBColor(0x8A, 0x98, 0xA6)   # captions
ACCENT   = RGBColor(0x03, 0x69, 0xA1)   # deep sky (suite accent)
ACCENT2  = RGBColor(0x0E, 0xA5, 0xE9)
VERITY   = RGBColor(0x6D, 0x35, 0xD6)   # product purple
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
GREEN    = RGBColor(0x15, 0x80, 0x3D)

H_ACCENT  = "0369A1"
H_VERITY  = "6D35D6"
H_LIGHT   = "EAF2F8"   # blue tint
H_PLIGHT  = "F1ECFB"   # purple tint
H_ROW     = "F4F8FB"   # zebra
H_GREENL  = "EAF6EE"
H_AMBERL  = "FBF1E2"
H_LINE    = "D9E4EC"

BODY_FONT = "微软雅黑"
MONO_FONT = "Consolas"

# ── low-level helpers ───────────────────────────────────────────────────────
def _ea(run, name):
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts'); rPr.append(rFonts)
    for a in ('w:eastAsia', 'w:ascii', 'w:hAnsi'):
        rFonts.set(qn(a), name)

def _shade(cell, hexfill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hexfill)
    tcPr.append(shd)

def _cell_margins(cell, top=60, bottom=60, left=110, right=110):
    tcPr = cell._tc.get_or_add_tcPr()
    m = OxmlElement('w:tcMar')
    for tag, val in (('top', top), ('bottom', bottom), ('start', left), ('end', right)):
        e = OxmlElement('w:' + tag); e.set(qn('w:w'), str(val)); e.set(qn('w:type'), 'dxa'); m.append(e)
    tcPr.append(m)

def _set_borders(table, color=H_LINE, sz=4, which=('top','bottom','left','right','insideH','insideV')):
    tblPr = table._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in which:
        e = OxmlElement('w:' + edge)
        e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), str(sz))
        e.set(qn('w:space'), '0'); e.set(qn('w:color'), color)
        borders.append(e)
    tblPr.append(borders)

def _no_borders(table):
    tblPr = table._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top','bottom','left','right','insideH','insideV'):
        e = OxmlElement('w:' + edge); e.set(qn('w:val'), 'none'); borders.append(e)
    tblPr.append(borders)

def _col_widths(table, widths_in):
    table.autofit = False
    table.allow_autofit = False
    for row in table.rows:
        for i, w in enumerate(widths_in):
            row.cells[i].width = Inches(w)

def _hrule(par, color=H_LINE, sz=8):
    pPr = par._p.get_or_add_pPr()
    pbdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single'); bottom.set(qn('w:sz'), str(sz))
    bottom.set(qn('w:space'), '4'); bottom.set(qn('w:color'), color)
    pbdr.append(bottom); pPr.append(pbdr)

# ── mid-level builders ──────────────────────────────────────────────────────
doc = Document()

# base style
normal = doc.styles['Normal']
normal.font.name = BODY_FONT
normal.font.size = Pt(10.5)
normal.font.color.rgb = INK
_ea(normal.element.rPr.append and normal.element or normal.element, BODY_FONT) if False else None
# ensure eastAsia on Normal
rpr = normal.element.get_or_add_rPr()
rfonts = rpr.find(qn('w:rFonts'))
if rfonts is None:
    rfonts = OxmlElement('w:rFonts'); rpr.append(rfonts)
rfonts.set(qn('w:eastAsia'), BODY_FONT); rfonts.set(qn('w:ascii'), BODY_FONT); rfonts.set(qn('w:hAnsi'), BODY_FONT)
normal.paragraph_format.line_spacing = 1.5
normal.paragraph_format.space_after = Pt(0)

# page margins
for sec in doc.sections:
    sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.4); sec.right_margin = Cm(2.4)

def run(par, text, size=10.5, color=INK, bold=False, italic=False, font=BODY_FONT):
    r = par.add_run(text)
    r.font.size = Pt(size); r.font.color.rgb = color; r.bold = bold; r.italic = italic
    _ea(r, font)
    return r

def para(text="", size=10.5, color=INK, bold=False, italic=False, align=None,
         before=0, after=7, line=1.5, font=BODY_FONT, indent=True):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = line
    if align is not None:
        p.alignment = align
    if text:
        run(p, text, size=size, color=color, bold=bold, italic=italic, font=font)
    if indent and align is None:
        pPr = p._p.get_or_add_pPr()
        ind = pPr.find(qn('w:ind'))
        if ind is None:
            ind = OxmlElement('w:ind'); pPr.append(ind)
        ind.set(qn('w:firstLineChars'), '200')   # 2 字符，随字号缩放
        ind.set(qn('w:firstLine'), '420')         # 兜底：2×10.5pt ≈ 420 twips
    return p

def rich(parts, align=None, after=7, before=0, line=1.5, size=10.5):
    """parts: list of (text, {opts}) tuples on one paragraph."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after); p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.line_spacing = line
    if align is not None:
        p.alignment = align
    for text, opts in parts:
        o = dict(size=size, color=INK, bold=False, italic=False, font=BODY_FONT)
        o.update(opts); run(p, text, **o)
    return p

def bullets(items, after=4, size=10.5, color=INK, lead_color=ACCENT):
    for it in items:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.first_line_indent = Cm(-0.35)
        p.paragraph_format.line_spacing = 1.45
        run(p, "▪ ", size=size, color=lead_color, bold=True)
        if isinstance(it, tuple):
            run(p, it[0], size=size, color=INK, bold=True)
            run(p, it[1], size=size, color=color)
        else:
            run(p, it, size=size, color=color)

def numbered(items, after=4, size=10.5):
    for i, it in enumerate(items, 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.left_indent = Cm(0.7)
        p.paragraph_format.first_line_indent = Cm(-0.7)
        p.paragraph_format.line_spacing = 1.45
        run(p, f"{i}. ", size=size, color=ACCENT, bold=True)
        if isinstance(it, tuple):
            run(p, it[0], size=size, color=INK, bold=True)
            run(p, it[1], size=size, color=INK)
        else:
            run(p, it, size=size, color=INK)

_eyebrow_n = 0
def h1(num, text, color=VERITY):
    global _eyebrow_n
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(20); p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.style = doc.styles['Heading 1']
    r = p.add_run(f"{num}　{text}")
    r.font.size = Pt(17); r.bold = True; r.font.color.rgb = color
    _ea(r, BODY_FONT)
    _hrule(p, color=H_VERITY if color == VERITY else H_ACCENT, sz=10)
    sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(2)
    return p

def h2(text, color=ACCENT):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12); p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    p.style = doc.styles['Heading 2']
    r = p.add_run(text); r.font.size = Pt(12.5); r.bold = True; r.font.color.rgb = color
    _ea(r, BODY_FONT)
    return p

def h3(text, color=INK):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8); p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text); r.font.size = Pt(11); r.bold = True; r.font.color.rgb = color
    _ea(r, BODY_FONT)
    return p

def table(headers, rows, widths=None, accent=H_ACCENT, zebra=True,
          header_color=WHITE, first_col_bold=False, font_size=9.5, align_center_cols=None,
          cap=None):
    if cap:
        tabcaption(cap)
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_borders(t, color=H_LINE, sz=4)
    align_center_cols = align_center_cols or []
    # header
    hdr = t.rows[0].cells
    for i, htext in enumerate(headers):
        _shade(hdr[i], accent); _cell_margins(hdr[i])
        hdr[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        pp = hdr[i].paragraphs[0]; pp.paragraph_format.space_after = Pt(0)
        pp.alignment = WD_ALIGN_PARAGRAPH.CENTER if i in align_center_cols or True else WD_ALIGN_PARAGRAPH.LEFT
        run(pp, htext, size=font_size + .5, color=header_color, bold=True)
    # body
    for ri, rowvals in enumerate(rows):
        cells = t.add_row().cells
        for ci, val in enumerate(rowvals):
            c = cells[ci]; _cell_margins(c)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if zebra and ri % 2 == 1:
                _shade(c, H_ROW)
            pp = c.paragraphs[0]; pp.paragraph_format.space_after = Pt(0)
            pp.paragraph_format.line_spacing = 1.3
            if ci in align_center_cols:
                pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            bold = first_col_bold and ci == 0
            col = INK
            run(pp, str(val), size=font_size, color=col, bold=bold)
    if widths:
        _col_widths(t, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def callout(title, body, fill=H_LIGHT, bar=H_ACCENT, title_color=ACCENT, icon="●"):
    t = doc.add_table(rows=1, cols=2)
    _no_borders(t)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _col_widths(t, [0.10, 6.3])
    bar_cell, body_cell = t.rows[0].cells
    _shade(bar_cell, bar)
    _shade(body_cell, fill)
    _cell_margins(body_cell, top=110, bottom=110, left=200, right=160)
    bar_cell.width = Inches(0.10)
    p = body_cell.paragraphs[0]; p.paragraph_format.space_after = Pt(3)
    if title:
        run(p, title, size=10.5, color=title_color, bold=True)
    if body:
        bp = body_cell.add_paragraph(); bp.paragraph_format.space_after = Pt(0); bp.paragraph_format.line_spacing = 1.45
        run(bp, body, size=10, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def _img(path, maxw=1600):
    """Downscale wide screenshots before embedding — keeps the docx small and
    avoids headless-Word OutOfMemory when exporting to PDF. Sharp enough at the
    ~6in print width. Returns a PNG stream."""
    im = _PILImage.open(path)
    if im.width > maxw:
        im = im.resize((maxw, round(im.height * maxw / im.width)), _PILImage.LANCZOS)
    bio = BytesIO()
    im.save(bio, format="PNG"); bio.seek(0)
    return bio

def figure(filename, caption, width=6.3):
    path = os.path.join(ASSETS, filename)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6); p.paragraph_format.space_after = Pt(2)
    if os.path.exists(path):
        run_ = p.add_run(); run_.add_picture(_img(path), width=Inches(width))
    else:
        run(p, f"[缺图: {filename}]", color=FAINT, italic=True)
    figcaption(caption)

def flow_diagram(boxes, fill=H_LIGHT, txt=ACCENT, arrow_color=ACCENT, cap=None):
    """Horizontal block-diagram via a single-row borderless table: box | → | box ..."""
    ncols = len(boxes) * 2 - 1
    t = doc.add_table(rows=1, cols=ncols)
    _no_borders(t); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    box_w, arr_w = 1.18, 0.32
    widths = []
    for i in range(ncols):
        widths.append(box_w if i % 2 == 0 else arr_w)
    cells = t.rows[0].cells
    bi = 0
    for i in range(ncols):
        c = cells[i]; c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        pp = c.paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER; pp.paragraph_format.space_after = Pt(0)
        if i % 2 == 0:
            top, bottom = boxes[bi]; bi += 1
            _shade(c, fill); _cell_margins(c, top=90, bottom=90, left=40, right=40)
            run(pp, top, size=9.5, color=txt, bold=True)
            if bottom:
                pp2 = c.add_paragraph(); pp2.alignment = WD_ALIGN_PARAGRAPH.CENTER; pp2.paragraph_format.space_after = Pt(0)
                run(pp2, bottom, size=7.5, color=MUTED)
        else:
            run(pp, "▶", size=11, color=arrow_color, bold=True)
    _col_widths(t, widths)
    if cap:
        figcaption(cap)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def layer_diagram(layers, cap=None):
    """Vertical stack of full-width shaded bands. layers: list of (label, detail, fill, txthex)."""
    for label, detail, fill, txthex in layers:
        t = doc.add_table(rows=1, cols=1); _no_borders(t); t.alignment = WD_TABLE_ALIGNMENT.CENTER
        _col_widths(t, [6.4])
        c = t.rows[0].cells[0]; _shade(c, fill); _cell_margins(c, top=80, bottom=80, left=160, right=160)
        p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(0)
        run(p, label + "　", size=10, color=RGBColor.from_string(txthex), bold=True)
        run(p, detail, size=9, color=MUTED)
        sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(2); sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run(sp, "▼", size=8, color=FAINT)
    if cap:
        figcaption(cap)

def add_toc():
    p = doc.add_paragraph()
    run_ = p.add_run()
    fldChar = OxmlElement('w:fldChar'); fldChar.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText'); instr.set(qn('xml:space'), 'preserve')
    instr.text = 'TOC \\o "1-2" \\h \\z \\u'
    fldChar2 = OxmlElement('w:fldChar'); fldChar2.set(qn('w:fldCharType'), 'separate')
    t = OxmlElement('w:t'); t.text = "（在 Word 中按 Ctrl+A 后 F9 更新目录）"
    fldChar3 = OxmlElement('w:fldChar'); fldChar3.set(qn('w:fldCharType'), 'end')
    r = run_._r
    r.append(fldChar); r.append(instr); r.append(fldChar2); r.append(t); r.append(fldChar3)

def page_break():
    doc.add_page_break()

# ── numbered captions (题注 via SEQ fields, auto-renumber on F9) ─────────────
_fig_n = [0]
_tab_n = [0]

def _seq_run(par, seqname, cached, size=8.5, color=FAINT, bold=True):
    r = par.add_run(); rr = r._r
    f1 = OxmlElement('w:fldChar'); f1.set(qn('w:fldCharType'), 'begin')
    it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve')
    it.text = f' SEQ {seqname} \\* ARABIC '
    f2 = OxmlElement('w:fldChar'); f2.set(qn('w:fldCharType'), 'separate')
    t = OxmlElement('w:t'); t.text = str(cached)
    f3 = OxmlElement('w:fldChar'); f3.set(qn('w:fldCharType'), 'end')
    for e in (f1, it, f2, t, f3):
        rr.append(e)
    r.font.size = Pt(size); r.font.color.rgb = color; r.bold = bold; _ea(r, BODY_FONT)
    return r

def figcaption(text):
    """图题：置于图/图表下方，居中。"""
    _fig_n[0] += 1
    cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_before = Pt(2); cap.paragraph_format.space_after = Pt(11)
    cap.paragraph_format.keep_together = True
    run(cap, "图 ", size=8.5, color=FAINT, bold=True)
    _seq_run(cap, "Figure", _fig_n[0], color=FAINT)
    run(cap, "　" + text, size=8.5, color=FAINT, italic=True)

def tabcaption(text):
    """表题：置于表上方，居中。"""
    _tab_n[0] += 1
    cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_before = Pt(8); cap.paragraph_format.space_after = Pt(3)
    cap.paragraph_format.keep_with_next = True
    run(cap, "表 ", size=8.5, color=MUTED, bold=True)
    _seq_run(cap, "Table", _tab_n[0], color=MUTED)
    run(cap, "　" + text, size=8.5, color=MUTED, bold=True)

def bar_chart(items, accent=H_VERITY, track=H_PLIGHT, cap=None):
    """Horizontal bar chart drawn with shaded table cells. items: [(label, value, display)]."""
    maxv = max(v for _, v, _ in items) or 1.0
    BAR, LBL, VAL = 3.9, 1.6, 0.6
    for label, val, disp in items:
        fw = max(0.05, BAR * val / maxv)
        ew = max(0.0, BAR - fw)
        t = doc.add_table(rows=1, cols=4); _no_borders(t); t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.rows[0].cells
        c[0].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p0 = c[0].paragraphs[0]; p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT; p0.paragraph_format.space_after = Pt(0)
        run(p0, label, size=9, color=INK, bold=True); _cell_margins(c[0], left=40, right=120, top=46, bottom=46)
        _shade(c[1], accent); _cell_margins(c[1], left=40, right=40, top=52, bottom=52)
        _shade(c[2], track)
        c[3].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p3 = c[3].paragraphs[0]; p3.alignment = WD_ALIGN_PARAGRAPH.LEFT; p3.paragraph_format.space_after = Pt(0)
        run(p3, disp, size=8.5, color=MUTED); _cell_margins(c[3], left=120, right=10, top=46, bottom=46)
        _col_widths(t, [LBL, fw, ew, VAL])
        sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(2); sp.paragraph_format.space_before = Pt(0)
        for r in sp.runs:
            r.font.size = Pt(2)
    if cap:
        figcaption(cap)

# ════════════════════════════════════════════════════════════════════════════
# COVER
# ════════════════════════════════════════════════════════════════════════════
sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(40)
eb = doc.add_paragraph(); eb.alignment = WD_ALIGN_PARAGRAPH.LEFT
run(eb, "ROMTEK CORTEX · 产品白皮书", size=11, color=ACCENT, bold=True, font=MONO_FONT)
eb.paragraph_format.space_after = Pt(6)

tp = doc.add_paragraph(); tp.paragraph_format.space_after = Pt(2)
run(tp, "RLab Cortex", size=40, color=VERITY, bold=True, font="Segoe UI Semibold")
st = doc.add_paragraph(); st.paragraph_format.space_after = Pt(4)
run(st, "可验证的数据分析智能体", size=22, color=INK, bold=True)
_hrule(st, color=H_VERITY, sz=14)

tl = doc.add_paragraph(); tl.paragraph_format.space_before = Pt(10); tl.paragraph_format.space_after = Pt(22)
tl.paragraph_format.line_spacing = 1.6
run(tl, "把数据交给它，AI 自动读懂、动手分析——每一步解析、算法与图表都可追溯、可复算，"
        "结论经得起复核，并能沉淀为团队可复用的资产。", size=12.5, color=MUTED)

figure("clean_home.png", "RLab Cortex 起始页：拖入数据即可开始，并以贴近场景的问题引导分析", width=6.3)

# meta block
mt = doc.add_table(rows=1, cols=2); _no_borders(mt); mt.alignment = WD_TABLE_ALIGNMENT.CENTER
_col_widths(mt, [3.2, 3.2])
lft, rgt = mt.rows[0].cells
for cell, items in ((lft, [("产品名称", "RLab Cortex"),
                           ("产品形态", "可私有化部署的 Web 智能体应用"),
                           ("目标用户", "工程师与科研人员")]),
                    (rgt, [("适用领域", "通用工程数据（电池测试 / CFD·CAE 等）"),
                           ("出品", "RLab · Cortex 智能体矩阵"),
                           ("文档版本", "v1.0 ｜ 2026-06")])):
    cell.paragraphs[0].paragraph_format.space_after = Pt(0)
    first = True
    for k, v in items:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        p.paragraph_format.space_after = Pt(5); p.paragraph_format.line_spacing = 1.3
        run(p, f"{k}　", size=9, color=FAINT, bold=True)
        run(p, v, size=9.5, color=INK)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# TOC
# ════════════════════════════════════════════════════════════════════════════
h_toc = doc.add_paragraph(); h_toc.paragraph_format.space_after = Pt(6)
run(h_toc, "目　录", size=16, color=VERITY, bold=True); _hrule(h_toc, color=H_VERITY, sz=10)
toc_items = [
    "01　产品概览与定位",
    "02　它要解决的问题：工程数据分析的三道坎",
    "03　核心价值：它能为团队带来什么",
    "04　输入与输出：一条端到端、可追溯的完整链条",
    "05　技术途径与技术路线",
    "06　可扩展性：如何把它接入你自己的业务",
    "07　功能清单（按模块）",
    "08　产品与服务方式",
    "09　应用案例",
    "10　未来发展方向",
]
for it in toc_items:
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(5); p.paragraph_format.left_indent = Cm(0.3)
    run(p, it, size=11, color=INK)
page_break()

# ════════════════════════════════════════════════════════════════════════════
# 01 概览与定位
# ════════════════════════════════════════════════════════════════════════════
h1("01", "产品概览与定位")

para("RLab Cortex 是一款面向工程师与科研人员的「可验证」数据分析智能体。它的出发点很朴素：在工程与科研场景里，"
     "一个“看起来对、其实算错”的数字，比没有答案更危险——它可能被写进报告、汇入设计冻结、随产品出厂。"
     "市面上以“上传 CSV、聊天、让大模型现写一段 pandas”为形态的通用工具，恰恰把这一点当作了可接受的代价：模型每次都即兴生成一段用完即弃的代码，"
     "没有沉淀、没有版本、没有人对它的假设、单位与失效边界负责。RLab Cortex 要解决的，正是这条裂缝。")

para("我们不做“又一个 AI 数据助手”。RLab Cortex 的两个内核，决定了它与通用工具的根本区别：")
bullets([
    ("可验证、可追溯　", "从原始文件被读懂的那一刻起，每一次解析、每一步算法、每一张图表，都带着可回放的来历；中间结果不被丢弃，而是作为可复算的资产沉淀下来。结论之所以可信，是因为它的每一步都摆在明面上、可被复核。"),
    ("自我扩展　", "它不止能调用内置算法，还能直接运行你自己信赖的代码，或在对话中让 AI 现场生成新工具——所有外来代码均先经沙箱验证，再成为团队可复用的能力。工具箱随使用持续累积，而非每次从零开始。"),
])

callout("一句话定位",
        "面向工程师与科研人员的「可验证」数据分析智能体：任意格式的数据拖进来，AI 自动读懂，"
        "用内置算法、你自己的代码、或 AI 现场生成的工具完成分析，每一步都有可追溯的来历，并能沉淀成可复用的流程。",
        fill=H_PLIGHT, bar=H_VERITY, title_color=VERITY)

h2("它适合谁")
para("RLab Cortex 锁定的是“数据本身带专业属性、且必须信得过结论”的人群——他们手里通常已经有一批用了多年、比任何聊天机器人都更信任的脚本与方法。"
     "下表是三类典型用户，也是产品当前与近期重点服务的场景：")
table(
    ["典型用户", "今天的工作方式", "最痛的地方"],
    [
        ["电池测试工程师", "Excel + MATLAB + 临时 Python 笔记本", "多厂商循环仪数据格式割裂；dV/dQ、容量衰减等分析靠私人脚本，难共享、难复核"],
        ["CFD / CAE 仿真工程师", "PyFoam / Tecplot 脚本 + PPT 拼图", "参数化 DOE 后处理繁琐重复；算例之间对比、灵敏度分析缺少统一工具"],
        ["试验 / 测试与科研人员", "组内相传的 MATLAB 工具箱", "经验散落在个人电脑里，人员变动即面临脚本失传；结果难以说清依据"],
    ],
    widths=[1.5, 2.3, 2.6], first_col_bold=True,
    cap="RLab Cortex 锁定的三类典型用户及其核心痛点",
)

h2("与通用 AI 数据工具的区别")
table(
    ["维度", "通用「聊天分析 CSV」工具", "RLab Cortex"],
    [
        ["对待结论", "给出答案即可，正确性靠用户自检", "每步可追溯、可复算，先取信再交付"],
        ["算法来源", "大模型即兴现写、用完即弃", "内置精选算法 + 你的代码 + AI 生成，均经沙箱验证并可沉淀"],
        ["专业数据", "偏通用业务表格", "原生支持传感器/仪器/仿真等工程数据与网格文件"],
        ["资产沉淀", "几乎没有，每次从零", "解析器、算法、流程模板跨会话、跨人复用"],
        ["私有化", "多为公有 SaaS", "可整套私有化部署，数据不出内网"],
    ],
    widths=[1.2, 2.7, 2.5], first_col_bold=True,
    cap="RLab Cortex 与通用「聊天分析 CSV」工具的关键差异",
)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 02 问题
# ════════════════════════════════════════════════════════════════════════════
h1("02", "它要解决的问题：工程数据分析的三道坎", color=ACCENT)

para("工程师每天与数据打交道，真正消耗时间和信任的，不是“跑一个算法”，而是横在算法前后的三道坎。RLab Cortex 的产品设计，正是逐一拆掉它们。")

h3("坎一　数据读不进来：格式割裂，时间耗在“把文件变成能算的表”")
para("循环仪、采集仪、求解器各家一套导出格式，Maccor、Arbin、Neware、Tecplot、CGNS……同一件事要写一堆一次性解析脚本。"
     "工程师往往花大半天把文件“变成能算的表”，真正的分析还没开始。这类前处理工作重复、易错、且无法积累。")

h3("坎二　算法靠私人脚本：经验锁在个人电脑里，难共享、难复核")
para("最值钱的分析方法——某人的 dV/dQ 峰值追踪、某条灵敏度排序、某段滤波参数——通常以 MATLAB 或 Jupyter 笔记本的形式，"
     "存在某个工程师的电脑里。它能跑，但不可共享、不可版本化、更无法被同行快速复核。人一走，方法就失传；要复用，只能靠邮件互发脚本。")

h3("坎三　结论不敢信：AI “看着自信，数字是错的”")
para("通用大模型工具的通病，是给出一个措辞笃定、却经不起追问的数字。它不会告诉你它假设了什么、用的什么单位、在什么条件下会失效。"
     "对一个要把结果写进交付报告的工程师而言，这种“自信的错误”是不可接受的。")

callout("我们的判断",
        "前两道坎是“做不到”的问题，第三道坎是“不敢信”的问题。把三者一并解决，需要的不是一个表达更流畅的模型，"
        "而是一个能承载专家经验、让非专家也能信任使用的「容器」——这正是 RLab Cortex 的设计原点。",
        fill=H_LIGHT, bar=H_ACCENT)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 03 价值
# ════════════════════════════════════════════════════════════════════════════
h1("03", "核心价值：它能为团队带来什么")

para("把上面三道坎拆掉之后，RLab Cortex 为团队带来的，是三类可以被感知、甚至被量化的收益。")

h2("① 把结论的可信度，从主观判断变成可复核的事实")
para("每一次分析都留下完整的来历：用了哪个数据集、走了哪几步、每步什么参数、产出什么中间结果。"
     "评审时不再是“相信工程师”，而是“复核这条链路”。出了问题能定位到具体一步，对了也说得清为什么对。"
     "对需要对外负责的结论，这一点意味着从“个人背书”升级为“流程背书”。")

h2("② 把个人经验沉淀为团队资产，持续积累")
para("工程师信任的私人脚本，第一次上传后就成为团队里可被调用、可被版本化的工具；一次成功的分析过程，可以一键保存为流程模板，"
     "换个数据集即可复跑。新人加入，不必从零摸索，直接继承前人沉淀的解析器、算法与流程。团队的能力不再随人员流动而流失。")

h2("③ 把重复劳动交给智能体，把判断留给人")
para("文件解析、算法选择、画图、批量出图这类机械工作，由智能体在对话中连贯完成；工程师真正的精力，回到“这个结论意味着什么、下一步怎么做”的判断上。")

h2("价值速览")
table(
    ["收益维度", "传统方式", "用了 RLab Cortex 之后"],
    [
        ["上手一份新数据", "写解析脚本，半天起步", "拖进来，AI 自动读懂；首次教会即永久复用"],
        ["复用一套分析方法", "翻找、互发笔记本，重配环境", "调用已沉淀的算法或一键复跑流程模板"],
        ["复核一个结论", "口头解释 + 翻聊天记录", "回放可追溯链路，定位到具体步骤"],
        ["接入自有算法", "无处安放，散在个人电脑", "上传即成团队工具，沙箱验证、可共享"],
        ["团队知识传承", "依赖人员与口头交接，易随人员流动而流失", "解析器 / 算法 / 流程模板三类资产持续累积"],
    ],
    widths=[1.5, 2.3, 2.6], first_col_bold=True, accent=H_VERITY,
    cap="传统方式与使用 RLab Cortex 的关键差异对比",
)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 04 输入输出完整链条
# ════════════════════════════════════════════════════════════════════════════
h1("04", "输入与输出：一条端到端、可追溯的完整链条", color=ACCENT)

para("RLab Cortex 的“可验证”，落到实处就是这条链条：从一个原始文件进、到一个可复核的结论出，中间的每一环都不被黑箱吞掉。")

h2("端到端数据流")
flow_diagram([
    ("① 输入", "原始文件"),
    ("② 读懂", "解析建表"),
    ("③ 理解", "列义识别"),
    ("④ 分析", "算法/代码/AI"),
    ("⑤ 呈现", "图表+结论"),
    ("⑥ 沉淀", "资产复用"),
], fill=H_LIGHT, txt=ACCENT, arrow_color=ACCENT2,
   cap="RLab Cortex 端到端数据处理链条：从原始文件到可复核结论的六个环节")

h3("输入（进什么）")
bullets([
    ("表格数据　", "CSV / TSV / Excel(.xlsx/.xls，多工作表自动拆分) / Parquet / JSON。"),
    ("仿真与网格　", "CGNS / VTK / STL 网格文件（经 VTK 解析为点+场数据）、Tecplot ASCII 探针数据自动识别。"),
    ("任意私有格式　", "若不匹配内置或已存解析器，可让 AI 现场生成自定义解析器，确认后即长期复用。"),
])
h3("输出（出什么）")
bullets([
    ("可交互图表　", "折线 / 散点 / 柱状等内置图，以及由 AI 生成的雷达、热力、等高线、3D 曲面、箱线等任意图形；支持多数据集叠加对比、批量出图。"),
    ("结构化结论　", "算法返回系数、R²、RMSE、主频、峰位、解释方差等量化结果，配自然语言解读。"),
    ("派生数据集　", "每一步分析结果都落为带血缘的 Parquet 数据集，可继续作为下一步输入。"),
    ("可复用资产　", "确认后的解析器、算法、整套流程模板，沉淀进库供团队复用。"),
])

h2("“可追溯”落到实处是什么样")
para("以一条“传感器去噪”分析为例。用户只说了一句“把这列噪声平滑、标出异常、再做归一化”，系统把它拆成四个明确步骤，"
     "每一步都是一个独立、具名、可复核的节点：上一步的输出，正是下一步的输入。")
flow_diagram([
    ("① 输入数据集", "原始测量"),
    ("② 去噪", "Savitzky-Golay"),
    ("③ 标记异常", "IQR 离群点"),
    ("④ 归一化", "Min-Max"),
    ("⑤ 输出", "带血缘结果集"),
], fill=H_PLIGHT, txt=VERITY, arrow_color=VERITY,
   cap="一条可追溯的分析链路：四个具名步骤首尾相接，每步产出一个带血缘的派生数据集")
para("这条链路的“可追溯”体现在两个层面：")
bullets([
    ("步骤可见　", "每个节点都标明用了哪个方法、什么参数，整条流水线一眼看全，并可一键存为流程模板、换份数据整套复跑。"),
    ("数据可回溯　", "每一步的结果都不是临时变量，而是落库为一个带血缘（lineage）的派生数据集，记录“它由哪个上游数据、经过哪一步算法而来”；于是任一中间结果都能逐级回溯到最初的原始文件。"),
])

callout("为什么这条链条是产品的核心",
        "通用工具在第④步“分析”之后就结束了——给个数字。RLab Cortex 把第④步前后的“读懂—理解”与“呈现—沉淀”同样纳入可追溯范围，"
        "于是“结论可信”不再依赖对模型的信任，而依赖对链路的可复核。这是它区别于通用“聊天分析 CSV”工具的根本所在。",
        fill=H_PLIGHT, bar=H_VERITY, title_color=VERITY)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 05 技术路线
# ════════════════════════════════════════════════════════════════════════════
h1("05", "技术途径与技术路线", color=ACCENT)

para("RLab Cortex 的技术选型，处处围绕两个目标：让“可验证”有工程支撑，让“私有化、易部署”不打折扣。下面从架构、智能体、安全沙箱、性能四个层面展开。")

h2("总体架构")
para("系统是一套前后端分离、可单机起步、可平滑扩容的 Web 应用。各层选型与理由如下：")
table(
    ["层", "技术选型", "选择理由"],
    [
        ["前端", "Next.js 15 + Tailwind + TypeScript", "同源 API、standalone 输出便于打成极小生产容器"],
        ["后端", "FastAPI + SQLAlchemy 2(async) + Pydantic v2", "原生 async（聊天 SSE 流式必需）、强类型、易容器化"],
        ["数据库", "SQLite 默认 → 一行配置切 Postgres", "V1 零运维；规模上来无缝升级"],
        ["对象存储", "本地磁盘 → 可切 S3 / OSS", "V1 一个数据卷即可"],
        ["大模型", "DeepSeek（OpenAI 兼容）默认，支持 BYOK", "同档可信模型里成本低、代码生成强；企业可换任意兼容端点"],
        ["执行沙箱", "python -I 子进程 + AST 白名单 + 资源限额", "跨 Windows/Linux，无需 Docker-in-Docker"],
        ["反向代理", "Nginx", "对 SSE 流式友好，便于前置终止 TLS"],
    ],
    widths=[0.9, 2.7, 2.8], first_col_bold=True,
    cap="总体技术栈选型与选择理由",
)

h2("分层视图")
layer_diagram([
    ("交互层", "Next.js 工作台：对话 · 数据集 · 算法库 · 流程模板 · 反馈 · 设置", H_LIGHT, H_ACCENT),
    ("智能体层", "ReAct 循环：列义理解 · 工具编排 · 代码生成 · 流式事件全程留痕", H_PLIGHT, H_VERITY),
    ("执行层", "内置算法（进程内）｜ 用户/AI 代码（隔离子进程沙箱）", H_LIGHT, H_ACCENT),
    ("数据层", "数据集 · 派生血缘 · 解析器 · 算法 · 流程模板 · 映射规则 · 反馈（全量落库）", H_GREENL, "15803D"),
], cap="系统分层架构：交互 · 智能体 · 执行 · 数据四层")

h2("智能体：一个会编排、会反省的分析循环")
para("对话背后是一个 ReAct（推理—行动）循环：模型每一步返回“想法 + 动作 + 参数”，系统分派执行后把结果喂回，直到给出最终答复。"
     "它具备四个工程化特性，保证运行的稳定与过程的可见：")
bullets([
    ("自动编排流水线　", "同一轮里，一个工具的输出自动接到下一个工具的输入；跨轮对话还会记住上一阶段结果，“再插值一下”会接着上一步而不是回到原始数据。"),
    ("熔断与自愈　", "重复同样的失败会触发熔断（第 2 次告警、第 3 次停止）；模型偶发返回非法 JSON 时，自动尝试重排、再不行回退为文字，不让一次抖动拖垮整轮。"),
    ("全程流式留痕　", "想法、工具调用、工具结果、最终答复逐条通过 SSE 推到前端并持久化，事后可完整重建审计轨迹——“没有沉默的步骤”。"),
    ("工具自省　", "智能体可先列工具、查参数规格，再决定调用哪个，避免“凭空臆造”不存在的工具。"),
])

h2("安全沙箱：让“运行外来代码”可控")
para("自我扩展能力的前提，是能安全地运行用户上传或 AI 生成的代码。RLab Cortex 绝不在 API 进程里执行外来代码，而是落到一个受限子进程里，"
     "两道关卡叠加：")
numbered([
    ("提交时——静态校验：", "AST 白名单只放行 numpy/pandas/scipy/sklearn 等科学计算库；拒绝 open/eval/exec/__import__、双下划线属性访问、socket/urllib 等网络访问；运行时再 monkey-patch 套接字使其抛错。"),
    ("运行时——资源隔离：", "python -I 启动的子进程设 cwd 于临时目录、墙钟超时（默认 30s）、CPU 时间（默认 10s）、内存上限（默认 512MB，POSIX 用 RLIMIT_AS）、输出截断；子进程拿不到大模型密钥等敏感环境变量。"),
])
para("子进程即使崩溃，也只会让父进程上报 status: error，不影响整体服务的稳定。对更高保障级别的部署，技术路线上还将引入 microVM 级隔离。", color=MUTED, size=9.5)

h2("性能特征")
para("下表为单机笔记本环境下的 p50 延迟参考值，实际表现随数据规模与硬件配置而变化：", size=9.5, color=MUTED)
table(
    ["操作", "p50 延迟（参考）"],
    [
        ["内置线性回归（200 样本 × 2 特征）", "< 20 ms"],
        ["内置 Savitzky-Golay 滤波（500 行）", "30–50 ms"],
        ["用户代码沙箱热路径（500 行）", "400–500 ms（子进程启动开销为主）"],
        ["AI 代码生成 + 沙箱测试", "2–5 s（大模型调用为主）"],
        ["10 MB CSV 上传并写 Parquet", "< 500 ms"],
    ],
    widths=[3.6, 2.6], first_col_bold=True, align_center_cols=[1],
    cap="单机环境下典型操作的 p50 延迟参考值",
)

h2("可平滑扩容的部署路线")
flow_diagram([
    ("单机", "SQLite+单 worker"),
    ("百用户", "多 worker"),
    ("千用户", "Postgres+OSS"),
    ("万用户", "沙箱微服务化"),
    ("企业级", "K8s/私有云"),
], fill=H_LIGHT, txt=ACCENT, arrow_color=ACCENT2,
   cap="可平滑扩容的部署路线：从单机到企业级，API 与算法层基本不变")
para("从单机到企业级，API 与算法层基本不动，改动集中在数据库连接串、存储后端与沙箱执行的拆分上——这意味着私有化交付不会推倒重来。",
     color=MUTED, size=9.5)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 06 可扩展性
# ════════════════════════════════════════════════════════════════════════════
h1("06", "可扩展性：如何把它接入你自己的业务")

para("可扩展性是 RLab Cortex 的立身之本，而不是一个附加功能。客户拿过去之后，可以沿四条清晰的路径，把它“长成”自己业务的样子，"
     "且每条路径都不需要改动产品源码。")

h2("路径一　教它读懂你的私有文件格式")
para("当一种导出格式不被原生支持，用户无需写代码：在对话或数据集页里描述这个文件，AI 现场生成一个解析器，先在沙箱里试解析、确认结果无误，"
     "再一键保存为该扩展名的解析适配器（format adapter）。从此团队中任何人再上传同类文件，系统自动套用——教一次，长期复用。")

h2("路径二　把你信赖的算法搬进来")
para("工程师多年积累的 MATLAB / Python 方法，可以直接作为 run(df, **params) 形态的算法上传。它进沙箱通过静态校验与测试报告后，"
     "就成为团队里可被对话调用、可被流程模板编排、可版本化的工具。多年内部 IP 第一次有了统一的“家”，也构成了真正的迁移成本与护城河。")
figure("clean_ai_generate.png", "用 AI 生成算法：用自然语言描述需求，系统按安全工具规范写出 Python 并在沙箱跑通验证，确认后入库", width=6.2)

h2("路径三　把一次成功分析固化为可复用的流程模板")
para("一段跑通的分析对话，可以一键保存为流程模板：它记录有序的步骤（动作 + 算法 + 参数），换一个数据集即可整套复跑，并支持运行时参数覆盖。"
     "模板可在可视化画布（FlowCanvas）上增删、调序、改参，相当于把“某位专家的标准作业流程”做成了人人可用的小应用。")
figure("clean_template_runapp.png", "流程模板的“运行·小程序”模式：把固化的分析流程做成换数据即跑的小应用，非专家也能一键复用", width=6.0)

h2("路径四　接你自己的大模型与算力（BYOK）")
para("企业可在设置里填入自有的 API Key、兼容端点与模型名（Bring Your Own Key），让 RLab Cortex 走你选定的任意 OpenAI 兼容大模型——"
     "无论是自建私有模型、国产模型还是云端商用模型。这既消除了“token 账单失控”的采购顾虑，也满足数据与模型都不出内网的合规要求。")
figure("clean_byok.png", "BYOK 设置：在 DeepSeek / 通义千问 / OpenAI / 任意兼容端点之间切换，填入自有密钥即可走企业选定的大模型", width=6.0)

callout("扩展的安全底线",
        "三条“运行外来逻辑”的路径（自定义解析器、用户算法、AI 生成工具）全部强制经过同一道沙箱关卡——"
        "静态白名单 + 子进程资源隔离。可扩展，但不以牺牲安全为代价。",
        fill=H_LIGHT, bar=H_ACCENT)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 07 功能清单（按模块）
# ════════════════════════════════════════════════════════════════════════════
h1("07", "功能清单（按模块）", color=ACCENT)
para("以下为产品当前已实现的功能全集，按模块组织。所有条目均对应真实可用的能力。")

h2("模块 A　数据接入与数据集管理")
table(["功能", "说明"], [
    ["多格式上传", "CSV / TSV / Excel(多表) / Parquet / JSON 原生支持"],
    ["仿真/网格接入", "CGNS / VTK / STL 网格、Tecplot ASCII 探针数据自动识别"],
    ["自定义解析器", "AI 生成解析器 → 沙箱试解析 → 保存为该扩展名适配器复用"],
    ["Schema 预览", "列名、类型、唯一值数、缺失数、前 N 行预览；类型推断"],
    ["数据血缘 / DAG", "原始 → 派生的操作链全程记录，可逐级回溯"],
    ["派生与回收", "每步结果落为带血缘的 Parquet；派生集宽限期后自动回收，可钉住保留"],
    ["导出", "数据集与结果可导出"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_ACCENT, cap="模块 A：数据接入与数据集管理功能")

h2("模块 B　对话式分析智能体")
table(["功能", "说明"], [
    ["ReAct 推理循环", "想法→动作→结果回灌，最多 8 步，带熔断（2 警告 / 3 停止）"],
    ["8 个智能体动作", "answer / list_tools / describe_tool / run_tool / generate_tool / visualize / visualize_batch / generate_viz"],
    ["自动流水线编排", "同轮工具输出自动接续；跨轮记忆上一阶段（pipeline_state）"],
    ["流式输出与留痕", "想法/调用/结果/答复逐条 SSE 推送并落库，可重建审计轨迹"],
    ["自愈", "非法 JSON 自动重排，2 次失败回退文字，不中断会话"],
    ["一键场景启动器", "内置 DOE 灵敏度 / 平滑 / 频谱 / 聚类等带样例数据的起步问题"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_ACCENT, cap="模块 B：对话式分析智能体功能")

h2("模块 C　算法库（29 个内置算法，6 大类）")
table(["类别", "算法"], [
    ["结构整理（4）", "transpose 转置、derived_column 派生列、drop_columns 删列、group_aggregate 分组聚合"],
    ["预处理（3）", "normalize 归一化、fill_missing 缺失填充、outlier_detect 异常检测(IQR/Z/Dixon)"],
    ["滤波与信号（7）", "moving_average、median_filter、gaussian_filter、savgol_filter、butterworth_filter、fft_frequency_analysis 频谱、find_peaks 寻峰"],
    ["回归与拟合（5）", "linear_regression、polynomial_regression、curve_fit(指数/对数/幂/sigmoid)、correlation(Pearson/Spearman/Kendall)、interpolate(线性/三次/RBF…)"],
    ["降维与分析（3）", "pca(线性/核 PCA)、sensitivity 灵敏度排序(相关/Morris/方差)、kmeans_cluster 聚类"],
], widths=[1.5, 4.7], first_col_bold=True, accent=H_VERITY, cap="模块 C：内置算法库（29 个算法，6 大类）")
para("注：分类按算法功能归并，合计 29 个内置算法；用户自带与 AI 生成的算法不在此列，会随使用持续增长。", size=9, color=MUTED)
figure("30_algo_library.png", "算法库：29 个内置算法按类别（滤波 / 回归拟合 / 降维 / 结构 / 预处理）浏览，可在线配参、试运行、存为模板", width=6.0)

h2("模块 D　自我扩展（自带代码 / AI 生成 / 沙箱）")
table(["功能", "说明"], [
    ["上传自有算法", "run(df, **params)+META 形态，静态校验 + 测试报告通过后入库"],
    ["AI 现场生成", "描述需求 → 生成算法/解析器/图表代码 → 沙箱测试 → 确认入库"],
    ["AI 辅助修复/解释", "自动修错(autofix)、参数建议、错误解释、结果解释"],
    ["静态校验", "AST 白名单库、禁危险内建与属性、禁网络访问"],
    ["运行时隔离", "子进程 + 墙钟/CPU/内存限额 + 输出截断 + 密钥隔离"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_ACCENT, cap="模块 D：自我扩展与安全沙箱功能")

h2("模块 E　可视化")
table(["功能", "说明"], [
    ["内置交互图表", "折线 / 散点 / 柱状，支持客户端切换 x/y/系列、点数下采样"],
    ["AI 生成图表", "雷达/极坐标、热力、等高线、3D 曲面/散点、箱线/小提琴、平行坐标、桑基等任意 Plotly 图"],
    ["多数据集叠加", "同列指标跨多个数据集叠加于一图对比"],
    ["批量出图", "按数据集或按列批量生成多图"],
    ["3D / 网格查看", "MeshViewer3D 渲染 VTK 网格"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_ACCENT, cap="模块 E：可视化功能")

h2("模块 F　流程模板（可复用分析小应用）")
table(["功能", "说明"], [
    ["保存为模板", "把一段对话流程固化为有序步骤（动作+算法+参数）"],
    ["可视化画布编辑", "FlowCanvas 增删/调序/改参"],
    ["一键复跑", "换数据集即整套重跑，支持运行时参数覆盖"],
    ["中间物化与血缘", "每步可选物化为派生数据集，自动识别报告型输出不参与续接"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_VERITY, cap="模块 F：流程模板功能")

h2("模块 G　知识沉淀与反馈回路")
table(["功能", "说明"], [
    ["应用内一键反馈", "右下角常驻，分 做不到/做错了/不敢信/想法 四类，自动带上下文与截图"],
    ["管理员收件箱", "按状态(待处理/已查看/已完成)与类型筛选、分流、跳回上下文"],
    ["列义映射规则", "把“U(V)→电压”这类规则沉淀；支持归一化/精确/包含/正则匹配，记命中数"],
    ["候选→晋升回路", "反馈作为候选知识，可晋升为映射规则/新算法/新模板（建设中）"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_ACCENT, cap="模块 G：知识沉淀与反馈回路功能")

h2("模块 H　账户、权限与大模型接入")
table(["功能", "说明"], [
    ["注册 / 登录", "邮箱+密码，Bcrypt + JWT(HS256)，默认 7 天有效"],
    ["多租户隔离", "算法、设置、反馈按 owner 隔离；可标记公开共享"],
    ["管理员", "查看全部反馈、公共算法，进行分流"],
    ["BYOK", "自填 api_key / base_url / model，切换任意 OpenAI 兼容大模型"],
    ["多模型支持", "DeepSeek 默认，兼容自建/国产/云端商用模型"],
], widths=[1.7, 4.5], first_col_bold=True, accent=H_ACCENT, cap="模块 H：账户、权限与大模型接入功能")

para("界面上，以上能力组织为「对话 / 数据集 / 算法库 / 流程模板 / 反馈收件箱(管理员) / 设置」六个主视图，"
     "外加常驻的反馈按钮，导航清晰、彼此联动。", size=9.5, color=MUTED)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 08 服务方式
# ════════════════════════════════════════════════════════════════════════════
h1("08", "产品与服务方式")

para("RLab Cortex 既可作为开箱即用的在线服务，也可整套私有化交付。我们按团队规模与合规要求提供分层版本，并以“产品 + 服务”双轮驱动落地。")

h2("版本分层")
table(
    ["版本", "面向", "核心内容"],
    [
        ["免费版", "个人 / 试用", "内置算法库、基本用量额度、支持 BYOK、单用户"],
        ["专业版", "独立工程师 / 小团队", "AI 代码生成、保存与版本化自有算法、结果历史、更高用量"],
        ["团队版", "实验室 / 部门", "共享算法库、流程模板共享、计划任务、审计日志、优先沙箱队列"],
        ["企业版", "OEM / 大型客户", "私有化/本地部署、SSO/RBAC、垂直算法包、专属交付工程师、SLA"],
    ],
    widths=[1.0, 1.7, 3.5], first_col_bold=True, accent=H_VERITY,
    cap="RLab Cortex 版本分层与核心内容",
)
para("计费采用“席位 + 用量”的混合模式，BYOK 作为企业级解锁项；具体报价按部署形态与规模面议。", size=9.5, color=MUTED)

h2("服务内容")
bullets([
    ("私有化部署　", "提供从单机 Compose 到 Kubernetes 的部署方案，数据与模型均可不出内网；支持国内云（阿里云 / 腾讯云）与离线环境。"),
    ("定制化开发　", "按客户业务定制专属解析器、垂直算法包（如电池包 / CFD 包）、专属流程模板与界面集成，作为交付物沉淀给客户。"),
    ("数据接入实施　", "协助打通客户现有的循环仪 / 采集系统 / 求解器导出，完成首批格式适配与样例流程搭建。"),
    ("培训与赋能　", "面向工程师的上手培训与“把私有脚本变成团队工具”的迁移工作坊，帮助团队自运转。"),
    ("售后支持　", "企业版提供 SLA 保障、版本升级、问题响应与专属技术对接人；应用内反馈通道直达，问题可带上下文一键提交。"),
    ("持续演进　", "客户的高频纠正与需求，经反馈回路沉淀，反哺产品垂直能力的持续增强。"),
])

callout("交付即资产",
        "我们交付的不只是一套软件，而是一套“会随你团队一起变厚”的能力容器：定制的解析器、算法与流程模板，都会作为可继承的资产留在客户侧。",
        fill=H_PLIGHT, bar=H_VERITY, title_color=VERITY)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 09 案例
# ════════════════════════════════════════════════════════════════════════════
h1("09", "应用案例", color=ACCENT)
para("以下两个案例分别取自产品锁定的两类客户，展示同一套“可验证 + 自我扩展”内核如何贴合各自痛点。案例为代表性工作流，所用方法与图表均对应产品真实能力。")

h2("案例一　电池测试：从多厂商循环数据到可复核的容量衰减结论")
h3("客户痛点")
para("某电芯研发团队在新化学体系试制中，同时使用 Maccor 与 Neware 循环仪，导出格式不一；dV/dQ 微分容量分析依赖一位博士的私人 MATLAB 脚本，"
     "组内其他人既看不懂也不敢直接用，评审时只能“相信他”。")
h3("用 RLab Cortex 的做法")
numbered([
    "把两台循环仪的导出文件直接拖入——格式不匹配的那台，让 AI 生成解析器并确认，保存适配器，后续自动套用。",
    "在对话里要求“对电压-容量曲线做保峰平滑，再求 dV/dQ 并标出特征峰”，智能体自动选用 Savitzky-Golay 滤波 + 寻峰，输出带峰位的曲线。",
    "继续追问“用容量衰减模型拟合循环-容量数据，给出衰减速率与拟合优度”，调用曲线拟合返回参数、R²、RMSE。",
    "把这一整套保存为流程模板；下一批电芯数据进来，一键复跑，全员可用。",
])
h3("结果")
para("原先以半天计的“整理 + 分析”工作被显著压缩（具体随数据规模而定）；更关键的是，结论附带完整可追溯链路——评审从“相信某个人”转为“复核这条流程”，"
     "那位博士的经验也第一次沉淀为团队可继承的模板。")
figure("clean_dataset_chart.png", "测量数据接入后自动识别字段、绘制多通道时序曲线（含电压通道 voltage_v），并给出字段结构概览", width=6.0)

h2("案例二　CFD / CAE：参数化 DOE 后处理与灵敏度排序")
h3("客户痛点")
para("某气动团队做翼型参数化研究，跑了数十组 DOE 算例，导出一张含厚度、弯度、迎角、后掠角等设计变量与阻力、升力、质量等响应的大表。"
     "“到底哪个参数对阻力影响最大、哪个其实没用”，过去靠 Tecplot 脚本加手工画图，繁琐且难以复用，向上汇报还要再拼 PPT。")
h3("用 RLab Cortex 的做法")
numbered([
    "把 DOE 结果表拖入，直接问“这些设计参数里，哪个对阻力 drag 影响最大、哪个其实没什么用？”。",
    "智能体自行判断哪些列是输入、哪列是输出，调用灵敏度分析给出排序，并指出最关键的两个因素。",
    "进一步要求“画出关键参数与阻力的关系，并把升力、阻力、质量做成一张对比图”，自动产出多图。",
    "把分析固化为模板；下一轮 DOE 算例只需替换数据集即可复跑同一套后处理。",
])
h3("结果")
para("后处理从“写脚本 + 手工拼图”变成一次对话；灵敏度结论清晰可复核，多算例对比与汇报图一步到位，参数研究的迭代节奏随之加快。"
     "下图为灵敏度排序的示意结果：在该 DOE 数据上，迎角与厚度是阻力的主导因素，后掠角的影响几乎可以忽略。")
bar_chart([
    ("迎角 aoa", 0.82, "影响度 0.82"),
    ("厚度 thickness", 0.41, "0.41"),
    ("弯度 camber", 0.12, "0.12"),
    ("后掠角 sweep", 0.04, "0.04"),
], cap="CFD 案例（示意）：灵敏度分析按对阻力 drag 的影响度对设计参数排序——迎角、厚度主导，后掠角几乎无影响")

callout("两个案例，同一个内核",
        "电池与 CFD 表面是两回事，但痛点同构：数据读不进、方法锁在个人手里、结论不敢信。RLab Cortex 用同一套“可验证 + 自我扩展”内核同时命中——"
        "这正是它能从一个垂直场景平滑复制到下一个场景的基础。",
        fill=H_LIGHT, bar=H_ACCENT)

page_break()

# ════════════════════════════════════════════════════════════════════════════
# 10 未来
# ════════════════════════════════════════════════════════════════════════════
h1("10", "未来发展方向")

para("RLab Cortex 的演进有一条清晰主线：让“可验证”更深、让“自我扩展”更自动、让沉淀的资产形成跨团队复利。")

h2("产品路线图")
table(
    ["阶段", "重点方向"],
    [
        ["近期", "电池包(Battery Pack)：Maccor/Arbin/Neware 解析器 + dV/dQ·ICA·GITT 求解器成套；激活算法跨用户继承（is_public）"],
        ["中期", "团队版正式发布：共享算法库、计划任务、审计日志；存储与数据库切换到 Postgres + S3/OSS"],
        ["后续", "CFD 包：OpenFOAM/Fluent 解析、DOE 后处理成套；上架云市场（阿里云 / 腾讯云 / AWS）"],
        ["企业化", "企业包：VPC / SSO / 审计；更强沙箱隔离（microVM 级）"],
        ["第三场景", "NVH / 耐久测试包：把垂直复制的方法论推向第三个领域"],
    ],
    widths=[1.0, 5.2], first_col_bold=True, accent=H_VERITY,
    cap="产品演进路线图",
)

h2("能力演进的三个方向")
bullets([
    ("判断类知识的沉淀回路　", "目前解析器、算法、流程模板三类“可执行知识”已能沉淀；下一步是把“某列其实是电压、某阈值算异常、某结果看着对”这类专家判断，"
     "经“候选 → 评审 → 晋升”回路沉淀为可继承资产——这是产品最核心的竞争壁垒。"),
    ("失败驱动的改进回路　", "把产品自身反复出错的地方（解析失败、列选错、阈值被改、结果被否）作为改进的稳定来源：专家一次纠正，团队整体持续受益，"
     "让 AI 在本垂直领域的成功率随使用稳步提升。"),
    ("更强的隔离与合规　", "面向国防/航空等敏感电池数据场景，提供更高保障级别的隔离与本地化部署，把“可信”从结论层延伸到运行环境层。"),
])

callout("北极星",
        "RLab Cortex 不追求做“一个更聪明的 AI”，而是做一个能把专家经验装进去、让非专家也能信任使用的「容器」。"
        "每一次专家的使用与纠正，都让这个容器对下一个用户更可靠——这就是我们要建的知识飞轮。",
        fill=H_PLIGHT, bar=H_VERITY, title_color=VERITY)

# closing
doc.add_paragraph().paragraph_format.space_after = Pt(8)
cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
_hrule(cp, color=H_LINE, sz=6)
end = doc.add_paragraph(); end.alignment = WD_ALIGN_PARAGRAPH.CENTER
run(end, "RLab · Cortex 智能体矩阵　｜　RLab Cortex 可验证数据分析智能体", size=9, color=MUTED)
end2 = doc.add_paragraph(); end2.alignment = WD_ALIGN_PARAGRAPH.CENTER; end2.paragraph_format.space_after = Pt(0)
run(end2, "本白皮书内容对应产品真实能力 ｜ v1.0 ｜ 2026-06", size=8.5, color=FAINT, italic=True)

try:
    doc.save(OUT)
    saved = OUT
except PermissionError:
    saved = os.path.join(os.path.dirname(OUT), "RLab_Cortex_产品白皮书_修订版.docx")
    doc.save(saved)
    print("WARN: 原文件被占用（Word 已打开），已另存为修订版。")
print("SAVED:", saved)
print("paragraphs:", len(doc.paragraphs), " figures:", _fig_n[0], " tables(题注):", _tab_n[0])
