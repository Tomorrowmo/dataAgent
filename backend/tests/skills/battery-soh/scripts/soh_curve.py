import numpy as np
import pandas as pd

META = {
    "name": "SOH 曲线",
    "slug": "soh_curve",
    "category": "battery",
    "description": "按初始容量（前 n 个有效循环的中位数）计算每个循环的 SOH(%)，并标出首次低于阈值的循环。",
    "params_schema": {
        "capacity_col": {"type": "string", "required": True, "description": "容量列"},
        "n_initial": {"type": "integer", "default": 5, "description": "用前 n 个循环估计初始容量"},
        "eol_pct": {"type": "number", "default": 80, "description": "寿命终点阈值(%)"},
        "exclude_col": {"type": "string", "required": False, "description": "可选：布尔列，True 的行不参与计算（如异常标记）"},
    },
    "returns": "dataframe",
}


def run(df, capacity_col, n_initial=5, eol_pct=80, exclude_col=None):
    if df is None:
        raise ValueError("需要数据集")
    if capacity_col not in df.columns:
        raise ValueError(f"列 {capacity_col} 不存在，现有列：{list(df.columns)}")
    out = df.copy()
    valid = out[capacity_col].notna()
    if exclude_col and exclude_col in out.columns:
        valid &= ~out[exclude_col].astype(bool)
    c0 = float(out.loc[valid, capacity_col].iloc[: int(n_initial)].median())
    out["soh_pct"] = np.where(valid, out[capacity_col] / c0 * 100.0, np.nan)
    below = out.index[(out["soh_pct"] < float(eol_pct)).fillna(False)]
    out["is_eol"] = False
    if len(below):
        out.loc[below[0], "is_eol"] = True
    out["c0_mAh"] = c0
    return out


test_cases = [
    {"df": pd.DataFrame({"cycle": range(1, 11), "cap": [3000, 2990, 2985, 2980, 2970, 2600, 2500, 2400, 2300, 2200]}),
     "params": {"capacity_col": "cap"}},
]
