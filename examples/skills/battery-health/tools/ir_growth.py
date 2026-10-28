"""内阻增长率。没有内阻列时报错说清楚,绝不拿别的列凑数。"""

from __future__ import annotations

import pandas as pd

from lib import criteria


def run(df: pd.DataFrame,
        cycle_col: str = "cycle",
        ir_col: str = "internal_resistance_mohm") -> pd.DataFrame:
    criteria.require_columns(df, {"循环号": cycle_col, "内阻": ir_col})
    clean = criteria.clean_series(df, cycle_col, ir_col)

    base = float(clean[ir_col].iloc[0])
    if base <= 0:
        raise criteria.DataInsufficient("首圈内阻 ≤ 0,数据不可用。")
    growth = (clean[ir_col] / base - 1.0) * 100.0

    return pd.DataFrame({
        "cycle": clean[cycle_col].to_numpy(),
        "ir_mohm": clean[ir_col].round(4).to_numpy(),
        "ir_growth_pct": growth.round(3).to_numpy(),
    })
