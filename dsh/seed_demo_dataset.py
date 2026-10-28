"""给计算面 sidecar 塞一份演示数据集。

造一条带噪正弦信号——滤波类算法在它上面的效果是可判断的，不像随机数那样"跑通了但
看不出对不对"。用于第 2 阶段的端到端验证。

    ./backend/.venv/Scripts/python.exe dsh/seed_demo_dataset.py
"""

from __future__ import annotations

import io
import math
import os
import random
import sys

import httpx

BASE = os.environ.get("SIDECAR", "http://127.0.0.1:8078/api")
NAME = os.environ.get("DEMO_NAME", "演示信号 带噪正弦")
ROWS = int(os.environ.get("DEMO_ROWS", "500"))


def build_csv(rows: int) -> str:
    """t, clean, signal —— clean 保留真值，便于事后判断滤波是否真的降了噪。"""
    rnd = random.Random(20260817)
    out = io.StringIO()
    out.write("t,clean,signal\n")
    for i in range(rows):
        t = i * 0.02
        clean = math.sin(t) + 0.3 * math.sin(3.7 * t)
        noise = rnd.gauss(0.0, 0.12)
        out.write(f"{t:.4f},{clean:.6f},{clean + noise:.6f}\n")
    return out.getvalue()


def main() -> int:
    csv = build_csv(ROWS)
    with httpx.Client(base_url=BASE, timeout=120.0) as c:
        h = c.get("/health")
        if h.status_code != 200 or not h.json().get("ready"):
            print(f"计算面未就绪：HTTP {h.status_code} {h.text[:200]}")
            return 1

        existing = c.get("/datasets").json()
        for d in existing:
            if d["name"] == NAME:
                print(f"已存在：#{d['id']} {d['name']}（{d['rows']} 行 × {d['columns']} 列）")
                return 0

        r = c.post("/datasets",
                   files={"file": ("demo_signal.csv", csv.encode("utf-8"), "text/csv")},
                   data={"name": NAME})
        if r.status_code != 200:
            print(f"上传失败：HTTP {r.status_code} {r.text[:300]}")
            return 1
        payload = r.json()
        print(f"已上传：{payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
