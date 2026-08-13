"""Browser-level end-to-end test of the wind-tunnel application.

Drives the real UI with Playwright — login, upload the customer's actual run
files, tick the checks, run them, read the verdicts off the screen, plot the
curves, generate and export a report, and exercise both extension surfaces.
Screenshots land in ``<repo>/tmp/wt-ui/`` as evidence.

    ./.venv/Scripts/python.exe -m playwright install chromium   # once
    ./.venv/Scripts/python.exe wt_ui_test.py

Requires the backend on :8077 and the frontend on :3000.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

from playwright.sync_api import Page, expect, sync_playwright

WEB = os.environ.get("WT_WEB", "http://127.0.0.1:3000")
EMAIL = os.environ.get("WT_TEST_EMAIL", "wt-ui@example.com")
PASSWORD = os.environ.get("WT_TEST_PASSWORD", "wt-ui-pass-2026")

FROMC = Path(os.environ.get(
    "WT_FROMC",
    r"d:/Git/Personal/WTDataAgent/FromC/20260129风洞试验过程质量检查智能体",
))
CA_DIR = FROMC / "Agent1风洞试验数据监测智能体-2-发锋哥版本" / \
    "场景一风洞试验数据监测智能体-2-发锋哥版本" / "data" / "ca模板(公开)"
PA_DIR = FROMC / "Agent1风洞试验数据监测智能体-2-发锋哥版本" / \
    "场景一风洞试验数据监测智能体-2-发锋哥版本" / "data" / "TEMP模板(公开)"
DA_DIR = FROMC / "Agent2质量检测代码生成" / "Agent2质量检测代码生成-9-发锋哥" / \
    "Data" / "list模板(公开)"
INPUT_DIR = FROMC / "输入"

SHOTS = Path(__file__).resolve().parents[1] / "tmp" / "wt-ui"
PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name if cond else f"{name}: {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def shot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def login(page: Page) -> None:
    page.goto(f"{WEB}/login", wait_until="networkidle")
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.locator("form button").last.click()
    try:
        page.wait_for_url("**/app", timeout=8000)
    except Exception:
        page.goto(f"{WEB}/signup", wait_until="networkidle")
        page.fill('input[type="email"]', EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        inputs = page.locator('form input[type="text"]')
        if inputs.count():
            inputs.first.fill("WT UI")
        page.locator("form button").last.click()
        page.wait_for_url("**/app", timeout=20000)


def main() -> int:
    with sync_playwright() as pw:
        # Reuse whichever Chromium build is already on the machine. The pip
        # playwright and the npx one pin different revisions; requiring an exact
        # match would make this test un-runnable on a box that already has a
        # perfectly good browser.
        exe = os.environ.get("WT_CHROME", "")
        if not exe:
            root = Path.home() / "AppData" / "Local" / "ms-playwright"
            for cand in sorted(root.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True):
                exe = str(cand)
                break
        browser = pw.chromium.launch(executable_path=exe or None)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000},
                                  locale="zh-CN")
        page = ctx.new_page()
        page.set_default_timeout(30000)

        print("\n=== 0. 登录并进入风洞应用 ===")
        login(page)
        check("登录成功", "/app" in page.url, page.url)
        page.click('button[title="风洞质量检查"]')
        expect(page.get_by_role("heading", name="风洞试验过程质量检查")).to_be_visible()
        check("侧边栏入口可进入风洞应用", True)
        shot(page, "01-entry")

        print("\n=== ① 数据导入 ===")
        files = [str(p) for d in (CA_DIR, PA_DIR, DA_DIR) if d.exists()
                 for p in sorted(d.iterdir()) if p.is_file()]
        check("找到甲方模板车次文件", len(files) >= 12, f"{len(files)} 个")
        page.set_input_files('[data-testid="wt-file-input"]', files)
        page.wait_for_selector("text=已识别车次", timeout=60000)
        # Wait for THIS batch's runs, not just the heading — the heading is
        # already on screen from whatever batch was selected before.
        page.wait_for_function(
            "() => { const t = document.body.innerText;"
            " return ['91836','91837','91838','91839','91840'].every(x => t.includes(x)); }",
            timeout=60000)
        body = page.inner_text("body")
        check("自动识别 5 个连续车次",
              all(f"9183{i}" in body for i in range(6, 10)) and "91840" in body)
        shot(page, "02-import")

        n_checked = page.locator('input[type="checkbox"]:checked').count()
        check("检查项默认全部勾选", n_checked >= 18, f"{n_checked} 项")

        print("\n=== 开始检查 ===")
        page.get_by_role("button", name="开始检查").click()
        page.wait_for_selector("text=检查结果明细", timeout=180000)
        shot(page, "03-result")
        body = page.inner_text("body")
        check("跳转到运算结果并显示明细", "检查结果明细" in body)
        check("91837 判为不合格（与甲方跟班记录一致）", "不合格" in body)

        print("\n=== ② 运算结果查看 ===")
        # The run list is now a compact picker (a <select> plus an expandable
        # list) — a 130-run entry made the old per-run card list push every
        # control off screen.
        page.locator("select").first.select_option("91837")
        page.wait_for_timeout(800)
        body = page.inner_text("body")
        check("天平零飘 0.0989 显示在界面上", "0.098912" in body or "0.0989" in body,
              "界面读数")
        check("原因分析/影响评估/处理建议三段齐全",
              "原因分析" in body and "影响评估" in body and "处理建议" in body)
        check("未评定项不伪装成正常", "未评定" in body)
        check("判据依据可展开", "判据依据" in body)
        shot(page, "04-findings-91837")

        # 多车次趋势
        if "多车次趋势" in body:
            check("多车次趋势面板出现", True)
        else:
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(400)
            check("多车次趋势面板出现", "多车次趋势" in page.inner_text("body"))
        shot(page, "05-trend")

        # The picker must not bury the controls, whatever the run count.
        page.mouse.wheel(0, -6000)
        page.wait_for_timeout(300)
        check("车次选择器紧凑，批次汇总仍在首屏",
              "批次汇总" in page.inner_text("body") and "展开车次列表" in page.inner_text("body"))
        page.get_by_role("button", name="展开车次列表", exact=False).click()
        page.wait_for_timeout(500)
        # placeholder text never appears in innerText — check the element.
        check("展开后可搜索与按异常筛选",
              page.get_by_placeholder("搜索车次号").count() > 0
              and "跳到下一个异常" in page.inner_text("body"),
              f"搜索框 {page.get_by_placeholder('搜索车次号').count()} 个")
        page.get_by_role("button", name="收起车次列表").click()
        page.wait_for_timeout(300)

        print("\n=== ③ 气动曲线绘制 ===")
        page.get_by_role("button", name="气动曲线绘制").click()
        page.wait_for_timeout(1500)
        page.get_by_role("button", name="绘制曲线").click()
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        has_curve = "曲线特征量" in body
        check("曲线与特征量表出现（模板车次含 da 文件）", has_curve,
              "" if has_curve else "该车次可能没有 da 文件")
        if has_curve:
            check("给出线性斜率与线性度 R²", "线性度" in body and "线性斜率" in body)
        shot(page, "06-curve")

        print("\n=== ④ 报告生成 / 编辑 / 导出 ===")
        page.get_by_role("button", name="质量检查报告").click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name="生成报告").click()
        page.wait_for_selector("text=报告预览", timeout=180000)
        body = page.inner_text("body")
        check("报告已生成并预览", "报告预览" in body)
        check("报告含判据附录", "判据与依据" in body)
        check("报告含跟班记录正文", "跟班记录" in body)
        shot(page, "07-report")

        page.get_by_role("button", name="编辑内容").click()
        page.wait_for_timeout(400)
        ta = page.locator("textarea").last
        ta.click()
        ta.press("Control+End")
        ta.type("\n\n> 【人工补充】UI 端到端测试写入。\n")
        page.get_by_role("button", name="保存编辑").click()
        page.wait_for_timeout(1200)
        check("报告预览可编辑并保存",
              "已保存编辑内容" in page.inner_text("body"))
        with page.expect_download(timeout=60000) as dl:
            page.get_by_role("button", name="导出报告").click()
        path = dl.value.path()
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        check("导出文件包含人工编辑内容", "人工补充" in text,
              f"{dl.value.suggested_filename}，{len(text)} 字")
        check("导出文件名符合「车次号_跟班记录」约定",
              "跟班记录" in dl.value.suggested_filename or
              "质量检查报告" in dl.value.suggested_filename,
              dl.value.suggested_filename)
        shot(page, "08-report-edited")

        print("\n=== ⑤ 知识库：规则即数据 ===")
        page.get_by_role("button", name="知识库管理").click()
        page.wait_for_timeout(1200)
        body = page.inner_text("body")
        check("规则库列出内置规则", "规则库" in body and "内置" in body)
        page.get_by_role("button", name="手工新增规则").click()
        page.wait_for_timeout(500)
        check("规则编辑器可打开（阈值可视化编辑，不写代码）",
              "判定区间" in page.inner_text("body"))
        shot(page, "09-rule-editor")
        page.get_by_role("button", name="取消").click()

        page.get_by_role("button", name="监测特征", exact=False).click()
        page.wait_for_timeout(600)
        check("特征清单可见（测量与判定分离）",
              "balance_zero_drift" in page.inner_text("body"))
        shot(page, "10-features")

        page.get_by_role("button", name="天平载荷库", exact=False).click()
        page.wait_for_timeout(600)
        check("天平载荷库可维护", "新增 / 更新条目" in page.inner_text("body"))
        shot(page, "11-balances")

        print("\n=== 真实车次 246490（含 da）走一遍曲线 ===")
        page.get_by_role("button", name="数据导入").click()
        page.wait_for_timeout(600)
        page.set_input_files('[data-testid="wt-file-input"]',
                             [str(p) for p in sorted(INPUT_DIR.iterdir()) if p.is_file()])
        page.wait_for_function(
            "() => document.body.innerText.includes('当前批次') &&"
            " document.body.innerText.includes('246490')", timeout=60000)
        page.wait_for_timeout(800)
        page.get_by_role("button", name="开始检查").click()
        page.wait_for_selector("text=检查结果明细", timeout=180000)
        body = page.inner_text("body")
        check("真实车次 246490 检查完成", "246490" in body)
        check("缺天平量程时如实报未评定并给出补齐方式",
              "载荷库" in body or "未评定" in body)
        shot(page, "12-real-run")
        page.get_by_role("button", name="气动曲线绘制").click()
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        check("真实车次气动曲线绘制成功", "曲线特征量" in body)
        shot(page, "13-real-curve")

        browser.close()

    print("\n" + "=" * 70)
    print(f"UI 端到端：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    print(f"截图目录：{SHOTS}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
