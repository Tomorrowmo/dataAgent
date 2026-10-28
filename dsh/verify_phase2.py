"""独立核实第 2 阶段的端到端结果。

agent 会用自然语言描述它做了什么，那是叙述不是证据。本脚本绕开 agent，直接问计算面
要事实：派生数据集在不在、血缘对不对、以及**滤波是否真的降了噪**——最后一条才是
"算法跑对了"的判据，HTTP 200 不是。

演示数据里保留了 clean 真值列，所以降噪效果可以量化：滤波后对真值的 RMSE 应当明显
小于原始带噪信号对真值的 RMSE。

    ./backend/.venv/Scripts/python.exe dsh/verify_phase2.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

import httpx

BASE = os.environ.get("SIDECAR", "http://127.0.0.1:8078/api")
SOURCE_NAME = os.environ.get("DEMO_NAME", "演示信号 带噪正弦")

PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    (PASSED if cond else FAILED).append(name if cond else f"{name}: {detail}")
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return bool(cond)


def rmse(a: List[float], b: List[float]) -> float:
    n = min(len(a), len(b))
    if not n:
        return float("nan")
    return (sum((a[i] - b[i]) ** 2 for i in range(n)) / n) ** 0.5


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=180.0) as c:
        datasets: List[Dict[str, Any]] = c.get("/datasets").json()
        src = next((d for d in datasets if d["name"] == SOURCE_NAME), None)
        if not check("源数据集存在", src is not None, SOURCE_NAME):
            return 1

        derived = [d for d in datasets
                   if d.get("kind") == "derived" and d.get("derived_from") == src["id"]]
        if not check("agent 落下了派生数据集", bool(derived),
                     f"源 #{src['id']} 共 {len(derived)} 个派生"):
            return 1
        d = max(derived, key=lambda x: x["id"])
        print(f"  · 受检派生数据集：#{d['id']} {d['name']}")

        lineage = d.get("lineage") or {}
        op = lineage.get("op") or {}
        check("血缘记录了来源数据集", lineage.get("from") == src["id"],
              f"lineage.from={lineage.get('from')}，期望 {src['id']}")
        check("血缘记录了产生它的算法", bool(op.get("slug")),
              f"slug={op.get('slug')!r} label={op.get('label')!r}")
        check("用的是 savgol 滤波", "savgol" in str(op.get("slug", "")).lower(),
              f"实得 {op.get('slug')!r}")

        # 取全量数据做数值判断，不能只看预览的头几行。
        n = max(int(d.get("rows") or 0), 1)
        prev = c.get(f"/datasets/{d['id']}/preview", params={"limit": n}).json()
        cols = list(prev.get("columns") or [])
        rows = list(prev.get("rows") or [])
        check("派生数据集可读且有数据", bool(rows), f"{len(rows)} 行 / {len(cols)} 列")

        # 找出滤波产出的那一列：既不是原三列，又是数值列。
        base_cols = {"t", "clean", "signal"}
        extra = [x for x in cols if x not in base_cols]
        if not check("产生了新的一列（滤波结果）", bool(extra), f"列={cols}"):
            return 1
        out_col = extra[0]
        print(f"  · 滤波输出列：{out_col}")

        def col(name: str) -> List[float]:
            vals = []
            for r in rows:
                v = r.get(name)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
            return vals

        clean, noisy, filt = col("clean"), col("signal"), col(out_col)
        check("三列数值齐全", len(clean) == len(noisy) == len(filt) and len(clean) > 100,
              f"clean={len(clean)} signal={len(noisy)} {out_col}={len(filt)}")

        r_noisy, r_filt = rmse(noisy, clean), rmse(filt, clean)
        # 这一条才是真正的判据：滤波必须让信号更接近真值。HTTP 200 证明不了这件事。
        check("滤波确实降低了对真值的偏差（RMSE 下降）", r_filt < r_noisy,
              f"原始 RMSE={r_noisy:.5f} → 滤波后 RMSE={r_filt:.5f}"
              f"（降低 {100 * (1 - r_filt / r_noisy):.1f}%）" if r_noisy else "无法计算")
        check("降噪幅度显著（>30%）", r_noisy > 0 and r_filt < 0.7 * r_noisy,
              f"{100 * (1 - r_filt / r_noisy):.1f}%" if r_noisy else "n/a")

    print("\n" + "=" * 70)
    print(f"第 2 阶段核实：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
