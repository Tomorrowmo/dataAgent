# -*- coding: utf-8 -*-
"""Generate the software-copyright (软著) OPERATION MANUAL (.docx) for
「ROMTEK 工程数据智能分析软件」(简称 RLab Cortex).

软著文档要求导向：详细的登录界面、连贯的操作步骤截图 + 文字描述、体现数据的变化，
截图与文字中的软件名称与申请表一致（申请表全称 = ROMTEK 工程数据智能分析软件；界面
显示简称 RLab Cortex，文档首页明确声明二者为同一软件）。

Run:  python tools/gen_ruanzhu_manual.py
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
OUT = os.path.join(ROOT, "docs", "pitch", "ROMTEK_工程数据智能分析软件_操作手册.docx")

FULLNAME = "ROMTEK 工程数据智能分析软件"
SHORT = "RLab Cortex"

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
        run(p, f"{i}. ", size=10.5, color=ACCENT, bold=True)
        if isinstance(it, tuple):
            run(p, it[0], bold=True); run(p, it[1])
        else:
            run(p, it)

_fig = [0]; _tab = [0]
def _seq(par, name, n, color=FAINT):
    r = par.add_run(); rr = r._r
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'begin'); rr.append(e)
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
    bio = BytesIO(); im.save(bio, format="PNG"); bio.seek(0)
    return bio

def figure(filename, caption, width=6.1):
    path = os.path.join(ASSETS, filename)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(6); p.paragraph_format.space_after = Pt(2)
    if os.path.exists(path):
        p.add_run().add_picture(_img(path), width=Inches(width))
    else:
        run(p, f"[缺图: {filename}]", color=FAINT, italic=True)
    figcap(caption)

def pb():
    doc.add_page_break()

NAME = FULLNAME  # 正文首次引入后改用简称，见 §1

# ════════════════════════════════════════════════════════ COVER
doc.add_paragraph().paragraph_format.space_after = Pt(30)
eb = doc.add_paragraph(); run(eb, "软件著作权登记 · 操作手册（使用说明书）", size=11, color=ACCENT, bold=True); eb.paragraph_format.space_after = Pt(8)
tp = doc.add_paragraph(); tp.paragraph_format.space_after = Pt(2); run(tp, FULLNAME, size=26, color=VERITY, bold=True)
st = doc.add_paragraph(); st.paragraph_format.space_after = Pt(4); run(st, "操作手册", size=20, color=INK, bold=True); _hrule(st, color=H_VERITY, sz=14)
sub = doc.add_paragraph(); sub.paragraph_format.space_before = Pt(8); sub.paragraph_format.space_after = Pt(4)
run(sub, "简称：", size=12, color=MUTED); run(sub, SHORT, size=12, color=INK, bold=True)
run(sub, "（软件运行界面显示英文简称 “RLab Cortex”）", size=10, color=FAINT)
tl = doc.add_paragraph(); tl.paragraph_format.space_before = Pt(8); tl.paragraph_format.space_after = Pt(18); tl.paragraph_format.line_spacing = 1.6
run(tl, "本手册按“登录 → 上传数据 → 对话分析 → 组成流水线 → 出图与结论 → 扩展与复用”的真实操作顺序，"
        "配以完整界面截图与文字说明，体现每一步的数据变化，供软件使用与登记参考。", size=11.5, color=MUTED)
figure("clean_login.png", f"{FULLNAME}（{SHORT}）登录界面", width=6.0)
mt = doc.add_table(rows=1, cols=2); _no_borders(mt); mt.alignment = WD_TABLE_ALIGNMENT.CENTER; _widths(mt, [3.2, 3.2])
for cell, items in ((mt.rows[0].cells[0], [("软件全称", FULLNAME), ("软件简称", SHORT), ("软件形态", "B/S 架构 Web 应用，可私有化部署")]),
                    (mt.rows[0].cells[1], [("适用对象", "工程师 / 科研与测试人员"), ("开发语言", "Python（后端）/ TypeScript（前端）"), ("文档版本", "V1.0")])):
    first = True
    for k, v in items:
        p = cell.paragraphs[0] if first else cell.add_paragraph(); first = False
        p.paragraph_format.space_after = Pt(5); p.paragraph_format.line_spacing = 1.3
        run(p, f"{k}　", size=9, color=FAINT, bold=True); run(p, v, size=9.5)
pb()

# ════════════════════════════════════════════════════════ 名称声明 + TOC
h1("", "软件名称说明", color=ACCENT)
callout("名称一致性声明",
        f"本软件全称为「{FULLNAME}」，简称「{SHORT}」。软件运行界面中统一显示英文简称 “{SHORT}”。"
        f"本操作手册中出现的 “{SHORT}” 与「{FULLNAME}」为同一软件的不同称谓，与软件著作权申请表所填软件名称一致。"
        "为行文简洁，下文正文多以简称指代本软件。",
        fill=H_PLIGHT, bar=H_VERITY, tcolor=VERITY)

ht = doc.add_paragraph(); ht.paragraph_format.space_before = Pt(10); run(ht, "目　录", size=16, color=VERITY, bold=True); _hrule(ht, color=H_VERITY, sz=10); ht.paragraph_format.space_after = Pt(6)
for it in [
    "01　软件简介与技术架构", "02　运行环境与部署", "03　登录与账号", "04　主界面与功能导航",
    "05　完整操作实录（一）：上传数据与自动首读", "06　完整操作实录（二）：对话式分析与出图",
    "07　完整操作实录（三）：自动分析流水线与数据血缘", "08　完整操作实录（四）：灵敏度分析与高级图表",
    "09　算法库与算法调用", "10　扩展算法：AI 生成 / 自带代码与安全沙箱", "11　流程模板（可复用小应用）",
    "12　设置与大模型（BYOK）", "13　反馈、版本与产品文档", "14　常见问题（FAQ）", "附录　内置算法速查表",
]:
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(4); p.paragraph_format.left_indent = Cm(0.3); run(p, it, size=11)
pb()

# ════════════════════════════════════════════════════════ 01 简介与架构
h1("01", "软件简介与技术架构")
para(f"{FULLNAME}（简称 {SHORT}，下同）是一款面向工程师与科研人员的可验证工程数据分析软件。"
     "用户把任意格式的工程数据导入软件，由内置的分析智能体自动读懂数据、选择合适的算法完成分析，"
     "并输出可交互图表与带数值的结论；分析过程中的每一步解析、算法与参数都被完整记录、可回放、可复算，"
     "并能沉淀为可复用的算法与流程模板。")
h2("软件定位与主要特点")
bullets([
    ("对话式分析　", "以自然语言驱动分析：用户只描述意图（如“平滑这列噪声”“哪个参数影响最大”），软件自动完成理解、选工具、执行、出图。"),
    ("可验证、可追溯　", "每一步分析都留有来历（用了哪个数据、哪一步算法、什么参数），结果可回放、可复算、可逐级回溯到原始文件。"),
    ("自我扩展　", "支持上传用户自有算法，或由 AI 现场生成新算法/解析器/图表；外来代码先经安全沙箱验证后方可入库复用。"),
    ("可私有化部署　", "采用前后端分离的 B/S 架构，可从单机部署平滑扩容到服务器/集群，数据与模型可不出内网。"),
])
h2("软件总体结构")
para("软件采用前后端分离的 B/S（浏览器/服务器）架构，自上而下分为四层：")
table(["层次", "主要模块", "职责"], [
    ["交互层（前端）", "工作台：对话 / 数据集 / 算法库 / 流程模板 / 设置", "用户操作界面，Web 浏览器访问"],
    ["智能体层", "推理循环、列义理解、工具编排、代码生成、流式事件", "把自然语言意图转化为具体的分析动作序列"],
    ["执行层", "内置算法引擎、用户/AI 代码安全沙箱", "内置算法进程内执行；外来代码在隔离子进程执行"],
    ["数据层", "数据集、派生血缘、解析器、算法、流程模板、映射规则、反馈", "全量持久化，支撑可追溯与资产沉淀"],
], widths=[1.3, 2.6, 2.5], cap="软件总体四层结构")
h2("主要功能模块")
table(["模块", "功能说明"], [
    ["数据接入与数据集管理", "多格式上传、自动首读 Profile、字段结构、数据血缘、派生与导出"],
    ["对话式分析智能体", "自然语言提问、自动选数据/选算法/执行、流水线编排、全程留痕"],
    ["算法库", "29 个内置算法按类别浏览、在线配参与试运行"],
    ["算法扩展与安全沙箱", "上传自有算法、AI 生成算法/解析器，静态校验 + 子进程资源隔离"],
    ["流程模板", "把跑通的分析固化为可复跑的“运行·小程序”"],
    ["可视化", "内置交互图表 + AI 生成的高级图表（雷达/极坐标/热力/3D 等）"],
    ["系统设置", "大模型 BYOK 配置、账号信息、版本与更新日志"],
], widths=[2.0, 4.2], cap="软件主要功能模块")
pb()

# ════════════════════════════════════════════════════════ 02 运行环境
h1("02", "运行环境与部署", color=ACCENT)
h2("运行环境要求")
table(["项目", "要求"], [
    ["服务器操作系统", "Linux（Ubuntu / CentOS 等）或 Windows；支持容器化部署"],
    ["运行时", "Python 3.11+（后端）、Node.js 18+（前端构建）"],
    ["数据库", "默认 SQLite（零运维）；可切换 PostgreSQL"],
    ["客户端", "现代浏览器（Chrome / Edge / Firefox 等），无需安装插件"],
    ["大模型", "内置默认模型即可运行；可通过 BYOK 接入任意 OpenAI 兼容大模型"],
], widths=[1.8, 4.4], cap="软件运行环境要求")
h2("启动与访问")
steps([
    ("启动后端服务　", "在服务器上启动后端（默认监听 8077 端口），提供数据、算法、对话等接口。"),
    ("启动前端服务　", "启动前端 Web 服务（默认 3000 端口），由反向代理统一对外提供访问。"),
    ("浏览器访问　", "在浏览器中打开软件地址，进入登录界面即可开始使用。"),
])
callout("部署说明", "软件从单机到集群的部署，接口层与算法层基本不变，改动集中在数据库连接、存储后端与沙箱执行的拆分上；"
        "支持数据与模型均不出内网的私有化交付。", fill=H_LIGHT, bar=H_ACCENT)
pb()

# ════════════════════════════════════════════════════════ 03 登录
h1("03", "登录与账号")
para(f"在浏览器中打开软件地址后，进入 {SHORT} 的登录界面（如下图）。界面顶部显示软件名称 “{SHORT}”。")
h2("登录步骤")
steps([
    ("输入账号　", "在“邮箱”输入框中填写已注册的账号邮箱，例如 engineer@romtek.com。"),
    ("输入密码　", "在“密码”输入框中填写登录密码（不少于 6 位）。"),
    ("点击“登录”　", "点击蓝色“登录”按钮提交；验证通过后进入软件工作台主界面。"),
    ("注册新账号　", "若尚无账号，点击“注册一个”进入注册页，填写昵称、邮箱与密码完成注册。"),
])
figure("clean_login.png", f"登录界面：顶部显示软件名称 {SHORT}，填写邮箱与密码后点击“登录”", width=6.0)
callout("说明", f"企业私有化部署时，{SHORT} 还支持接入统一认证中心（OIDC 单点登录）；开启后登录将由企业统一认证中心完成。"
        "本手册以软件内置的账号密码登录方式为例进行说明。", fill=H_LIGHT, bar=H_ACCENT)
pb()

# ════════════════════════════════════════════════════════ 04 主界面
h1("04", "主界面与功能导航", color=ACCENT)
para("登录成功后进入工作台主界面。界面顶部显示软件名称，左侧为图标式主导航栏，中间为当前视图的工作区，"
     "右侧为“工作台”面板，实时显示分析过程的时间线、流程图与数据。")
figure("clean_home.png", f"{SHORT} 工作台主界面：顶部为软件名称，左侧导航，中部工作区，右侧“工作台”面板", width=6.1)
h2("左侧导航的主要视图")
table(["视图", "作用", "在这里做什么"], [
    ["对话", "对话式分析", "用自然语言提问，让软件选数据、选方法、出图"],
    ["数据集", "数据接入与管理", "上传文件、查看字段与血缘、预览与导出"],
    ["算法库", "内置 + 自有 + AI 算法", "浏览内置算法、配参试运行、上传或 AI 生成新算法"],
    ["流程模板", "可复用分析流程", "把跑通的流程存为模板，换数据一键复跑"],
    ["设置", "账号与大模型", "配置大模型（BYOK）、查看版本与产品文档"],
], widths=[1.1, 1.9, 3.4], cap="主界面左侧导航的主要视图")
callout("提示", "界面右下角常驻“反馈”按钮，在任意视图都可提交使用反馈（做不到 / 做错了 / 不敢信 / 想法），"
        "系统会自动附带当前操作上下文。", fill=H_PLIGHT, bar=H_VERITY, tcolor=VERITY)
pb()

# ════════════════════════════════════════════════════════ 05 操作实录一：上传
h1("05", "完整操作实录（一）：上传数据与自动首读")
para("下面以一份传感器测试数据为例，演示从上传数据到得到分析结论的完整、连贯操作过程，并展示每一步的数据变化。")
h2("步骤 1：上传或选择数据集")
steps([
    ("进入“数据集”视图　", "点击左侧导航“数据集”图标。"),
    ("上传文件　", "点击顶部“上传 CSV / XLSX / Parquet”按钮，或将文件直接拖入上传区。软件支持 CSV / Excel（多工作表自动拆分）/ Parquet / JSON，以及 CGNS / VTK / STL 等仿真网格数据。"),
    ("自动首读　", "上传完成后，软件立即对数据进行“首读”，无需人工干预即自动识别：这是什么数据、包含哪些字段、字段类型、取值范围与缺失情况。"),
])
para("如下图，软件读入一份 200 行 × 4 列的传感器时间序列数据后，自动给出字段结构（时间轴 time_s，以及电压 voltage_v、电流 current_a、温度 temp_c 三个测量量），"
     "并在右侧绘制出多通道时序曲线——数据由“一个文件”变成了“可分析、可绘图的结构化数据集”。")
figure("clean_dataset_chart.png", "上传后自动首读：识别字段结构（含电压 voltage_v 等），并绘制多通道时序曲线", width=6.1)
h2("步骤 2：查看字段结构与数据血缘")
bullets([
    ("字段结构　", "列出每个字段的名称、类型、去重值数与缺失数，便于确认数据质量。"),
    ("数据血缘　", "分析产生的每个派生数据集都会记录“由哪个上游数据、经过哪一步算法而来”，可逐级回溯到最初的原始文件。"),
])
pb()

# ════════════════════════════════════════════════════════ 06 操作实录二：对话出图
h1("06", "完整操作实录（二）：对话式分析与出图", color=ACCENT)
para("数据就绪后，进入“对话”视图，用自然语言提出分析需求。软件会自动理解意图、选择合适的算法并执行，"
     "右侧“工作台”会实时显示每一步的想法、工具调用与结果。")
h2("步骤 3：用自然语言提问并生成图表")
steps([
    ("选择数据集　", "在对话界面右上角选择要分析的数据集。"),
    ("输入需求　", "在底部输入框中用大白话描述需求，例如“画一下电压随时间的曲线”，回车发送。"),
    ("软件自动执行　", "软件判断这是一个可视化请求，自动选择 time_s 为横轴、voltage_v 为纵轴，调用可视化工具生成曲线图。"),
    ("查看结果与过程　", "中部对话区显示生成的电压—时间曲线；右侧“工作台”时间线逐条显示 llm_call → 思考 → 工具调用 → 生成图表 → 最终答复的完整过程。"),
])
para("数据变化：从“一列 voltage_v 数值”变成了“一张可交互的电压随时间变化曲线”，"
     "同时软件用自然语言给出结论（如电压在约 0～2.5 秒区间内的变化趋势）。")
figure("op_voltage.png", "对话生成图表：输入“画一下电压随时间的曲线”，软件自动出图，右侧完整记录每一步", width=6.1)
h2("步骤 4：在同一轮里继续追问")
para("可继续追问，如“能不能进行插值”。软件会在上一步结果的基础上继续，先绘制原始数据曲线，"
     "再对数据插值并叠加平滑曲线，形成“原始点 + 插值曲线”的对比图——体现出数据经算法处理后的变化。")
figure("op_curve.png", "对话追问续接：在曲线基础上继续插值，得到“原始数据 vs 插值平滑”的对比图", width=6.1)
pb()

# ════════════════════════════════════════════════════════ 07 操作实录三：流水线 + 血缘
h1("07", "完整操作实录（三）：自动分析流水线与数据血缘")
para("对于多步骤分析，软件会把上一步算法的输出自动接到下一步的输入，组成一条可见、可回放的处理流水线。")
h2("步骤 5：一句话触发多步流水线")
steps([
    ("描述多步需求　", "在对话中输入“去噪 → 检测异常 → 插值 → 归一化”，一次性描述四步处理。"),
    ("自动拆解并串联　", "软件将其拆成有序的具名步骤，上一步的输出数据集自动作为下一步的输入。"),
    ("查看流程图　", "切换右侧“工作台”的“流程图”标签，可看到完整的处理链：数据集 → 去噪 → 检测异常 →（插值）→ 归一化 → 输出，每个节点标注所用算法与参数。"),
])
para("数据变化：原始数据依次经过“平滑去噪 → 标记异常 → 插值 → 归一化”，每一步都生成一个带血缘的派生数据集，"
     "数据的行列结构与数值随之改变，且每一步的来历都被完整记录。")
figure("op_pipeline.png", "自动分析流水线（流程图）：上一步输出自动成为下一步输入，各节点标注算法与参数", width=6.1)
h2("步骤 6：数据血缘的逐级回溯")
para("在“数据集”视图中，每个派生数据集都挂在其来源数据之下，形成血缘树。如下图，"
     "由“示例·参数优化DOE”经 Savitzky-Golay 滤波派生出的中间结果，明确记录了“从哪来、经过哪一步”，可逐级回溯到原始数据。")
figure("op_lineage.png", "数据血缘：派生数据集记录“从哪来、经过哪几步”，可逐级回溯到原始文件", width=6.1)
pb()

# ════════════════════════════════════════════════════════ 08 操作实录四：灵敏度 + 高级图
h1("08", "完整操作实录（四）：灵敏度分析与高级图表", color=ACCENT)
h2("步骤 7：灵敏度分析——找出影响最大的因素")
para("对于包含多个输入参数与一个输出的工程数据，可直接提问“这些参数里哪个对结果影响最大？”。"
     "软件自动识别输入/输出列，运行灵敏度分析，并按影响程度排序输出。")
para("如下图，针对一份计算流体力学（CFD）仿真数据，软件对 “Temperature_Correction” 影响最大的因素给出排序："
     "X-Velocity_Correction（敏感度 0.857）、Y-Velocity_Correction（0.513）、Z-Velocity_Correction（0.372）等，"
     "并指出最关键的两个因素——数据由“一张宽表”变成了“带数值的因素重要性排序结论”，同时结果另存为新的派生数据集。")
figure("op_sensitivity.png", "灵敏度分析：自动识别输入/输出并按影响程度排序，结果另存为派生数据集", width=6.1)
h2("步骤 8：生成高级图表")
para("除折线、散点、柱状等基础图表外，软件还能按需生成雷达图、极坐标图、热力图、3D 曲面等高级图形。")
figure("op_polar.png", "高级图表（一）：由对话生成的极坐标图", width=5.7)
figure("op_radar.png", "高级图表（二）：一次生成多张对比图（归一化折线 + 雷达图），用于多响应量对比", width=6.1)
pb()

# ════════════════════════════════════════════════════════ 09 算法库
h1("09", "算法库与算法调用")
para("除对话式自动选算法外，用户也可在“算法库”中手动浏览、配参并运行算法。算法库收录 29 个内置算法，按类别组织，详见文末附录。")
figure("30_algo_library.png", "算法库：内置算法按类别浏览，可在线配参、试运行、存为模板", width=6.1)
h2("手动调用算法的步骤")
steps([
    ("进入“算法库”　", "点击左侧导航“算法库”，按类别（滤波 / 回归拟合 / 降维 / 预处理 / 结构整理）筛选。"),
    ("选择算法　", "点击某个算法（如 Savitzky-Golay 平滑），右侧展开参数表单。"),
    ("填写参数并选数据　", "填写算法参数（不确定时可由 AI 根据数据与意图建议参数），选择要处理的数据集。"),
    ("运行并查看结果　", "点击运行，查看结果摘要（如 R²、RMSE、主频、解释方差等）；满意后可存为流程模板。"),
])
table(["类别", "包含算法"], [
    ["结构整理（4）", "转置、派生列、删列、分组聚合"],
    ["预处理（3）", "归一化、缺失填充、异常检测（IQR / Z-score / Dixon）"],
    ["滤波与信号（7）", "巴特沃斯 / 高斯 / 中值 / 移动平均 / Savitzky-Golay 滤波、FFT 频谱、寻峰"],
    ["回归与拟合（5）", "线性 / 多项式回归、曲线拟合、相关性、插值（含 RBF）"],
    ["降维与分析（3）", "PCA（线性 / 核）、灵敏度排序、K-means 聚类"],
], widths=[1.5, 4.7], accent=H_VERITY, cap="内置算法六大类别（合计 29 个）")
pb()

# ════════════════════════════════════════════════════════ 10 扩展算法
h1("10", "扩展算法：AI 生成 / 自带代码与安全沙箱", color=ACCENT)
para(f"{SHORT} 可以“自我扩展”：把用户信赖的代码搬进来，或由 AI 现场生成新工具。所有外来代码都先经安全沙箱验证，再成为可复用的能力。")
h2("途径一：用 AI 生成算法")
steps([
    ("进入 “算法库 → 用 AI 生成”　", "在输入框中用自然语言描述需求，例如“用准随机采样计算 y 对 x1、x2、x3 的一阶 Sobol 指数”。"),
    ("生成并沙箱验证　", "软件按安全工具规范写出 Python 代码，并在沙箱中试运行验证其可用性。"),
    ("确认入库　", "用户确认结果无误后，算法保存入库，即可在对话与流程模板中复用。"),
])
figure("clean_ai_generate.png", "用 AI 生成算法：描述需求 → 生成 Python → 沙箱跑通验证 → 确认入库", width=6.1)
h2("途径二：上传自有算法")
para("用户可把自己的 Python 方法整理为 run(df, **params) 形态上传；通过静态校验与测试后入库，即可在对话中调用、被流程模板编排并版本化。")
h2("安全沙箱")
bullets([
    ("静态校验　", "只放行 numpy / pandas / scipy / sklearn 等科学计算库；禁用文件、网络访问与危险内建函数。"),
    ("运行时隔离　", "外来代码在独立子进程中执行，设有墙钟超时、CPU 时间与内存上限、输出截断；大模型密钥对沙箱不可见。"),
    ("失败隔离　", "子进程即使异常，也只上报错误状态，不影响主服务稳定。"),
])
pb()

# ════════════════════════════════════════════════════════ 11 流程模板
h1("11", "流程模板（可复用小应用）")
para("把一段跑通的分析固化为流程模板后，换一份数据即可整套复跑——相当于把“某位专家的标准作业流程”做成人人可用的小应用。")
h2("操作步骤")
steps([
    ("保存为模板　", "在对话或算法库里跑通一段分析后，将其保存为流程模板（记录有序的步骤：动作 + 算法 + 参数）。"),
    ("编辑流程　", "在“流程模板”视图中，用可视化画布增删步骤、调整顺序、修改参数。"),
    ("运行·小程序　", "切换到“运行·小程序”模式，选择数据集、按需覆盖运行时参数，点“运行”即可整套复跑。"),
])
para("如下图，“【示例】传感器测试数据·标准去噪流水线”被做成一个小应用：非专业用户只需选择数据、点“运行”，"
     "即可复跑“去噪 → 标异常 → 归一化”整条流程，并看到可信的处理过程。")
figure("clean_template_runapp.png", "流程模板“运行·小程序”：选数据、点运行即整套复跑，非专家也能一键复用", width=6.1)
pb()

# ════════════════════════════════════════════════════════ 12 设置 BYOK
h1("12", "设置与大模型（BYOK）", color=ACCENT)
para(f"{SHORT} 默认使用内置大模型即可工作。若企业希望使用自有的大模型与密钥（数据与模型不出内网、或控制成本），"
     "可在“设置”中配置 BYOK（Bring Your Own Key，自带密钥）。")
h2("配置步骤")
steps([
    ("进入设置　", "点击左侧导航“设置”，找到“LLM 服务商（自带 Key）”。"),
    ("选择服务商　", "在 DeepSeek、通义千问（DashScope）、OpenAI，或 Custom（任意 OpenAI 兼容端点）中选择。"),
    ("填写端点与模型　", "确认 Base URL，选择或填写模型名。"),
    ("填入密钥并保存　", "填入 API Key（已配置过可留空保持原值），点“保存”。下一条消息即生效，无需重启。"),
])
figure("clean_byok.png", "BYOK 设置：在 DeepSeek / 通义千问 / OpenAI / 任意兼容端点之间切换并填入密钥", width=6.1)
pb()

# ════════════════════════════════════════════════════════ 13 反馈/版本
h1("13", "反馈、版本与产品文档")
h2("提交反馈")
para("点击界面右下角“反馈”按钮，选择一类（做不到 / 做错了 / 不敢信 / 想法），填写一句说明后发送；"
     "系统会自动附带当前视图、会话、数据集与运行上下文，便于定位与改进。")
h2("查看版本与更新日志")
para("左侧导航栏底部常驻当前版本号；点击它或进入“设置 → 关于”，可查看当前版本与更新日志（本版相比上一版的新增、优化与修复）。")
h2("下载产品文档")
para("在“设置 → 关于 → 产品文档”处，可直接下载《操作手册》（本文）与《产品白皮书》。")
pb()

# ════════════════════════════════════════════════════════ 14 FAQ
h1("14", "常见问题（FAQ）", color=ACCENT)
faqs = [
    ("上传的文件格式不被支持怎么办？", "让软件生成自定义解析器：它会试解析并给出预览，用户确认无误后保存为该扩展名的适配器，之后同类文件自动套用。"),
    ("软件选错了列或用错了方法怎么办？", "在对话中直接纠正（如“这列其实是电压”“改用保峰平滑”）；纠正可沉淀为可复用规则，下次自动套用。"),
    ("分析结果可信吗？怎么核对？", "每一步都可回放：用了哪个数据、走了哪几步、每步什么参数。复核这条链路即可，而不必盲信模型。"),
    ("用户的私有算法安全吗？", "外来代码只在隔离子进程中运行，禁用网络与文件访问，设有资源上限，且拿不到大模型密钥。"),
    ("可以私有化部署吗？", "可以。软件支持从单机到集群的部署，数据与模型均可不出内网。"),
    ("如何换成自有大模型？", "见第 12 章 BYOK：在设置中填入自有服务商、端点、模型与密钥即可。"),
]
for q, a in faqs:
    p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(1); p.paragraph_format.space_before = Pt(6)
    run(p, "问　", color=VERITY, bold=True); run(p, q, bold=True)
    pa = doc.add_paragraph(); pa.paragraph_format.space_after = Pt(5); pa.paragraph_format.left_indent = Cm(0.7); pa.paragraph_format.line_spacing = 1.45
    run(pa, "答　", color=ACCENT, bold=True); run(pa, a)
pb()

# ════════════════════════════════════════════════════════ 附录
h1("附录", "内置算法速查表", color=ACCENT)
para("下表为 29 个内置算法速查（slug 为软件内部标识）。用户上传与 AI 生成的算法会随使用持续增加，不在此列。")
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
run(end, f"{FULLNAME}（{SHORT}）操作手册 · V1.0", size=9, color=MUTED)

try:
    doc.save(OUT); saved = OUT
except PermissionError:
    saved = os.path.join(os.path.dirname(OUT), "ROMTEK_工程数据智能分析软件_操作手册_修订版.docx"); doc.save(saved)
    print("WARN: 原文件被占用，已另存修订版。")
print("SAVED:", saved)
print("figures:", _fig[0], "tables:", _tab[0])
