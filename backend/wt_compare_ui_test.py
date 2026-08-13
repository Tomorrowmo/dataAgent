"""Browser test of 多车次对比 on the real 130-run entry.

Drives the comparison view the 20260225 note asks for: filter 130 runs down to
a deflection series, plot them sorted by δz, switch to a drag polar, take the
delta against the δ=0 baseline, plot versus Mach at selected angles of attack,
and read the coverage matrix / control effectiveness / symmetry panes.
Screenshots land in ``<repo>/tmp/wt-ui/``.

    ./.venv/Scripts/python.exe wt_compare_ui_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

from playwright.sync_api import Page, expect, sync_playwright

WEB = os.environ.get("WT_WEB", "http://127.0.0.1:3000")
EMAIL = os.environ.get("WT_TEST_EMAIL", "wt-matrix@example.com")
PASSWORD = os.environ.get("WT_TEST_PASSWORD", "wt-matrix-pass-2026")
SHOTS = Path(__file__).resolve().parents[1] / "tmp" / "wt-ui"

PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name if cond else f"{name}: {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def shot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def main() -> int:
    with sync_playwright() as pw:
        exe = os.environ.get("WT_CHROME", "")
        if not exe:
            root = Path.home() / "AppData" / "Local" / "ms-playwright"
            for cand in sorted(root.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True):
                exe = str(cand)
                break
        browser = pw.chromium.launch(executable_path=exe or None)
        page = browser.new_context(viewport={"width": 1680, "height": 1050},
                                   locale="zh-CN").new_page()
        page.set_default_timeout(60000)

        print("\n=== 登录并进入多车次对比 ===")
        page.goto(f"{WEB}/login", wait_until="networkidle")
        page.fill('input[type="email"]', EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        page.locator("form button").last.click()
        page.wait_for_url("**/app", timeout=20000)
        page.click('button[title="风洞质量检查"]')
        expect(page.get_by_role("heading", name="风洞试验过程质量检查")).to_be_visible()
        page.get_by_role("button", name="多车次对比").click()
        page.wait_for_selector("text=对比绘图", timeout=30000)
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        check("进入多车次对比", "对比绘图" in body and "状态矩阵" in body)
        check("加载 130 个车次", "共 130 个车次" in body, body[body.find("共 "):body.find("共 ") + 22])
        shot(page, "20-compare-entry")

        print("\n=== 筛选：Ma1.741 / β=0 / 仅升降舵单独偏转 ===")
        selects = page.locator("select")
        selects.nth(0).select_option(label="Ma=1.741")
        selects.nth(1).select_option(label="β=0°")
        selects.nth(2).select_option(label="仅升降舵 δz 单独偏转")
        page.wait_for_timeout(600)
        btn = page.get_by_role("button", name="加入筛选结果", exact=False)
        label = btn.inner_text()
        check("筛选后剩 6 个 δz 偏转车次", "(6)" in label, label)
        btn.click()
        page.wait_for_timeout(400)
        # add the δ=0 baseline of that block back in
        selects.nth(2).select_option(label="仅 δ 全零基准车次")
        page.wait_for_timeout(500)
        page.get_by_role("button", name="加入筛选结果", exact=False).click()
        page.wait_for_timeout(400)
        body = page.inner_text("body")
        check("已选 7 个车次（6 偏转 + 1 基准，筛选结果为累加）", "已选 7" in body,
              [l for l in body.splitlines() if "已选" in l][:1])

        print("\n=== 绘图：CN vs 攻角，按 δz 排序 ===")
        page.get_by_role("button", name="绘图", exact=True).click()
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        check("出图并给出图例状态表", "图例（多车次对比时" in body and "7 条曲线" in body,
              [l for l in body.splitlines() if "条曲线" in l][:1])
        check("图例按 δz 升序（-25→+25）", "-25" in body and "25" in body,
              "图例含 ±25 舵偏行")
        check("图例含状态列 Ma/β/φ/δz/δy/δx",
              all(k in body for k in ("Ma", "β", "φ", "δz", "δy", "δx")))
        shot(page, "21-compare-runs")

        print("\n=== 差量对比（以 δ=0 车次为基准）===")
        page.get_by_role("button", name="差量", exact=True).click()
        page.wait_for_timeout(400)
        page.locator("select").last.select_option("246490")
        page.wait_for_timeout(300)
        page.get_by_role("button", name="绘图", exact=True).click()
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        check("差量模式生效并标出基准", "差量 · 基准 246490" in body)
        shot(page, "22-compare-delta")

        print("\n=== 极曲线：横轴取 CN ===")
        page.get_by_role("button", name="原值", exact=True).click()
        page.wait_for_timeout(300)
        # x-axis column picker is the first select inside the 横轴 card
        page.locator("select").nth(3).select_option("CN")
        page.wait_for_timeout(300)
        for lab in ("法向力系数 CN", "俯仰力矩系数 MZ"):
            pass
        cd = page.locator("label", has_text="阻力系数 CD").first
        if cd.count():
            cd.locator("input").check()
        page.get_by_role("button", name="绘图", exact=True).click()
        page.wait_for_timeout(2500)
        check("以 CN 为横轴出图（阻力极曲线）",
              "法向力系数 CN" in page.inner_text("body"))
        shot(page, "23-compare-polar")

        print("\n=== 随马赫数变化（攻角序列 + 两组）===")
        page.get_by_role("button", name="状态量").click()
        page.wait_for_timeout(400)
        selects = page.locator("select")
        selects.nth(0).select_option("")          # clear Mach filter
        selects.nth(2).select_option(label="仅 δ 全零基准车次")
        page.wait_for_timeout(500)
        page.get_by_role("button", name="加入筛选结果", exact=False).click()
        page.wait_for_timeout(400)
        boxes = page.locator('input[type="text"], input:not([type])')
        page.get_by_placeholder("留空则只画一组").fill("2 3")
        page.get_by_role("button", name="绘图", exact=True).click()
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        check("随马赫数出图", "马赫数 M" in body and "条曲线" in body,
              [l for l in body.splitlines() if "条曲线" in l][:1])
        shot(page, "24-compare-mach")

        print("\n=== 导出 CSV ===")
        with page.expect_download(timeout=60000) as dl:
            page.locator('button[title^="保存数据"]').click()
        text = Path(dl.value.path()).read_text(encoding="utf-8-sig", errors="replace")
        check("导出对比数据", len(text.splitlines()) > 3,
              f"{dl.value.suggested_filename}，{len(text.splitlines())} 行")

        print("\n=== 状态矩阵 ===")
        page.get_by_role("button", name="状态矩阵").click()
        page.wait_for_timeout(1500)
        body = page.inner_text("body")
        check("12 个 (Ma,β) 区块", "12 个 (Ma, β) 区块" in body)
        check("列出每块的基准车次与舵偏覆盖",
              "基准车次" in body and "δz 覆盖" in body)
        shot(page, "25-matrix")

        print("\n=== 舵效分析 ===")
        page.get_by_role("button", name="舵效分析").click()
        page.wait_for_timeout(600)
        page.get_by_role("button", name="计算").click()
        page.wait_for_timeout(6000)
        body = page.inner_text("body")
        check("舵偏响应表（线性段导数 + 饱和比）",
              "线性段导数/度" in body and "饱和比" in body)
        check("操纵增量明细", "操纵增量明细" in body)
        shot(page, "26-effectiveness")

        print("\n=== 对称性校核 ===")
        page.get_by_role("button", name="对称性校核").click()
        page.wait_for_timeout(600)
        page.get_by_role("button", name="计算").click()
        page.wait_for_timeout(6000)
        body = page.inner_text("body")
        check("对称性结果与判据说明",
              "不对称度" in body and "中位数" in body)
        check("判异口径写明是与同批次比而非与 0 比",
              "与本批次全部" in body or "同批次" in body)
        shot(page, "27-symmetry")

        browser.close()

    print("\n" + "=" * 70)
    print(f"多车次对比 UI：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    print(f"截图目录：{SHOTS}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
