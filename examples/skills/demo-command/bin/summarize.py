"""一个普通的命令行脚本 —— 它不知道自己被技能包调用,只认命令行参数。

用法(系统会这样调它):
    python bin/summarize.py --in <输入csv> --out <输出csv> --params <参数json>
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--params", dest="params", default="")
    args = ap.parse_args()

    params = {}
    if args.params:
        with open(args.params, "r", encoding="utf-8") as fh:
            params = json.load(fh)
    top_n = int(params.get("top_n", 20))

    df = pd.read_csv(args.inp)
    numeric = df.select_dtypes("number")
    if numeric.empty:
        print("输入数据里没有数值列,没法统计。", file=sys.stderr)
        return 2

    stats = numeric.describe().T.reset_index().rename(columns={"index": "column"})
    stats = stats.head(top_n)
    stats.to_csv(args.out, index=False)
    print(f"wrote {len(stats)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
