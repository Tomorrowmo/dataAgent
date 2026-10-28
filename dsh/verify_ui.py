"""无头验证 RLab 工作台在 dsh Web 里真的渲染并显示真实数据。

断言全部走结构（数元素、读层级、点单元格），不在整页文本里找子串——后者会因为
数据集名里含 "clean"、或某处出现 "#26" 这类巧合而通过，那种通过毫无意义。
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = os.environ.get("WEB", "http://127.0.0.1:3080")
SHOTS = Path(os.environ.get("SHOTS", "."))
PASSED, FAILED = [], []


def check(name, cond, ok_detail="", fail_detail=""):
    """通过与失败各说各的话。

    先前版本无论成败都打同一段说明，于是出现「PASS — 未见数据集行」这种自相矛盾
    的输出。验证工具自己说谎，比没有验证更糟。
    """
    detail = ok_detail if cond else fail_detail
    (PASSED if cond else FAILED).append(name if cond else f"{name}: {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return bool(cond)


def dismiss_host_dialog(page):
    """关掉 dsh 首次运行的公告遮罩——宿主的一次性对话框，不是被测对象。

    按结构定位对话框里唯一的主按钮，不按文字匹配：文案会随版本变。
    """
    for _ in range(4):
        if page.locator('[class*="_mask_"]').count() == 0:
            return
        primary = page.locator('[role="dialog"] button[class*="_primary_"]')
        if primary.count():
            primary.last.click(timeout=5000, force=True)
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(600)


def main() -> int:
    with sync_playwright() as pw:
        exe = os.environ.get("CHROME", "")
        if not exe:
            root = Path.home() / "AppData" / "Local" / "ms-playwright"
            for cand in sorted(root.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True):
                exe = str(cand)
                break
        # 系统代理会拦回环；dsh 的 SSE 长连接让 networkidle 永不触发。
        browser = pw.chromium.launch(executable_path=exe or None,
                                     args=["--no-proxy-server"])
        page = browser.new_context(viewport={"width": 1500, "height": 950},
                                   locale="zh-CN").new_page()
        page.set_default_timeout(30000)

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(WEB, wait_until="domcontentloaded")
        page.wait_for_selector("button", timeout=30000)
        page.wait_for_timeout(2500)
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / "01-shell.png"))

        dismiss_host_dialog(page)
        check("宿主首次运行遮罩已关闭",
              page.locator('[class*="_mask_"]').count() == 0,
              fail_detail="遮罩仍在，后续点击会被拦截")

        launcher = page.get_by_role("button", name="工作台")
        if not check("工作台入口出现在外壳上", launcher.count() > 0,
                     ok_detail=f"{launcher.count()} 个",
                     fail_detail="外壳上没有入口"):
            print("控制台错误:", errors[:5])
            browser.close()
            return 1

        launcher.first.click()
        page.wait_for_timeout(1800)
        page.screenshot(path=str(SHOTS / "02-workbench-datasets.png"))
        body = page.inner_text("body")
        check("面板标题出现", "RLab 工作台" in body, fail_detail="未见标题")
        check("标注为只读视图", "只读视图" in body, fail_detail="未见只读标注")

        rows = page.locator("[data-rlab-dataset]")
        n = rows.count()
        check("血缘树渲染出数据集行", n >= 5,
              ok_detail=f"{n} 行", fail_detail=f"只有 {n} 行")

        depths = sorted({int(rows.nth(i).get_attribute("data-rlab-depth") or 0)
                         for i in range(min(n, 60))})
        check("血缘确实是树（存在嵌套层级）", len(depths) >= 2,
              ok_detail=f"层级 {depths}", fail_detail=f"全部同层：{depths}")

        ops = page.locator('[data-rlab-dataset] [title="产生这个数据集的算法"]')
        check("派生行标注了产生它的算法", ops.count() >= 1,
              ok_detail=f"{ops.count()} 条边有算法标签",
              fail_detail="没有任何派生行标注算法")

        check("预览表有列头", page.locator("table thead th").count() >= 1,
              ok_detail=f"{page.locator('table thead th').count()} 列",
              fail_detail="没有列头")
        check("预览表有数据单元格", page.locator("table tbody td").count() >= 2,
              ok_detail=f"{page.locator('table tbody td').count()} 个单元格",
              fail_detail="没有数据行")

        # 换一个数据集，确认预览跟着选择走，而不是一张死表。
        before = page.locator("table thead th").all_inner_texts()
        target = None
        for i in range(min(n, 60)):
            if rows.nth(i).get_attribute("data-rlab-dataset") == "262":
                target = rows.nth(i)
                break
        if target is not None:
            target.click()
            page.wait_for_timeout(1500)
            after = page.locator("table thead th").all_inner_texts()
            check("切换数据集会重新加载预览",
                  after != before and "signal" in after,
                  ok_detail=f"{before} → {after}",
                  fail_detail=f"列头未按预期变化：{before} → {after}")
            page.screenshot(path=str(SHOTS / "02b-dataset-262.png"))
        else:
            check("找得到演示数据集 #262", False,
                  fail_detail="树里没有 #262，无法验证切换")

        page.get_by_role("button", name="算法库").click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "03-workbench-algorithms.png"))

        algos = page.locator("[data-rlab-algo]")
        check("算法库渲染出条目", algos.count() >= 10,
              ok_detail=f"{algos.count()} 个", fail_detail=f"只有 {algos.count()} 个")
        check("含内置的 savgol_filter",
              page.locator('[data-rlab-algo="savgol_filter"]').count() == 1,
              ok_detail="找到", fail_detail="未找到 savgol_filter")
        builtin = page.locator('[data-rlab-source="builtin"]').count()
        ai = page.locator('[data-rlab-source="ai"]').count()
        check("按来源区分内置与 AI 生成", builtin >= 5 and ai >= 1,
              ok_detail=f"内置 {builtin}，AI {ai}",
              fail_detail=f"内置 {builtin}，AI {ai}——来源未区分")

        page.keyboard.press("Escape")
        page.wait_for_timeout(700)
        check("Esc 关闭面板", "RLab 工作台" not in page.inner_text("body"),
              fail_detail="面板仍在")
        page.screenshot(path=str(SHOTS / "04-closed.png"))

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("无 JS 运行时错误", not real_errors,
              fail_detail="; ".join(real_errors[:2])[:200])
        browser.close()

    print("\n" + "=" * 60)
    print(f"UI 验证：通过 {len(PASSED)}，失败 {len(FAILED)}")
    for f in FAILED:
        print("  FAILED:", f)
    print("截图:", SHOTS.resolve())
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
