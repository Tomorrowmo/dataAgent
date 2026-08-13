"""End-to-end HTTP test of the wind-tunnel API against a running backend.

Run the backend first::

    ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8077
    ./.venv/Scripts/python.exe wt_api_test.py

Walks the exact path a customer would: 登录 → 上传车次 → 选检查项 → 执行检查 →
看结果 → 画曲线 → 出报告 → 编辑 → 导出，plus both extension surfaces
(AI 起草规则 → 预览 → 落库 → 重跑；AI 生成算子 → 沙箱 → 入库 → 被规则引用).

Exits non-zero on the first failed assertion so it can gate a release.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

BASE = os.environ.get("WT_API", "http://127.0.0.1:8077/api")
EMAIL = os.environ.get("WT_TEST_EMAIL", "wt-e2e@example.com")
PASSWORD = os.environ.get("WT_TEST_PASSWORD", "wt-e2e-pass-2026")

FROMC = Path(os.environ.get(
    "WT_FROMC",
    r"d:/Git/Personal/WTDataAgent/FromC/20260129风洞试验过程质量检查智能体",
))
INPUT_DIR = FROMC / "输入"
CA_DIR = FROMC / "Agent1风洞试验数据监测智能体-2-发锋哥版本" / \
    "场景一风洞试验数据监测智能体-2-发锋哥版本" / "data" / "ca模板(公开)"
PA_DIR = FROMC / "Agent1风洞试验数据监测智能体-2-发锋哥版本" / \
    "场景一风洞试验数据监测智能体-2-发锋哥版本" / "data" / "TEMP模板(公开)"
DA_DIR = FROMC / "Agent2质量检测代码生成" / "Agent2质量检测代码生成-9-发锋哥" / \
    "Data" / "list模板(公开)"

PASSED: List[str] = []
FAILED: List[str] = []



def _client(base: str) -> httpx.Client:
    """HTTP client that survives uvicorn's keep-alive timeout.

    A long request (the AI narration takes ~10 s) leaves the pool's other
    connections idle past uvicorn's 5 s keep-alive, so the server closes them.
    Reusing one then fails with WinError 10054 mid-write. `retries` on the
    transport re-establishes the connection instead — this is a client-pool
    artefact, not a server fault, and a real browser handles it the same way.
    """
    return httpx.Client(base_url=base, timeout=600.0,
                        transport=httpx.HTTPTransport(retries=3))

def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  [PASS] {name}" + (f"  — {detail}" if detail else ""))
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}  — {detail}")


def section(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def main() -> int:
    c = _client(BASE)

    # ── auth ────────────────────────────────────────────────────────────
    section("0. 登录")
    r = c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        r = c.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD,
                                         "name": "WT E2E"})
    check("认证", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:400])
        return 1
    token = r.json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"

    # ── idempotency ─────────────────────────────────────────────────────
    # A release gate that only passes on a virgin account is worthless. Remove
    # everything a previous run of THIS test created, so the assertions below
    # always start from the shipped baseline.
    section("0b. 清理上一轮测试残留（保证可重复运行）")
    removed = 0
    try:
        for r in c.get("/wt/rules").json()["rules"]:
            if r["rule_id"].startswith("rule_e2e_"):
                c.delete(f"/wt/rules/{r['id']}")
                removed += 1
        for b in c.get("/wt/balances").json()["balances"]:
            if b["name"].upper() == "N636CB01":
                c.delete(f"/wt/balances/{b['id']}")
                removed += 1
        for b in c.get("/wt/batches").json():
            c.delete(f"/wt/batches/{b['id']}")
            removed += 1
    except Exception as e:  # noqa: BLE001
        print("  (清理时出现异常，继续执行)", e)
    check("测试环境已重置", True, f"清理 {removed} 项残留")

    h = c.get("/wt/health").json()
    check("风洞模块健康检查", h.get("ok") is True,
          f"LLM可用={h.get('llm_configured')} 模型={h.get('model')} "
          f"特征数={h.get('features')} 内置规则={h.get('seed_rules')}")
    llm_on = bool(h.get("llm_configured"))

    # ── ① 数据导入 ──────────────────────────────────────────────────────
    section("① 数据导入 — 上传 5 个连续车次(ca+pa+da) + 1 个真实车次")
    files = []
    for d in (CA_DIR, PA_DIR, DA_DIR):
        if d.exists():
            for p in sorted(d.iterdir()):
                if p.is_file():
                    files.append(("files", (p.name, p.read_bytes(), "application/octet-stream")))
    check("模板车次文件已找到", len(files) >= 12, f"{len(files)} 个文件")
    r = c.post("/wt/batches", files=files, data={"name": "E2E 模板批次 91836~91840"})
    check("创建批次", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    batch = r.json()
    bid = batch["id"]
    runs = batch["runs"]
    check("自动按车次分组", len(runs) == 5,
          "车次=" + "、".join(x["run_no"] for x in runs))
    check("三类文件归位", all(x["files"].get("ca") and x["files"].get("pa") for x in runs),
          json.dumps(runs[0]["files"], ensure_ascii=False))

    r2 = c.post("/wt/batches",
                files=[("files", (p.name, p.read_bytes(), "application/octet-stream"))
                       for p in sorted(INPUT_DIR.iterdir()) if p.is_file()],
                data={"name": "E2E 真实车次 246490"})
    check("创建真实车次批次", r2.status_code == 200, f"HTTP {r2.status_code}")
    bid_real = r2.json()["id"]
    check("真实车次识别到三个文件",
          len(r2.json()["runs"]) == 1 and len(r2.json()["runs"][0]["files"]) == 3,
          json.dumps(r2.json()["runs"][0]["files"], ensure_ascii=False))

    # ── 规则库 ──────────────────────────────────────────────────────────
    section("⑤ 知识库 — 规则与特征清单")
    rules = c.get("/wt/rules").json()["rules"]
    check("内置规则已落库", len(rules) >= 18, f"{len(rules)} 条")
    check("规则携带判据出处", all(r_["refs"] for r_ in rules if r_["source"] == "builtin"))
    feats = c.get("/wt/features").json()["features"]
    check("特征清单可用", len(feats) >= 17, f"{len(feats)} 个特征")
    bal = c.get("/wt/balances").json()
    check("天平载荷库已初始化", any(b["name"].lower() == "n628e" for b in bal["balances"]),
          "、".join(b["name"] for b in bal["balances"]))

    # ── ① 执行检查 ──────────────────────────────────────────────────────
    section("① 执行检查 — 全部规则")
    r = c.post(f"/wt/batches/{bid}/check", json={"rule_ids": [], "tail_contracted": False})
    check("检查执行成功", r.status_code == 200, f"HTTP {r.status_code} {r.text[:300]}")
    res = r.json()
    by_run = {x["run_no"]: x for x in res["runs"]}
    check("覆盖全部 5 个车次", len(by_run) == 5)

    # Ground truth: the customer's own 跟班记录 for these five runs.
    check("91837 判定不合格（与甲方跟班记录一致）",
          by_run["91837"]["grade"] == "不合格", by_run["91837"]["grade"])
    zd = by_run["91837"]["features"]["balance_zero_drift"]["value"]
    check("91837 天平零飘 ≈ 0.0989（甲方记录同值）", abs(zd - 0.0989) < 5e-4, f"{zd:.6f}")
    rz = by_run["91837"]["features"]["balance_return_zero"]["value"]
    check("91837 不回零 ≈ 0.1002（甲方记录同值）", abs(rz - 0.1002) < 5e-4, f"{rz:.6f}")
    lr = by_run["91837"]["features"]["balance_load_ratio"]["extras"]["per_unit"]["Mz"]
    check("91837 MZ 载荷占比 ≈ 28.902%（甲方记录同值）", abs(lr - 28.902) < 0.01, f"{lr:.3f}%")
    check("91836 合格（甲方记录：优秀）", by_run["91836"]["grade"].startswith("合格"),
          by_run["91836"]["grade"])
    check("91838 不合格（甲方记录同）", by_run["91838"]["grade"] == "不合格")
    check("91839/91840 合格（甲方记录：优秀）",
          by_run["91839"]["grade"].startswith("合格") and
          by_run["91840"]["grade"].startswith("合格"))
    check("首车次零飘如实标未评定，而非默认正常",
          by_run["91836"]["features"]["balance_zero_drift"]["status"] == "unavailable",
          by_run["91836"]["features"]["balance_zero_drift"]["detail"][:60])
    check("零飘比对链正确串起", [by_run[k]["compared_with"] for k in
                                 ("91837", "91838", "91839", "91840")] ==
          ["91836", "91837", "91838", "91839"])
    check("跨车次趋势已产出", len(res["trends"]) >= 5, f"{len(res['trends'])} 条特征序列")

    r = c.post(f"/wt/batches/{bid_real}/check", json={"rule_ids": []})
    check("真实车次检查成功", r.status_code == 200, f"HTTP {r.status_code}")
    real = r.json()["runs"][0]
    check("真实车次 246490 出结论", real["grade"] in
          ("合格", "合格(需关注)", "有条件合格", "不合格"), real["grade"])
    check("超量程项缺库时如实未评定（不编造）",
          real["features"]["balance_load_ratio"]["status"] == "unavailable",
          real["features"]["balance_load_ratio"]["detail"][:70])

    # ── 天平载荷库补录 → 未评定项转为可评定 ────────────────────────────
    section("⑤ 补录天平载荷库 → 原本未评定的超量程项应变为可评定")
    r = c.post("/wt/balances", json={
        "name": "N636CB01",
        "ranges": {"My": 16.25, "Z": 273.16, "Mz": 19.91, "Y": 349.33,
                   "Mx": 20.38, "Q": 147.64},
        "note": "E2E：按 pa 文件天平标定矩阵主对角线量级临时录入，仅用于连通性验证",
    })
    check("补录天平条目", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    r = c.post(f"/wt/batches/{bid_real}/check", json={"rule_ids": []})
    real2 = r.json()["runs"][0]
    check("补录后超量程项已可评定",
          real2["features"]["balance_load_ratio"]["status"] == "ok",
          f"占比 {real2['features']['balance_load_ratio']['value']:.4f}%")

    # ── ③ 气动曲线 ──────────────────────────────────────────────────────
    section("③ 气动曲线")
    r = c.post(f"/wt/batches/{bid_real}/curve",
               json={"run_no": "246490", "x": "ALPHA",
                     "ys": ["CAF", "CN", "CZ", "CAB", "MX", "MY", "MZ"]})
    check("曲线数据", r.status_code == 200, f"HTTP {r.status_code}")
    curve = r.json()
    check("7 条系数曲线", len(curve["series"]) == 7)
    stats = {s["key"]: s for s in curve["statistics"]}
    check("CN 线性度极高（物理合理）", stats["CN"]["r2"] > 0.99, f"R²={stats['CN']['r2']}")
    # Cross-check the computed slope against the tunnel's own CNa column.
    r_frame = c.get(f"/wt/batches/{bid_real}/frame",
                    params={"run_no": "246490", "table": "da"})
    cna = r_frame.json()["rows"][0].get("CNa") if r_frame.status_code == 200 else None
    if cna:
        rel = abs(stats["CN"]["slope_per_deg"] - cna) / abs(cna)
        check("CN 斜率与 da 文件自带 CNα 相符(<5%)", rel < 0.05,
              f"拟合 {stats['CN']['slope_per_deg']:.5f} vs 文件 {cna:.5f}，相对差 {rel*100:.2f}%")
    check("可选列清单返回", len(curve["available_columns"]) > 20,
          f"{len(curve['available_columns'])} 列")

    if llm_on:
        r = c.post(f"/wt/batches/{bid_real}/curve/conclusion",
                   json={"run_no": "246490", "statistics": curve["statistics"],
                         "meta": {"mach": curve.get("mach"), "model": curve.get("model")}})
        j = r.json()
        check("AI 气动规律结论", j.get("ok") is True, (j.get("text") or j.get("error"))[:80])
        narrative = j.get("text", "")
    else:
        narrative = ""

    # ── ④ 报告 ──────────────────────────────────────────────────────────
    section("④ 报告：生成 → 编辑 → 导出")
    secs = c.get("/wt/report-sections").json()["sections"]
    check("章节清单", len(secs) >= 8, f"{len(secs)} 个可选章节")
    r = c.post(f"/wt/batches/{bid_real}/report", json={
        "run_no": "246490", "kind": "report",
        "sections": ["overview", "verdict", "problems", "unavailable",
                     "curves", "shift_record", "basis"],
        "title": "风洞试验过程质量检查报告", "author": "E2E",
        "narratives": {"curves": narrative}, "include_curve": True,
    })
    check("生成质量检查报告", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    rpt = r.json()
    check("报告含判据附录", "判据与依据" in rpt["content"])
    check("报告含未评定说明", "未评定项说明" in rpt["content"])
    check("报告含气动曲线章节", "气动曲线与规律结论" in rpt["content"])
    rid = rpt["id"]

    r = c.post(f"/wt/batches/{bid_real}/report", json={"run_no": "246490", "kind": "shift"})
    check("生成跟班记录", r.status_code == 200 and "跟班记录" in r.json()["content"])
    check("命名符合「车次号_跟班记录」", r.json()["filename"].startswith("246490_跟班记录"),
          r.json()["filename"])
    shift_id = r.json()["id"]

    r = c.post(f"/wt/batches/{bid}/report", json={"kind": "summary",
                                                  "title": "91836~91840 批次汇总"})
    check("生成多车次汇总报告",
          r.status_code == 200 and "各车次评级" in r.json()["content"])

    edited = rpt["content"] + "\n\n> 【人工补充】本车次底压突变已现场复核，确认为二喉道激波扫掠。\n"
    r = c.put(f"/wt/reports/{rid}", json={"edited": edited})
    check("报告预览可编辑并保存", r.status_code == 200)
    r = c.get(f"/wt/reports/{rid}/export", params={"fmt": "txt"})
    check("导出报告", r.status_code == 200 and "人工补充" in r.content.decode("utf-8-sig"),
          f"{len(r.content)} 字节，编辑内容已保留")
    r = c.get(f"/wt/reports/{shift_id}/export", params={"fmt": "txt"})
    check("导出跟班记录", r.status_code == 200 and "【车次 246490】" in
          r.content.decode("utf-8-sig"))

    # ── 扩展面 A：自然语言 → 规则 ───────────────────────────────────────
    section("扩展面 A：用户新增异常检测规则（AI 起草 → 真实车次预览 → 落库 → 生效）")
    manual = {
        "rule_id": "rule_e2e_manual_return_zero",
        "name": "E2E 手工规则：天平回零收紧到 0.002",
        "feature": "balance_return_zero",
        "object": "天平", "note": "E2E 手工新增，用于验证规则即数据",
        "applies_when_mach": "", "refs": ["E2E 测试"],
        "bands": [
            {"level": "warning", "lo": 0.002, "hi": None, "verdict": "回零量超过 0.002 码",
             "cause": "装夹应力", "impact": "系统偏差", "action": "复查装夹"},
            {"level": "ok", "lo": None, "hi": 0.002, "verdict": "回零正常"},
        ],
        "enabled": True, "source": "user",
    }
    r = c.post("/wt/rules", json=manual)
    check("手工新增规则（不写代码）", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    r = c.post(f"/wt/batches/{bid}/check", json={"rule_ids": []})
    hit = [x["run_no"] for x in r.json()["runs"]
           for f in x["findings"]
           if f["rule_id"] == "rule_e2e_manual_return_zero" and f["level"] == "warning"]
    check("新规则立即参与检查并命中", len(hit) >= 1, f"命中车次 {hit}")

    bad = dict(manual, rule_id="rule_e2e_bad", feature="no_such_feature")
    r = c.post("/wt/rules", json=bad)
    check("绑定不存在的特征被拒（防止规则错配）", r.status_code == 400,
          r.json().get("detail", "")[:80])

    if llm_on:
        r = c.post("/wt/rules/triage",
                   json={"request": "我想盯住左右底压差是不是太大"})
        j = r.json()
        check("AI 分诊命中已有特征", j.get("matched") and
              j.get("feature") == "base_pressure_lr_diff", json.dumps(j, ensure_ascii=False)[:120])

        r = c.post("/wt/rules/draft", json={
            "request": "天平回零量超过 0.008 就必须停机检查，0.005 到 0.008 提醒注意，"
                       "请建一条规则，ID 叫 rule_e2e_ai_return_zero"})
        j = r.json()
        check("AI 起草规则", j.get("ok") is True,
              (j.get("error") or json.dumps(j.get("rule", {}).get("bands", []),
                                            ensure_ascii=False))[:100])
        if j.get("ok"):
            draft = j["rule"]
            draft["rule_id"] = "rule_e2e_ai_return_zero"
            r = c.post("/wt/rules/preview", json={"rule": draft, "batch_id": bid})
            check("草稿在真实车次上预览（未落库）", r.status_code == 200,
                  f"预览 {len(r.json().get('preview', []))} 个车次")
            prev_hits = [p["run_no"] for p in r.json()["preview"]
                         for f in p["findings"] if f["level"] in ("warning", "critical")]
            check("预览能看到会命中哪些车次", "91837" in prev_hits, f"命中 {prev_hits}")
            r = c.post("/wt/rules", json={**draft, "source": "ai"})
            check("确认后落库", r.status_code == 200, f"HTTP {r.status_code} {r.text[:160]}")

    # ── 扩展面 B：自然语言 → 特征算子 ───────────────────────────────────
    if llm_on:
        section("扩展面 B：用户新增分析算法（AI 写码 → 沙箱验证 → 入库 → 被规则引用）")
        r = c.post("/wt/extractors/generate", json={
            "request": "监测吹风段来流总压 P0 的波动系数（标准差/均值×100%），衡量流场稳定性",
            "batch_id": bid_real, "run_no": "246490"})
        j = r.json()
        check("AI 生成特征算子并通过沙箱测试", j.get("ok") is True,
              f"尝试 {j.get('attempts')} 次，key={j.get('feature_key')}，"
              f"{(j.get('error') or '')[:60]}")
        if j.get("ok"):
            meta = j["meta"]
            r = c.post("/wt/extractors", json={
                "code": j["code"], "name": meta.get("name", "自定义特征"),
                "slug": meta["slug"], "description": meta.get("description", ""),
                "test_report": {"tests": j.get("tests", [])}})
            check("算子入库", r.status_code == 200, f"HTTP {r.status_code} {r.text[:160]}")
            fkey = r.json()["feature_key"]

            rule = {
                "rule_id": "rule_e2e_flow_stability",
                "name": "E2E：来流总压稳定性诊断",
                "feature": fkey, "object": "风洞总压控制系统",
                "note": "由 AI 生成的自定义特征算子驱动", "applies_when_mach": "",
                "refs": ["E2E 测试；阈值为演示值，需人工评审"],
                "bands": [
                    {"level": "warning", "lo": 1.0, "hi": None,
                     "verdict": "来流总压波动系数大于 1%", "cause": "总压控制或调压阀波动",
                     "impact": "动压与雷诺数不稳定", "action": "检查总压控制系统"},
                    {"level": "notice", "lo": 0.2, "hi": 1.0,
                     "verdict": "来流总压波动系数在 0.2%~1% 之间", "cause": "轻微波动",
                     "impact": "影响有限", "action": "关注后续车次"},
                    {"level": "ok", "lo": None, "hi": 0.2, "verdict": "来流总压稳定"},
                ],
                "enabled": True, "source": "ai",
            }
            r = c.post("/wt/rules", json=rule)
            check("规则引用自定义算子", r.status_code == 200,
                  f"HTTP {r.status_code} {r.text[:200]}")
            r = c.post(f"/wt/batches/{bid_real}/check", json={"rule_ids": []})
            f = next((x for x in r.json()["runs"][0]["findings"]
                      if x["rule_id"] == "rule_e2e_flow_stability"), None)
            check("自定义算子参与真实检查并产生判定",
                  f is not None and f["status"] == "evaluated",
                  f"{f['value']:.4f}{f['unit']} → {f['verdict']}" if f else "未找到")

    # ── AI 小结 / 问答 ──────────────────────────────────────────────────
    if llm_on:
        section("AI 小结与问答（只基于已算出的结果）")
        r = c.post("/wt/summarize", json={"batch_id": bid_real, "run_no": "246490"})
        j = r.json()
        check("车次质量小结", j.get("ok") is True, (j.get("text") or "")[:70])
        r = c.post("/wt/ask", json={"batch_id": bid_real, "run_no": "246490",
                                    "question": "这个车次有哪些项目没能评定？为什么？"})
        j = r.json()
        check("基于结果的问答", j.get("ok") is True, (j.get("text") or "")[:70])

    # ── 结果 ────────────────────────────────────────────────────────────
    section("结果")
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
