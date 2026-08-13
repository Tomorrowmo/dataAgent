"""HTTP test of the multi-run capabilities on the customer's 130-run entry.

Exercises everything the 20260225《车次及马赫数绘图》note asks for, plus the
analyses that entry makes possible, against the real ``FromC/testdata`` files:

  * upload 130 runs (390 files) and check them
  * run list with state, and the (Mach, β) × deflection coverage matrix
  * 车次序列绘图 sorted by deflection
  * drag polar (x = CN) and stability plot (x = CN, y = MZG1)
  * 差量 / 比值 vs a baseline run
  * 随马赫数变化 at selected α, including the two-group form
  * 舵效 (ΔY, ΔY/Δδ), 舵偏响应 with saturation, ±δ symmetry
  * repeatability (correctly reports "no repeat runs" for a parametric matrix)
  * CSV export

Physics is asserted, not just HTTP status: transonic drag rise, falling
supersonic control effectiveness, monotone control increments. A plumbing test
that passes on wrong numbers is worth little.

    ./.venv/Scripts/python.exe wt_matrix_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

import httpx

BASE = os.environ.get("WT_API", "http://127.0.0.1:8077/api")
EMAIL = os.environ.get("WT_TEST_EMAIL", "wt-matrix@example.com")
PASSWORD = os.environ.get("WT_TEST_PASSWORD", "wt-matrix-pass-2026")
DATA = Path(os.environ.get("WT_TESTDATA", r"d:/Git/Personal/WTDataAgent/FromC/testdata"))

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
    (PASSED if cond else FAILED).append(name if cond else f"{name}: {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def section(t: str) -> None:
    print(f"\n{'=' * 76}\n{t}\n{'=' * 76}")


def main() -> int:
    if not DATA.exists():
        print(f"找不到测试数据：{DATA}")
        return 2
    c = _client(BASE)

    section("0. 登录并清理上一轮残留")
    r = c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        r = c.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD,
                                         "name": "WT Matrix"})
    check("认证", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
        return 1
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    for b in c.get("/wt/batches").json():
        c.delete(f"/wt/batches/{b['id']}")

    section("① 导入 130 个车次（390 个文件）")
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream"))
             for sub in ("ca", "da", "temp") for p in sorted((DATA / sub).iterdir())
             if p.is_file()]
    check("文件齐备", len(files) == 390, f"{len(files)} 个")
    r = c.post("/wt/batches", files=files, data={"name": "FromC 全量 130 车次"})
    check("上传成功", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    batch = r.json()
    bid = batch["id"]
    check("识别出 130 个车次", len(batch["runs"]) == 130, f"{len(batch['runs'])}")
    check("每个车次三文件齐全",
          all(len(x["files"]) == 3 for x in batch["runs"]),
          f"缺文件的车次 {[x['run_no'] for x in batch['runs'] if len(x['files']) != 3][:5]}")

    section("① 全量质量检查")
    r = c.post(f"/wt/batches/{bid}/check", json={"rule_ids": []})
    check("检查完成", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    res = r.json()
    s = res["summary"]
    check("覆盖 130 个车次", s["run_count"] == 130)
    check("超量程项已可评定（N636CB01 已内置载荷库）",
          all(x["features"]["balance_load_ratio"]["status"] == "ok"
              for x in res["runs"]),
          "首车次占比 %.2f%%" % res["runs"][0]["features"]["balance_load_ratio"]["value"])
    zero_first = res["runs"][0]["features"]["balance_zero_drift"]["status"]
    check("首车次零飘如实未评定", zero_first == "unavailable")

    # Trend must NOT fire on everything — that was the bug this entry exposed.
    flagged = [t for t in res["trends"] if t["flagged"]]
    indep = [t for t in res["trends"] if not t["state_dependent"]]
    not_analysed = [t for t in res["trends"] if t.get("analysed") is False]
    check("仪器健康（零点）类全批次可比", len(indep) >= 4, f"{len(indep)} 条")
    check("状态相关量在多构型批次中不做趋势判定并写明理由",
          len(not_analysed) >= 10 and all("不做趋势判定" in t["headline"] for t in not_analysed),
          f"{len(not_analysed)} 条未判定")
    check("趋势告警收敛（早期实现曾 15/17 全报）", len(flagged) <= 5,
          f"{len(flagged)}/{len(res['trends'])} 条告警")

    section("车次清单与状态矩阵")
    runs = c.get(f"/wt/batches/{bid}/runs").json()
    check("车次清单带状态", runs["count"] == 130 and runs["runs"][0]["state"]["M"] is not None,
          f"Ma 取值 {runs['machs']}")
    check("6 个马赫数", len(runs["machs"]) == 6, str(runs["machs"]))
    check("可选系数列 ≥ 18", len(runs["columns"]) >= 18, f"{len(runs['columns'])} 列")
    mat = c.get(f"/wt/batches/{bid}/matrix").json()
    check("12 个 (Ma,β) 区块", mat["block_count"] == 12, str(mat["block_count"]))
    check("每个区块都有 δ=0 基准车次", not mat["without_baseline"],
          str(mat["without_baseline"]))

    section("③b 车次序列绘图（需求：按舵偏角排序）")
    sel = [x["run_no"] for x in runs["runs"]
           if x["state"]["M"] == 1.741 and x["state"]["BETA"] == 0
           and (x["state"]["dy"] or 0) == 0 and (x["state"]["dx"] or 0) == 0]
    check("选出 Ma1.741/β0 的 δz 系列", len(sel) == 7, f"{len(sel)} 个车次")
    r = c.post(f"/wt/batches/{bid}/compare/runs",
               json={"run_nos": sel, "x": "ALPHA", "ys": ["CN"], "sort_by": ["dz"]})
    check("绘图接口", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    cur = r.json()
    dzs = [l["dz"] for l in cur["legend"]]
    check("图例按 δz 升序排列", dzs == sorted(dzs), str(dzs))
    check("图例携带状态（车次/β/φ/δ）", all("BETA" in l for l in cur["legend"]))

    section("③b 极曲线与静稳定性图（横轴取 CN）")
    r = c.post(f"/wt/batches/{bid}/compare/runs",
               json={"run_nos": sel[:1], "x": "CN", "ys": ["CD", "MZG1"]})
    check("以 CN 为横轴", r.status_code == 200 and len(r.json()["series"]) == 2,
          r.json().get("x_label", ""))

    section("③b 差量对比（需求：求差量 / 相对基准比值）")
    base = next(x["run_no"] for x in runs["runs"]
                if x["run_no"] in sel and (x["state"]["dz"] or 0) == 0)
    r = c.post(f"/wt/batches/{bid}/compare/runs",
               json={"run_nos": sel, "x": "ALPHA", "ys": ["CN"],
                     "baseline": base, "mode": "delta", "sort_by": ["dz"]})
    check("差量模式", r.status_code == 200, f"HTTP {r.status_code}")
    d = r.json()
    at0 = {}
    for ser in d["series"]:
        for x, y in zip(ser["x"], ser["y"]):
            if abs(x) < 1e-6:
                at0[ser["state"]["dz"]] = y
    ordered = [at0[k] for k in sorted(at0)]
    check("ΔCN 随 δz 单调递增（舵效物理正确）",
          all(ordered[i] < ordered[i + 1] for i in range(len(ordered) - 1)),
          " ".join(f"{k:+g}°:{at0[k]:+.4f}" for k in sorted(at0)))
    check("基准车次自身差量为 0", abs(at0.get(0.0, 1)) < 1e-9)
    r = c.post(f"/wt/batches/{bid}/compare/runs",
               json={"run_nos": sel, "x": "ALPHA", "ys": ["CN"],
                     "baseline": base, "mode": "ratio"})
    check("比值模式", r.status_code == 200 and len(r.json()["series"]) == len(sel) - 1)

    section("③b 随马赫数变化（需求：选攻角序列 + 两组对比）")
    baselines = [x["run_no"] for x in runs["runs"]
                 if all((x["state"].get(k) or 0) == 0 for k in ("dz", "dy", "dx"))
                 and x["state"]["BETA"] == 0]
    check("6 个 β=0 基准车次", len(baselines) == 6, str(sorted(baselines)))
    r = c.post(f"/wt/batches/{bid}/compare/state",
               json={"run_nos": baselines, "state_var": "M",
                     "ys": ["CN", "CAF"], "alphas": [0.0, 2.0, 4.0]})
    check("随马赫数绘图", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")
    st = r.json()
    caf0 = next(x for x in st["series"] if x["coefficient"] == "CAF" and x["alpha"] == 0.0)
    pairs = dict(zip(caf0["x"], caf0["y"]))
    check("跨声速阻力上升（CAF: Ma0.8 → Ma1.05 明显增大）",
          pairs[1.05] > pairs[0.8] * 1.8,
          f"CAF Ma0.8={pairs[0.8]:.4f} → Ma1.05={pairs[1.05]:.4f}")
    r = c.post(f"/wt/batches/{bid}/compare/state",
               json={"run_nos": baselines, "state_var": "M", "ys": ["CN"],
                     "alphas": [0.0, 1.0], "alphas_2": [2.0, 3.0],
                     "group_label": "a", "group_label_2": "b"})
    j = r.json()
    check("两组攻角序列同图", j.get("two_groups") is True and len(j["series"]) == 4,
          f"{len(j['series'])} 条曲线，分组 {sorted({x['group'] for x in j['series']})}")

    section("舵效 / 舵偏响应 / 对称性")
    r = c.post(f"/wt/batches/{bid}/compare/effectiveness",
               json={"surface": "dz", "alphas": [0.0], "coeffs": ["CN"]})
    check("舵效计算", r.status_code == 200, f"HTTP {r.status_code}")
    rows = r.json()["rows"]
    by_mach = {}
    for row in rows:
        by_mach.setdefault(row["mach"], []).append(row["derivative_per_deg"])
    avg = {m: sum(v) / len(v) for m, v in by_mach.items()}
    check("舵效随马赫数下降（超声速段 < 跨声速段，物理正确）",
          avg[1.741] < avg[1.05],
          " ".join(f"Ma{m:g}:{a:+.5f}" for m, a in sorted(avg.items())))
    r = c.post(f"/wt/batches/{bid}/compare/response",
               json={"surface": "dz", "alphas": [0.0], "coeffs": ["CN"]})
    blocks = [b_ for b_ in r.json()["blocks"] if b_["coefficient"] == "CN"]
    check("舵偏响应给出线性段导数与饱和比", len(blocks) == 12
          and all(b_["linear_slope_per_deg"] for b_ in blocks),
          f"饱和比范围 {min(b_['saturation_ratio'] for b_ in blocks):.2f}"
          f"~{max(b_['saturation_ratio'] for b_ in blocks):.2f}")
    r = c.post(f"/wt/batches/{bid}/compare/symmetry",
               json={"surface": "dz", "alphas": [0.0, 2.0, 4.0], "coeffs": ["CN"]})
    sy = r.json()
    check("对称性校核", r.status_code == 200 and sy["pairs"], sy["note"][:90])
    check("判异是与同批次水平比，而非与 0 比（避免全面误报）",
          len(sy["flagged"]) < 0.2 * len(sy["pairs"]),
          f"{len(sy['flagged'])}/{len(sy['pairs'])} 命中")

    section("重复性（本批次为参数矩阵，无重复车次）")
    rp = c.get(f"/wt/batches/{bid}/repeatability").json()
    check("如实报告无重复车次，不编造精度指标",
          rp["repeated_group_count"] == 0 and not rp["table"],
          f"{rp['group_count']} 个状态全部只做一次")

    section("导出 CSV")
    r = c.post(f"/wt/batches/{bid}/compare/export",
               json={"kind": "runs", "run_nos": sel, "x": "ALPHA", "ys": ["CN"],
                     "baseline": base, "mode": "delta"})
    body = r.content.decode("utf-8-sig")
    check("导出差量数据", r.status_code == 200 and "246490" in body and "\n" in body,
          f"{len(body)} 字节，{len(body.splitlines())} 行")
    r = c.post(f"/wt/batches/{bid}/compare/export",
               json={"kind": "state", "run_nos": baselines, "state_var": "M",
                     "ys": ["CN"], "alphas": [0.0, 2.0]})
    check("导出随马赫数数据", r.status_code == 200
          and len(r.content.decode("utf-8-sig").splitlines()) >= 7)

    section("结果")
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
