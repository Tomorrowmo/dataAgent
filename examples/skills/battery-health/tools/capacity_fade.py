"""逐循环容量保持率 + 衰减速率。

技能包工具的约定:
  - 顶层函数,签名 `run(df, **params)`(needs_data: false 的工具则是 `run(**params)`);
  - 返回 DataFrame / dict / Series 都行,在 skill.yaml 里用 returns 声明;
  - 出错就抛异常,异常信息会原样带回给用户和 AI —— 所以异常信息要写成人话。
"""

from __future__ import annotations

import pandas as pd

from lib import criteria


def run(df: pd.DataFrame,
        cycle_col: str = "cycle",
        capacity_col: str = "discharge_capacity_ah",
        baseline_cycles: int = 5) -> pd.DataFrame:
    criteria.require_columns(df, {"循环号": cycle_col, "放电容量": capacity_col})
    clean = criteria.clean_series(df, cycle_col, capacity_col)

    base = criteria.baseline_capacity(clean[capacity_col], baseline_cycles)
    retention = clean[capacity_col] / base * 100.0
    fade = criteria.fade_rate_pct_per_100(clean[cycle_col], retention)

    out = pd.DataFrame({
        "cycle": clean[cycle_col].to_numpy(),
        "capacity": clean[capacity_col].to_numpy(),
        "retention_pct": retention.round(3).to_numpy(),
    })
    # 拟合速率对整条曲线是同一个值,写成列是为了下游画图/汇总时不用再算一遍。
    out["fade_pct_per_100cyc"] = round(float(fade), 4)
    out["baseline_capacity"] = round(float(base), 6)
    return out
