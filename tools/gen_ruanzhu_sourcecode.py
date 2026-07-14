# -*- coding: utf-8 -*-
"""Concatenate a representative ~3000-line slice of the software's real source
code into a .txt for software-copyright (软著) submission.

- 登录界面代码（含产品简称 RLab Cortex）置于最前。
- 每个文件前有「文件名标头」，两个文件之间用一行 em-dash「————…」分隔，
  便于定位每个文件的头和尾。
- 约 3000 行代码（≈ Word 每页 50 行 × 60 页）。UTF-8 (BOM) 便于 Word 正确显示中文。

Run:  python tools/gen_ruanzhu_sourcecode.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "pitch", "RLab_Cortex_源代码_软著.txt")

FULLNAME = "ROMTEK 工程数据智能分析软件"
SHORT = "RLab Cortex"

# 精选的核心源码文件（登录界面在最前）。相对仓库根目录。
FILES = [
    # —— 前端：登录 / 注册 / 界面（界面显示产品简称 RLab Cortex）——
    ("web/app/login/page.tsx",                    "前端·登录界面（显示产品简称 RLab Cortex）"),
    ("web/app/signup/page.tsx",                   "前端·注册界面"),
    ("web/app/layout.tsx",                        "前端·应用外壳（页面标题 RLab Cortex）"),
    ("web/components/Sidebar.tsx",                "前端·主导航侧栏"),
    ("web/components/SettingsView.tsx",           "前端·系统设置（大模型 BYOK）"),
    # —— 后端：入口 / 配置 / 鉴权 / 数据模型 ——
    ("backend/app/main.py",                       "后端·应用入口与路由装配"),
    ("backend/app/core/config.py",                "后端·全局配置"),
    ("backend/app/core/security.py",              "后端·安全与 JWT 令牌"),
    ("backend/app/api/auth.py",                   "后端·登录/注册接口"),
    ("backend/app/db/models.py",                  "后端·数据库数据模型"),
    # —— 后端：代码生成与安全沙箱（核心 IP）——
    ("backend/app/services/codegen.py",           "后端·AI 代码生成"),
    ("backend/app/sandbox/validator.py",          "后端·外来代码静态校验"),
    ("backend/app/sandbox/executor.py",           "后端·安全沙箱执行器"),
    ("backend/app/sandbox/runner_worker.py",      "后端·沙箱子进程 worker"),
    # —— 后端：算法库 ——
    ("backend/app/algorithms/registry.py",        "后端·算法注册表"),
    ("backend/app/algorithms/builtins_regression.py", "后端·回归与拟合算法"),
    ("backend/app/algorithms/builtins_preprocess.py", "后端·数据预处理算法"),
]

SEP = "—" * 64  # 文件之间的分隔线

def build():
    parts = []
    total_code_lines = 0
    # 文档抬头
    parts.append(f"软件名称（全称）：{FULLNAME}")
    parts.append(f"软件简称：{SHORT}（软件运行界面显示此英文简称）")
    parts.append("说明：以下为本软件源代码清单。两个文件之间以一行「—」分隔，每个文件前标注其文件路径，便于定位文件的头与尾。")
    parts.append(SEP)
    parts.append("")

    n = len(FILES)
    for i, (rel, desc) in enumerate(FILES, 1):
        path = os.path.join(ROOT, rel)
        with open(path, "r", encoding="utf-8") as f:
            code = f.read().rstrip("\n")
        code_lines = code.count("\n") + 1
        total_code_lines += code_lines
        # 文件标头（找到每个文件的“头”）
        parts.append(f"【文件 {i}/{n}】 {rel}")
        parts.append(f"【说明】 {desc}    （本文件 {code_lines} 行）")
        parts.append("")
        parts.append(code)
        parts.append("")
        # 两个文件之间的分隔线（找到每个文件的“尾”/边界）
        if i < n:
            parts.append(SEP)
            parts.append("")

    parts.append(SEP)
    parts.append(f"— 源代码清单结束 —  共 {n} 个文件，代码合计约 {total_code_lines} 行 —")

    text = "\n".join(parts) + "\n"
    # UTF-8 with BOM，Word/记事本正确识别中文
    with open(OUT, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(text)
    out_lines = text.count("\n")
    print("SAVED:", OUT)
    print(f"files: {n}  code lines: {total_code_lines}  total txt lines: {out_lines}  (~{out_lines//50} pages @50/pg)")

build()
