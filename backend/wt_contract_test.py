"""风洞模块的实现无关验收契约。

这套测试只通过 HTTP 断言领域事实，不驱动浏览器、不依赖任何 DOM 结构。它存在的
理由是迁移：前端一旦重写（Next.js → 别的），``wt_ui_test.py`` 与
``wt_compare_ui_test.py`` 的 44 项断言会随之作废，但**它们断言的领域事实不该跟着
作废**。本文件把那些事实固定在 API 层，并补上此前只在浏览器里被断言过的三处缺口。

与既有测试的分工::

    wt_smoke_test.py     纯离线，不起服务   —— 算法与解析层
    wt_api_test.py       HTTP，功能路径      —— 走一遍用户流程
    wt_matrix_test.py    HTTP，130 车次      —— 多车次对比与物理正确性
    wt_contract_test.py  HTTP，验收契约      —— 本文件：数字对着 wt_golden.json，
                                               外加三处 UI-only 缺口的下沉

数值不写在代码里，全部来自 ``wt_golden.json``——重写后的实现是对着**数据**验收，
而不是对着旧实现的源码验收。

运行::

    ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8077
    ./.venv/Scripts/python.exe wt_contract_test.py

130 车次那一段需要 ``WT_TESTDATA`` 指向的大数据集；数据不在时该段跳过并明确说明，
不会伪装成通过。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

BASE = os.environ.get("WT_API", "http://127.0.0.1:8077/api")
EMAIL = os.environ.get("WT_TEST_EMAIL", "wt-contract@example.com")
PASSWORD = os.environ.get("WT_TEST_PASSWORD", "wt-contract-pass-2026")

#: 计算面 sidecar 没有登录入口——它的属主由启动它的网关决定。同一份契约要能验收
#: 两种部署形态，所以认证是可关的，而被验收的领域事实一条不变。
NO_AUTH = os.environ.get("WT_NO_AUTH", "").strip() not in ("", "0", "false", "False")

GOLDEN = Path(__file__).resolve().parent / "wt_golden.json"

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
MATRIX_DATA = Path(os.environ.get("WT_TESTDATA",
                                  r"d:/Git/Personal/WTDataAgent/FromC/testdata"))

PASSED: List[str] = []
FAILED: List[str] = []
SKIPPED: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        PASSED.append(name)
        print(f"  [PASS] {name}" + (f"  — {detail}" if detail else ""))
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}  — {detail}")
    return bool(cond)


def skip(name: str, why: str) -> None:
    SKIPPED.append(f"{name}: {why}")
    print(f"  [SKIP] {name}  — {why}")


def section(title: str) -> None:
    print(f"\n{'=' * 76}\n{title}\n{'=' * 76}")


def entries(d: Dict[str, Any]) -> List[tuple]:
    """Data entries of a golden-file object, skipping ``_``-prefixed metadata.

    The golden file carries its own provenance inline (``_about``, ``_note``)
    so a reader never has to hunt for what a number means. Those keys are
    documentation, not cases — iterate through this helper, never directly.
    """
    return [(k, v) for k, v in d.items() if not k.startswith("_")]


def dig(obj: Any, path: List[str]) -> Any:
    """Walk a golden-file ``path`` into a response object.

    Returns ``None`` on any missing link rather than raising, so a contract
    miss reports as a readable failed assertion instead of a stack trace.
    """
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _client(base: str) -> httpx.Client:
    # Same pool posture as wt_api_test: a long AI call idles the other
    # connections past uvicorn's keep-alive, so allow transport retries.
    return httpx.Client(base_url=base, timeout=600.0,
                        transport=httpx.HTTPTransport(retries=3))


def upload(c: httpx.Client, dirs: List[Path], name: str) -> Optional[Dict[str, Any]]:
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream"))
             for d in dirs if d.exists()
             for p in sorted(d.iterdir()) if p.is_file()]
    if not files:
        return None
    r = c.post("/wt/batches", files=files, data={"name": name})
    return r.json() if r.status_code == 200 else None


# ──────────────────────────────────────────────────────────────────────────
# 契约段落
# ──────────────────────────────────────────────────────────────────────────

def assert_template_batch(c: httpx.Client, g: Dict[str, Any]) -> None:
    """5 个连续车次：判级、客户对齐数字、诚实缺口、比对链。"""
    spec = g["template_batch"]
    section("契约 1 — 甲方模板车次 91836~91840（客户数字逐位对齐）")

    batch = upload(c, [CA_DIR, PA_DIR, DA_DIR], "契约 模板批次")
    if not check("模板批次上传成功", batch is not None,
                 f"数据目录 {CA_DIR.parent}"):
        return
    check("自动按车次分组", len(batch["runs"]) == spec["run_count"],
          "车次=" + "、".join(x["run_no"] for x in batch["runs"]))

    r = c.post(f"/wt/batches/{batch['id']}/check",
               json={"rule_ids": [], "tail_contracted": False})
    if not check("检查执行成功", r.status_code == 200, f"HTTP {r.status_code}"):
        return
    res = r.json()
    by_run = {x["run_no"]: x for x in res["runs"]}

    for run_no, rule in entries(spec["grades"]):
        got = by_run.get(run_no, {}).get("grade", "<缺失>")
        ok = (got == rule["value"] if rule["match"] == "equals"
              else got.startswith(rule["value"]))
        check(f"{run_no} 判级 {rule['match']} 「{rule['value']}」", ok,
              f"实得「{got}」 / {rule['source']}")

    for key, m in entries(spec["measurements"]):
        got = dig(by_run.get(m["run_no"], {}), m["path"])
        ok = isinstance(got, (int, float)) and abs(got - m["expect"]) <= m["tol"]
        check(f"{m['run_no']} {m['label']} ≈ {m['expect']}（{m['source']}）", ok,
              f"实得 {got!r}，容差 ±{m['tol']}")

    for key, h in entries(spec["honest_gaps"]):
        got = dig(by_run.get(h["run_no"], {}), h["path"])
        check(f"{h['run_no']} 如实报未评定而非默认正常", got == h["expect"],
              f"实得 {got!r}；理由：{h['reason']}")

    chain = entries(spec["comparison_chain"])
    chain_ok = all(by_run.get(k, {}).get("compared_with") == v for k, v in chain)
    check("零飘比对链按车次顺序正确串起", chain_ok,
          str({k: by_run.get(k, {}).get("compared_with") for k, _ in chain}))

    check("跨车次趋势已产出",
          len(res.get("trends", [])) >= spec["min_trend_series"],
          f"{len(res.get('trends', []))} 条特征序列")

    # 供后续段落复用
    globals()["_TEMPLATE_RESULT"] = res


def assert_finding_contract(g: Dict[str, Any]) -> None:
    """缺口 1 — 非 ok 判定必须四段齐全。

    此前只有浏览器测试断言过「原因分析/影响评估/处理建议三段齐全」，靠的是这三个
    词出现在页面文本里。那是渲染层的证据，换个前端就没了。真正的契约是：每条非 ok
    的 finding 都必须带着 verdict/cause/impact/action 四个字段，报告才有东西可列。
    """
    section("契约 2 — 判定四段齐全（缺口下沉：原 UI 断言「三段齐全」）")
    res = globals().get("_TEMPLATE_RESULT")
    if res is None:
        skip("判定四段齐全", "模板批次未成功检查，无 findings 可验")
        return

    fc = g["finding_contract"]
    required = fc["required_fields_on_non_ok"]
    non_ok_levels = set(fc["levels_considered_non_ok"])

    non_ok = [(run["run_no"], f)
              for run in res["runs"]
              for f in run.get("findings", [])
              if f.get("level") in non_ok_levels
              and f.get("status", "evaluated") == "evaluated"]

    if not check("批次中存在非 ok 判定可供校验", len(non_ok) > 0,
                 f"{len(non_ok)} 条"):
        return

    incomplete = [(run_no, f.get("rule_id"), field)
                  for run_no, f in non_ok
                  for field in required
                  if not str(f.get(field, "")).strip()]
    check(f"每条非 ok 判定四段齐全（{'/'.join(required)}）",
          not incomplete,
          f"{len(non_ok)} 条判定全齐" if not incomplete
          else f"{len(incomplete)} 处缺失，例：{incomplete[:3]}")

    # 报告要真的把四段列出来——这是 UI 断言的另一半（报告正文里三段可见）。
    labels = ["原因分析", "影响评估", "处理建议"]
    globals()["_NON_OK_SAMPLE"] = non_ok[0] if non_ok else None
    globals()["_REPORT_LABELS"] = labels


def assert_knowledge_base(c: httpx.Client, g: Dict[str, Any]) -> None:
    """知识库下限，以及缺口 2 — 「默认全部勾选」的 API 等价物。"""
    section("契约 3 — 知识库下限与默认检查集（缺口下沉：原 UI 断言「默认全选」）")
    kb = g["knowledge_base"]

    rules = c.get("/wt/rules").json()["rules"]
    check("内置规则已落库", len(rules) >= kb["min_rules"],
          f"{len(rules)} 条 / 下限 {kb['min_rules']}")

    if kb["builtin_rules_have_refs"]:
        missing = [r["rule_id"] for r in rules
                   if r.get("source") == "builtin" and not r.get("refs")]
        check("内置规则全部携带判据出处", not missing,
              f"缺出处：{missing[:5]}" if missing else "全部有出处")

    # 浏览器测试数的是「勾上的复选框 ≥ 18」。它在 API 层的等价物是：默认参与检查的
    # 规则集合 = enabled 的规则集合（pipeline 里 rule_ids 为空即取全部 enabled）。
    enabled = [r for r in rules if r.get("enabled")]
    check("默认参与检查的规则数达标（= UI 默认勾选项）",
          len(enabled) >= kb["min_enabled_rules"],
          f"{len(enabled)} 条 enabled / 下限 {kb['min_enabled_rules']}")

    feats = c.get("/wt/features").json()["features"]
    check("特征清单可用", len(feats) >= kb["min_features"],
          f"{len(feats)} 个特征")

    bal = c.get("/wt/balances").json()["balances"]
    check("天平载荷库已初始化",
          any(b["name"].lower() == kb["seed_balance"] for b in bal),
          "、".join(b["name"] for b in bal))


def assert_real_run(c: httpx.Client, g: Dict[str, Any]) -> None:
    """真实车次：未评定 → 补录量程 → 转为可评定；曲线。"""
    spec = g["real_run"]
    section("契约 4 — 真实车次 246490：诚实缺口可闭合")

    batch = upload(c, [INPUT_DIR], "契约 真实车次")
    if not check("真实车次上传成功", batch is not None, str(INPUT_DIR)):
        return
    bid = batch["id"]
    check("识别到三类文件",
          len(batch["runs"]) == 1 and len(batch["runs"][0]["files"]) == spec["file_count"],
          json.dumps(batch["runs"][0]["files"], ensure_ascii=False))

    # 先清掉可能已存在的 N636CB01，保证「补录前未评定」这一步真的从缺库开始。
    for b in c.get("/wt/balances").json()["balances"]:
        if b["name"].upper() == spec["balance_entry"]["name"].upper():
            c.delete(f"/wt/balances/{b['id']}")

    r = c.post(f"/wt/batches/{bid}/check", json={"rule_ids": []})
    if not check("真实车次检查成功", r.status_code == 200, f"HTTP {r.status_code}"):
        return
    run = r.json()["runs"][0]
    check("出结论且等级在合法域内", run["grade"] in spec["grade_domain"], run["grade"])

    before = spec["load_ratio_unavailable_before_balance"]
    got = dig(run, before["path"])
    check("缺天平量程时如实未评定（不编造）", got == before["expect"],
          f"实得 {got!r}；{before['reason']}")

    be = spec["balance_entry"]
    r = c.post("/wt/balances", json={"name": be["name"], "ranges": be["ranges"],
                                     "note": be["note"]})
    check("补录天平条目", r.status_code == 200, f"HTTP {r.status_code}")

    r = c.post(f"/wt/batches/{bid}/check", json={"rule_ids": []})
    run2 = r.json()["runs"][0]
    after = spec["load_ratio_ok_after_balance"]
    got2 = dig(run2, after["path"])
    check("补录后同一项转为可评定（证明未评定=缺输入而非缺能力）",
          got2 == after["expect"], f"实得 {got2!r}；{after['reason']}")

    cv = spec["curve"]
    r = c.post(f"/wt/batches/{bid}/curve",
               json={"run_no": spec["run_no"], "x": cv["x"], "ys": cv["ys"]})
    if check("气动曲线数据", r.status_code == 200, f"HTTP {r.status_code}"):
        check(f"{cv['series_count']} 条系数曲线",
              len(r.json()["series"]) == cv["series_count"],
              f"{len(r.json()['series'])} 条")

    globals()["_REAL_BID"] = bid


def assert_report(c: httpx.Client, g: Dict[str, Any]) -> None:
    """报告：章节、必含内容、四段渲染、编辑往返、命名约定。"""
    spec = g["report"]
    section("契约 5 — 报告生成、四段渲染、编辑往返与命名约定")
    bid = globals().get("_REAL_BID")
    if bid is None:
        skip("报告契约", "真实车次批次不可用")
        return

    secs = c.get("/wt/report-sections").json()["sections"]
    check("可选章节清单", len(secs) >= spec["min_sections"],
          f"{len(secs)} 个 / 下限 {spec['min_sections']}")

    r = c.post(f"/wt/batches/{bid}/report", json={
        "run_no": "246490", "kind": "report",
        "sections": ["overview", "verdict", "problems", "unavailable",
                     "curves", "shift_record", "basis"],
        "title": "契约测试 质量检查报告", "author": "contract",
        "include_curve": True,
    })
    if not check("生成质量检查报告", r.status_code == 200,
                 f"HTTP {r.status_code} {r.text[:160]}"):
        return
    rpt = r.json()
    content = rpt["content"]
    for must in spec["must_contain"]:
        check(f"报告含「{must}」", must in content)

    # UI 曾断言页面上能同时看到三段。报告正文是它在服务端的等价物。
    labels = globals().get("_REPORT_LABELS") or ["原因分析", "影响评估", "处理建议"]
    present = [l for l in labels if l in content]
    check("异常项明细逐条列出四段中的三段标签",
          len(present) == len(labels),
          f"命中 {present}；缺 {[l for l in labels if l not in present]}"
          if len(present) != len(labels) else "、".join(present))

    marker = "【契约测试】人工补充内容，用于验证编辑往返。"
    r = c.put(f"/wt/reports/{rpt['id']}", json={"edited": content + "\n\n> " + marker})
    check("报告可编辑并保存", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.get(f"/wt/reports/{rpt['id']}/export", params={"fmt": "txt"})
    check("导出文件保留人工编辑内容（编辑往返）",
          r.status_code == 200 and marker in r.content.decode("utf-8-sig"),
          f"{len(r.content)} 字节")

    r = c.post(f"/wt/batches/{bid}/report", json={"run_no": "246490", "kind": "shift"})
    if check("生成跟班记录", r.status_code == 200, f"HTTP {r.status_code}"):
        sr = r.json()
        check("命名符合「车次号_跟班记录」约定",
              sr["filename"].startswith(spec["shift_record_filename_prefix"]),
              sr["filename"])
        for must in spec["shift_record_must_contain"]:
            check(f"跟班记录含「{must}」", must in sr["content"])


def assert_matrix(c: httpx.Client, g: Dict[str, Any]) -> None:
    """130 车次：区块、序列筛选，以及缺口 3 — 操纵增量明细。"""
    spec = g["matrix_entry"]
    section("契约 6 — 130 车次矩阵与操纵增量明细（缺口下沉：原 UI 断言）")

    if not MATRIX_DATA.exists():
        skip("130 车次矩阵全段", f"数据集不在 {MATRIX_DATA}（设 WT_TESTDATA 指向它）")
        return

    files = [("files", (p.name, p.read_bytes(), "application/octet-stream"))
             for sub in ("ca", "da", "temp") if (MATRIX_DATA / sub).exists()
             for p in sorted((MATRIX_DATA / sub).iterdir()) if p.is_file()]
    r = c.post("/wt/batches", files=files, data={"name": "契约 130 车次"})
    if not check("130 车次上传成功", r.status_code == 200, f"HTTP {r.status_code}"):
        return
    bid = r.json()["id"]
    check(f"识别出 {spec['run_count']} 个车次",
          len(r.json()["runs"]) == spec["run_count"], f"{len(r.json()['runs'])}")

    runs = c.get(f"/wt/batches/{bid}/runs").json()
    check(f"{spec['mach_count']} 个马赫数",
          len(runs["machs"]) == spec["mach_count"], str(runs["machs"]))
    check(f"可选系数列 ≥ {spec['min_coefficient_columns']}",
          len(runs["columns"]) >= spec["min_coefficient_columns"],
          f"{len(runs['columns'])} 列")

    mat = c.get(f"/wt/batches/{bid}/matrix").json()
    check(f"{spec['block_count']} 个 (Ma, β) 区块",
          mat["block_count"] == spec["block_count"], str(mat["block_count"]))
    if spec["every_block_has_zero_deflection_baseline"]:
        check("每个区块都有 δ=0 基准车次", not mat["without_baseline"],
              str(mat["without_baseline"]))

    ds = spec["deflection_series"]
    # 「仅升降舵 δz 单独偏转」= 同区块内 dy/dx 全零且 dz 非零。δ 全零的那个车次是
    # 基准，不属于偏转序列——UI 上是两次「加入筛选结果」累加成 7 个，别混为一谈。
    block = [x for x in runs["runs"]
             if x["state"]["M"] == ds["mach"] and x["state"]["BETA"] == ds["beta"]
             and (x["state"]["dy"] or 0) == 0 and (x["state"]["dx"] or 0) == 0]
    deflected = [x["run_no"] for x in block if (x["state"]["dz"] or 0) != 0]
    baseline = [x["run_no"] for x in block if (x["state"]["dz"] or 0) == 0]
    check(f"Ma{ds['mach']}/β{ds['beta']} 的 δz 偏转序列共 {ds['expect_runs']} 个车次",
          len(deflected) == ds["expect_runs"], f"{len(deflected)} 个：{deflected}")
    check(f"加上 δ=0 基准共 {ds['with_baseline']} 个车次",
          len(deflected) + len(baseline) == ds["with_baseline"],
          f"偏转 {len(deflected)} + 基准 {baseline}")

    # 缺口 3：浏览器测试断言页面出现「操纵增量明细」。服务端等价物是舵效结果里
    # 逐舵偏的增量行——没有它，页面那张表无从渲染。
    r = c.post(f"/wt/batches/{bid}/compare/effectiveness",
               json={"surface": "dz", "alphas": [0.0], "coeffs": ["CN"]})
    if check("舵效计算", r.status_code == 200, f"HTTP {r.status_code}"):
        rows = r.json().get("rows", [])
        # 每一行本身就是一条操纵增量记录：某车次在某舵偏下相对同区块 δ=0 基准的
        # 增量。页面上那张「操纵增量明细」表就是它的渲染，缺任一字段都渲染不出来。
        need = ["deflection", "delta", "baseline_run", "derivative_per_deg"]
        complete = [x for x in rows if all(k in x for k in need)]
        check("舵效结果携带逐舵偏的操纵增量明细", len(complete) == len(rows) and rows,
              f"{len(complete)}/{len(rows)} 行字段齐全"
              + (f"，字段 {need}" if rows else "，无数据行"))
        if rows:
            check("增量明细的舵偏角非零且标出基准车次",
                  all(x["deflection"] != 0 and x["baseline_run"] for x in complete),
                  f"样例 {rows[0]['run_no']} δ={rows[0]['deflection']} "
                  f"Δ={rows[0]['delta']} 基准={rows[0]['baseline_run']}")


def assert_codegen_gate(c: httpx.Client) -> None:
    """自扩展通道：沙箱门禁与畸形 META 的处理。

    这一段是在迁移中发现真实缺陷后补的：AI 写的 META 很自然会把 returns 写成一个
    描述输出结构的对象，而 Algorithm.returns 是 String(32) 列——旧实现直接把它塞
    进去，请求以未捕获的 500 死掉。任何人或模型上传这样一份算法都会踩到。

    契约是：畸形 META 必须以指名字段的 400 被拒，而不是 500，也不能被悄悄改写成
    别的值——后者会让入库结果和源码自相矛盾。
    """
    section("契约 7 — 自扩展：沙箱门禁与畸形 META（迁移中发现的缺陷）")

    good = (
        "import pandas as pd\n\n"
        "META = {\n"
        '    "name": "契约测试 变异系数",\n'
        '    "slug": "contract_cv_probe",\n'
        '    "category": "reduce",\n'
        '    "description": "CV = std/mean",\n'
        '    "params_schema": {},\n'
        '    "returns": "dataframe",\n'
        "}\n\n"
        "def run(df, **params):\n"
        "    rows = []\n"
        "    for col in df.columns:\n"
        '        s = pd.to_numeric(df[col], errors="coerce")\n'
        "        m = s.mean()\n"
        "        rows.append({\n"
        '            "column": col,\n'
        '            "cv": float(s.std(ddof=0) / m) if m else None,\n'
        "        })\n"
        "    return pd.DataFrame(rows)\n"
    )

    # 自带一份最小数据集：run(df) 需要真实输入，不传 dataset_id 时 df 是 None，
    # 测出来的只会是「算法没处理 None」，而不是沙箱通不通。
    csv = b"a,b\n1,2\n2,4\n3,6\n4,9\n"
    up = c.post("/datasets", files={"file": ("contract_probe.csv", csv, "text/csv")},
                data={"name": "契约测试 探针数据"})
    dataset_id: Optional[int] = None
    if up.status_code == 200:
        dataset_id = up.json().get("dataset", {}).get("id")
    check("探针数据集就绪", dataset_id is not None, f"HTTP {up.status_code} id={dataset_id}")

    payload: Dict[str, Any] = {"code": good, "params": {}}
    if dataset_id is not None:
        payload["dataset_id"] = dataset_id
    r = c.post("/algorithms/test", json=payload)
    if check("合法算法通过沙箱", r.status_code == 200, f"HTTP {r.status_code}"):
        d = r.json()
        check("静态校验通过且识别出 run/META",
              d["validation"]["ok"] and d["validation"]["has_run"]
              and d["validation"]["has_meta"],
              json.dumps(d["validation"], ensure_ascii=False))
        check("沙箱执行成功", d["execution"].get("status") == "ok",
              str(d["execution"].get("error"))[:120])

    # 恶意代码必须被静态校验拦下，而不是靠运行时侥幸。
    r = c.post("/algorithms/test", json={"code": "import os\n\ndef run(df):\n    return df\n"})
    if r.status_code == 200:
        v = r.json()["validation"]
        check("AST 白名单拦截 import os", not v["ok"] and bool(v["errors"]),
              "；".join(v["errors"])[:120])

    # 缺陷复现：returns 写成对象。
    bad = good.replace('"returns": "dataframe",',
                       '"returns": {"description": "两列表", "columns": ["column", "cv"]},')
    bad = bad.replace('"slug": "contract_cv_probe"', '"slug": "contract_cv_badmeta"')
    r = c.post("/algorithms/save", json={"code": bad, "source": "ai",
                                         "test_report": {"all_tests_passed": True}})
    check("META.returns 非字符串时以 400 被拒（而非 500）",
          r.status_code == 400, f"HTTP {r.status_code}: {r.text[:160]}")
    if r.status_code == 400:
        check("错误信息指名了出问题的字段", "returns" in r.text,
              r.text[:160])

    # 修好之后必须能入库，并且不被悄悄改值。
    r = c.post("/algorithms/save", json={"code": good, "source": "ai",
                                         "test_report": {"all_tests_passed": True}})
    if check("合法算法可入库", r.status_code == 200, f"HTTP {r.status_code} {r.text[:160]}"):
        saved = r.json()
        check("入库后 returns 与源码一致（未被悄悄改写）",
              saved.get("returns") == "dataframe", str(saved.get("returns")))
        check("沙箱通过的算法标记为已验证", saved.get("verified") is True,
              str(saved.get("verified")))
        listed = c.get("/algorithms").json()
        check("入库后立即出现在算法目录里",
              any(a["slug"] == "contract_cv_probe" for a in listed),
              f"目录共 {len(listed)} 个算法")

    # 迁移中发现的第二个缺陷：保存同一个 slug 是**插入新行**（版本递增），而各处
    # 按 slug 的查询写的是 scalar_one_or_none()——存到第三次就 MultipleResultsFound
    # 500，而且运行路径上是同样的写法，所以改过两次的算法之后再被调用也会 500。
    # 迭代一个算法是最正常不过的事，这条必须一直成立。
    for n in (2, 3, 4):
        r = c.post("/algorithms/save", json={"code": good, "source": "ai",
                                             "test_report": {"all_tests_passed": True}})
        check(f"同一 slug 第 {n} 次保存仍成功（版本递增，不是 500）",
              r.status_code == 200, f"HTTP {r.status_code}: {r.text[:160]}")
        if r.status_code != 200:
            break

    if dataset_id is not None:
        r = c.post("/algorithms/run-to-dataset",
                   json={"slug": "contract_cv_probe", "dataset_id": dataset_id, "params": {}})
        check("多版本算法仍可被调用（运行路径同样不炸）",
              r.status_code == 200, f"HTTP {r.status_code}: {r.text[:160]}")


def assert_pipeline(c: httpx.Client) -> None:
    """流程模板：存为配方、在新数据上重放、每步落带血缘的派生数据集。

    这里断言的是重放**真的把上一步的输出喂给了下一步**，而不是各步各自对着源数据
    跑一遍——后者也会返回一堆 200，看起来一样成功，但结果完全不同。判据是血缘链：
    第二步的父数据集必须是第一步的产出，而不是源数据集。
    """
    section("契约 8 — 流程模板：可复用配方与串联重放")

    csv = b"t,signal\n" + b"".join(
        f"{i * 0.1:.3f},{(i % 7) - 3 + (0.5 if i % 2 else -0.5):.4f}\n".encode()
        for i in range(120))
    up = c.post("/datasets", files={"file": ("contract_flow.csv", csv, "text/csv")},
                data={"name": "契约测试 流程源数据"})
    if not check("流程源数据集就绪", up.status_code == 200, f"HTTP {up.status_code}"):
        return
    src_id = up.json()["dataset"]["id"]

    r = c.post("/templates", json={
        "name": "契约测试 两步流程",
        "description": "savgol 平滑后做 z-score 归一化",
        "steps": [
            {"action": "run_tool", "slug": "savgol_filter",
             "params": {"columns": ["signal"], "window_length": 11, "polyorder": 3},
             "label": "平滑"},
            {"action": "run_tool", "slug": "normalize",
             "params": {"columns": ["signal"], "method": "zscore"}, "label": "归一化"},
        ],
    })
    if not check("模板创建成功", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}"):
        return
    tpl = r.json()
    check("模板记录了两个步骤", tpl.get("n_steps") == 2, str(tpl.get("n_steps")))

    r = c.post(f"/templates/{tpl['id']}/run",
               json={"dataset_id": src_id, "save_result": True, "param_overrides": {}})
    if not check("重放执行成功", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}"):
        return
    res = r.json()
    steps = res.get("steps") or []
    check("两步都跑完且都成功",
          len(steps) == 2 and all(s.get("status") == "ok" for s in steps),
          json.dumps([{s.get("label"): s.get("status")} for s in steps], ensure_ascii=False))

    derived = res.get("derived_chain") or []
    check("每步都落了带血缘的派生数据集", len(derived) == 2,
          f"{len(derived)} 个：{[d.get('id') for d in derived]}")
    if len(derived) != 2:
        return

    # 串联的判据：第二步的父必须是第一步的产出。
    all_ds = {d["id"]: d for d in c.get("/datasets").json()}
    first, second = derived[0]["id"], derived[1]["id"]
    check("第一步派生自源数据集",
          all_ds.get(first, {}).get("derived_from") == src_id,
          f"#{first}.derived_from={all_ds.get(first, {}).get('derived_from')}，期望 {src_id}")
    check("第二步派生自第一步的产出（证明确实串联，而非各自跑源数据）",
          all_ds.get(second, {}).get("derived_from") == first,
          f"#{second}.derived_from={all_ds.get(second, {}).get('derived_from')}，期望 {first}")

    ops = [str(((all_ds.get(i) or {}).get("lineage") or {}).get("op", {}).get("slug"))
           for i in (first, second)]
    check("血缘记录了各步用的算法", ops == ["savgol_filter", "normalize"], str(ops))

    listed = c.get("/templates").json()
    check("模板出现在模板列表里",
          any(t["id"] == tpl["id"] for t in listed), f"共 {len(listed)} 个模板")


def main() -> int:
    if not GOLDEN.exists():
        print(f"找不到黄金样本：{GOLDEN}")
        return 2
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))
    print(f"黄金样本：{GOLDEN.name}（冻结于 {g['_about']['frozen_at']}）")
    print(f"依据：{g['_about']['authority']}")

    c = _client(BASE)

    section("0 — 认证与残留清理（保证可重复运行）")
    if NO_AUTH:
        h = c.get("/wt/health")
        if not check("计算面就绪（无鉴权模式）", h.status_code == 200,
                     f"HTTP {h.status_code} {h.text[:160]}"):
            return 1
        print(f"  · 免登录，属主由实例决定：{c.get('/health').json().get('owner')}")
    else:
        r = c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        if r.status_code != 200:
            r = c.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD,
                                             "name": "WT Contract"})
        if not check("认证", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}"):
            return 1
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    removed = 0
    for b in c.get("/wt/batches").json():
        c.delete(f"/wt/batches/{b['id']}")
        removed += 1
    check("测试环境已重置", True, f"清理 {removed} 个残留批次")

    assert_template_batch(c, g)
    assert_finding_contract(g)
    assert_knowledge_base(c, g)
    assert_real_run(c, g)
    assert_report(c, g)
    assert_matrix(c, g)
    assert_codegen_gate(c)
    assert_pipeline(c)

    print("\n" + "=" * 76)
    print(f"验收契约：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项，"
          f"跳过 {len(SKIPPED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    for s in SKIPPED:
        print("  SKIPPED:", s)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
