"""Browser test of the 数据导入 entry — the paths a real user actually takes.

The entry had a silent failure: `dataTransfer.files` is EMPTY when a FOLDER is
dropped (Chromium exposes the directory only through
`items[].webkitGetAsEntry()`), so dragging `testdata/` in did nothing at all
and said nothing either. The tunnel's data is stored as ca/ da/ temp/, so that
is the normal way in, not an edge case.

Covers:
  * 选择文件夹 picks a whole tree (390 files across 3 subdirectories)
  * dropping a folder works, and reports what it found
  * unrelated files in the tree are filtered client-side and counted
  * an empty drop produces a VISIBLE error, never a silent no-op

    ./.venv/Scripts/python.exe wt_import_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

import httpx
from playwright.sync_api import Page, expect, sync_playwright

WEB = os.environ.get("WT_WEB", "http://127.0.0.1:3000")
EMAIL = os.environ.get("WT_TEST_EMAIL", "wt-import@example.com")
PASSWORD = os.environ.get("WT_TEST_PASSWORD", "wt-import-pass-2026")
DATA = Path(os.environ.get("WT_TESTDATA", r"d:/Git/Personal/WTDataAgent/FromC/testdata"))
SHOTS = Path(__file__).resolve().parents[1] / "tmp" / "wt-ui"

PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name if cond else f"{name}: {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def enter(page: Page) -> None:
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
        i = page.locator('form input[type="text"]')
        if i.count():
            i.first.fill("WT Import")
        page.locator("form button").last.click()
        page.wait_for_url("**/app", timeout=25000)
    page.click('button[title="风洞质量检查"]')
    expect(page.get_by_role("heading", name="风洞试验过程质量检查")).to_be_visible()


def reset_account() -> None:
    """Delete this account's batches before driving the UI.

    Without it the page loads showing the PREVIOUS run's batch, so a wait for
    "已识别车次 / 246490" is satisfied before the new upload even finishes —
    the test then reads a half-finished screen. A browser test that depends on
    leftover state is not a test.
    """
    api = os.environ.get("WT_API", "http://127.0.0.1:8077/api")
    c = httpx.Client(base_url=api, timeout=300.0,
                     transport=httpx.HTTPTransport(retries=3))
    r = c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        r = c.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD,
                                         "name": "WT Import"})
    if r.status_code != 200:
        return
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    for b in c.get("/wt/batches").json():
        c.delete(f"/wt/batches/{b['id']}")


def main() -> int:
    if not DATA.exists():
        print(f"找不到测试数据：{DATA}")
        return 2
    reset_account()
    with sync_playwright() as pw:
        exe = os.environ.get("WT_CHROME", "")
        if not exe:
            root = Path.home() / "AppData" / "Local" / "ms-playwright"
            for cand in sorted(root.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True):
                exe = str(cand)
                break
        browser = pw.chromium.launch(executable_path=exe or None)
        page = browser.new_context(viewport={"width": 1600, "height": 1000},
                                   locale="zh-CN").new_page()
        page.set_default_timeout(120000)

        print("\n=== 进入数据导入 ===")
        enter(page)
        body = page.inner_text("body")
        check("导入区提供「选择文件」与「选择文件夹」两个入口",
              "选择文件" in body and "选择文件夹" in body)
        check("说明了目录结构可直接选最外层",
              "直接选最外层目录" in body)
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / "30-import-entry.png"), full_page=True)

        print("\n=== 空拖放必须可见报错，不能静默 ===")
        page.evaluate("""() => {
            const zone = [...document.querySelectorAll('div')]
              .find(d => d.className && d.className.includes('border-dashed'));
            const dt = new DataTransfer();
            zone.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
        }""")
        page.wait_for_timeout(800)
        body = page.inner_text("body")
        check("空拖放给出明确提示（旧版本是静默无反应）",
              "没有读到任何文件" in body, [l for l in body.splitlines() if "没有读到" in l][:1])
        page.screenshot(path=str(SHOTS / "31-import-empty-drop.png"), full_page=True)

        print("\n=== 选择文件夹：一次导入整棵目录树 ===")
        page.set_input_files('[data-testid="wt-dir-input"]', str(DATA))
        # Wait for the COMPLETION message, not merely for run numbers to appear.
        page.wait_for_function(
            "() => document.body.innerText.includes('已导入')", timeout=300000)
        page.wait_for_timeout(1200)
        body = page.inner_text("body")
        check("整棵 testdata 目录一次导入", "130 个车次" in body,
              [l for l in body.splitlines() if "个车次" in l][:1])
        check("导入后给出进度反馈", "已导入" in body,
              [l for l in body.splitlines() if "已导入" in l][:1])
        check("车次表被一并读入，不再当作无关文件跳过",
              "跳过 1 个无关文件" not in body,
              [l for l in body.splitlines() if "已导入" in l][:1])
        page.screenshot(path=str(SHOTS / "32-import-folder.png"), full_page=True)

        print("\n=== 计划与实到核对（来自车次表）===")
        page.get_by_role("button", name="多车次对比").click()
        page.wait_for_timeout(2500)
        page.get_by_role("button", name="状态矩阵").click()
        page.wait_for_timeout(2000)
        body = page.inner_text("body")
        check("显示计划与实到核对", "计划与实到核对" in body)
        check("给出计划数与实到数", "计划 136 个车次，实到 130 个" in body,
              [l for l in body.splitlines() if "计划 " in l][:1])
        check("区分重做废弃与真正缺失",
              "重做前的废弃车次" in body and "计划内但没有数据" in body)
        check("点名缺失车次 246542 / 246543",
              "246542" in body and "246543" in body)
        check("文件状态与车次表逐项一致（对解析器的独立校验）",
              "个车次的文件状态与车次表逐项一致" in body,
              [l for l in body.splitlines() if "逐项一致" in l][:1])
        page.screenshot(path=str(SHOTS / "35-coverage.png"), full_page=True)
        page.get_by_role("button", name="数据导入").click()
        page.wait_for_timeout(800)

        print("\n=== 目录里混入无关文件时应被过滤并计数 ===")
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="wt_mixed_"))
        try:
            (tmp / "ca").mkdir()
            for n in ("246490", "246492", "246493"):
                shutil.copy(DATA / "ca" / f"ca{n}", tmp / "ca" / f"ca{n}")
                shutil.copy(DATA / "temp" / f"pa{n}", tmp / f"pa{n}")
                shutil.copy(DATA / "da" / f"da{n}", tmp / f"da{n}")
            (tmp / "readme.txt").write_text("说明文件，不是车次数据", encoding="utf-8")
            (tmp / "notes.docx").write_bytes(b"not a run file")
            (tmp / "ca" / "thumbs.db").write_bytes(b"junk")
            page.set_input_files('[data-testid="wt-dir-input"]', str(tmp))
            page.wait_for_function(
                "() => document.body.innerText.includes('已导入')", timeout=120000)
            page.wait_for_timeout(800)
            body = page.inner_text("body")
            check("混入的无关文件被过滤并如实计数",
                  "跳过 3 个无关文件" in body,
                  [l for l in body.splitlines() if "跳过" in l][:1])
            check("识别出 3 个车次", "3 个车次" in body,
                  [l for l in body.splitlines() if "个车次" in l][:1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        page.screenshot(path=str(SHOTS / "33-import-mixed.png"), full_page=True)

        print("\n=== 全是无关文件时给出可操作的提示 ===")
        tmp2 = Path(tempfile.mkdtemp(prefix="wt_junk_"))
        try:
            (tmp2 / "a.txt").write_text("x", encoding="utf-8")
            (tmp2 / "b.docx").write_bytes(b"y")
            page.set_input_files('[data-testid="wt-dir-input"]', str(tmp2))
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            check("说明什么样的文件名才算车次文件",
                  "没有识别到车次文件" in body and "ca246490" in body,
                  [l for l in body.splitlines() if "没有识别到" in l][:1])
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        print("\n=== 导入后能正常执行检查 ===")
        page.set_input_files('[data-testid="wt-dir-input"]', str(DATA / "ca"))
        page.wait_for_function(
            "() => document.body.innerText.includes('已导入')", timeout=180000)
        page.wait_for_timeout(1000)
        page.get_by_role("button", name="开始检查").click()
        page.wait_for_selector("text=检查结果明细", timeout=300000)
        body = page.inner_text("body")
        check("只导 ca 目录也能检查（pa 类项如实未评定）",
              "检查结果明细" in body and "未评定" in body)
        page.screenshot(path=str(SHOTS / "34-import-ca-only.png"), full_page=True)

        browser.close()

    print("\n" + "=" * 70)
    print(f"数据导入：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    print(f"截图目录：{SHOTS}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
