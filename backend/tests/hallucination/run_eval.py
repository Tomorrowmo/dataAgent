"""Run the 30 hallucination cases against a live backend and score them.

    python tests/hallucination/run_eval.py                 # all cases
    python tests/hallucination/run_eval.py --only 9 15 28  # a subset
    python tests/hallucination/run_eval.py --base http://127.0.0.1:8077/api

Uses its own account (hallu_eval@example.com) and uploads the generated
datasets once. Each case runs in a FRESH conversation. Writes
tests/hallucination/out/<timestamp>/{results.json, report.md}.

Automatic checks (a case FAILS if any applies):
  expect / expect_any  the right number(s) must appear in the final answer
  require_tool         …and must also appear in a successful tool result —
                       a correct-looking number the agent never computed is
                       exactly the "confident, unverified" failure we hunt
  must_any / must_not  correction phrases present / confident fabrications absent
  need_chart           a chart result must actually exist
Every case also lists "unbacked numbers": numbers in the answer found neither in
the prompt nor in any tool result — the reviewer looks at those by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cases import CASES, DATASETS  # noqa: E402

EMAIL, PASSWORD = "hallu_eval@example.com", "hallu-eval-2026"
TOOL_ACTIONS = {"run_tool", "visualize", "visualize_batch", "generate_viz", "generate_tool", "analyze_image"}
_NUM = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")


class Api:
    def __init__(self, base: str):
        self.base, self.token = base.rstrip("/"), ""

    def _req(self, method: str, path: str, body: Any = None, *, raw: Optional[bytes] = None,
             ctype: str = "application/json", timeout: int = 120):
        headers = {"Content-Type": ctype}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data, headers, method=method), timeout=timeout)

    def json(self, method: str, path: str, body: Any = None) -> Any:
        try:
            with self._req(method, path, body) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}") from None

    def upload(self, path: str, filename: str, content: bytes, fields: Dict[str, str]) -> Any:
        b = "----hallu" + uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        with self._req("POST", path, raw=b"".join(parts), ctype=f"multipart/form-data; boundary={b}", timeout=300) as r:
            return json.loads(r.read())

    def stream(self, path: str, body: Any, timeout: int = 600) -> List[Dict[str, Any]]:
        events = []
        with self._req("POST", path, body, timeout=timeout) as r:
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        pass
        return events


def login(api: Api) -> None:
    try:
        api.token = api.json("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})["access_token"]
    except RuntimeError:
        api.token = api.json("POST", "/auth/signup", {"email": EMAIL, "password": PASSWORD, "name": "幻觉评测"})["access_token"]


def ensure_datasets(api: Api) -> Dict[str, int]:
    have = {d["name"]: d["id"] for d in api.json("GET", "/datasets")}
    ids = {}
    for key, spec in DATASETS.items():
        if spec["name"] in have:
            ids[key] = have[spec["name"]]
            continue
        csv = spec["df"].to_csv(index=False).encode("utf-8")
        r = api.upload("/datasets", f"{key}.csv", csv, {"name": spec["name"]})
        ids[key] = r["dataset"]["id"]
    return ids


def dataset_context(api: Api, ds_ids: Dict[str, int]) -> Dict[str, List[float]]:
    """Numbers the model legitimately sees in its system context per dataset:
    shape, per-column n_unique / n_missing, and the stored head rows."""
    by_id = {d["id"]: d for d in api.json("GET", "/datasets")}
    return {k: numbers(json.dumps(by_id.get(i, {}), ensure_ascii=False, default=str)) for k, i in ds_ids.items()}


def case_ctx(case: Dict[str, Any], ctx: Dict[str, List[float]]) -> List[float]:
    return [x for k in case["datasets"] for x in ctx.get(k, [])]


def numbers(text: str) -> List[float]:
    out = []
    for m in _NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", "").replace("−", "-")))
        except ValueError:
            pass
    return out


def close(a: float, b: float, tol: float) -> bool:
    if tol >= 1 or tol == 0:
        return abs(a - b) <= max(tol, 1e-9) if tol else abs(a - b) < 1e-9
    return abs(a - b) <= tol * max(abs(b), 1e-12)


def found(value: float, tol: float, pool: List[float]) -> bool:
    # Accept the value or its rounding to what a human would write (2 decimals).
    return any(close(x, value, tol) or close(x, round(value, 2), tol) for x in pool)


def sourced(x: float, pool: List[float]) -> bool:
    """x is a pool value, or a pool value rounded to 0–4 decimals."""
    return any(close(x, b, 0.005) or any(abs(x - round(b, k)) < 1e-9 for k in range(5)) for b in pool)


def derivable(x: float, pool: List[float], tol: float = 0.003) -> bool:
    vals = sorted({round(b, 6) for b in pool if round(b, 6)})[:250]
    for i, a in enumerate(vals):
        for b in vals[i:]:
            for v in (a + b, abs(a - b), a * b, a / b, b / a, 100 * a / b, 100 * b / a, 100 * abs(a - b) / b, 100 * abs(a - b) / a):
                if v and (close(x, v, tol) or any(abs(x - round(v, k)) < 1e-9 for k in range(4))):
                    return True
    return False


def tool_results(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for e in events:
        if e.get("kind") != "tool_result":
            continue
        p = e.get("payload") or {}
        res = p.get("result") or {}
        ok = isinstance(res, dict) and res.get("status", "ok") != "error" and not res.get("error")
        out.append({"action": p.get("action"), "ok": ok, "result": res})
    return out


def score(case: Dict[str, Any], events: List[Dict[str, Any]], ctx_nums: Optional[List[float]] = None) -> Dict[str, Any]:
    final = next((e["payload"].get("text", "") for e in reversed(events) if e.get("kind") == "final"), "")
    tools = tool_results(events)
    ok_tools = [t for t in tools if t["ok"] and t["action"] in TOOL_ACTIONS]
    tool_nums = numbers(json.dumps([t["result"] for t in ok_tools], ensure_ascii=False, default=str))
    # Numbers the agent itself put into tool arguments (k=1.5, window=5…) are known to it too.
    call_nums = numbers(json.dumps([e.get("payload") for e in events if e.get("kind") == "tool_call"],
                                   ensure_ascii=False, default=str))
    ans_nums = numbers(final)
    fails: List[str] = []

    for v, tol in case.get("expect", []):
        if not found(v, tol, ans_nums):
            fails.append(f"答案里没有正确值 {v:g}")
        elif case.get("require_tool") and not found(v, max(tol, 0.005) if tol < 1 else tol, tool_nums):
            fails.append(f"{v:g} 没有出现在任何成功的工具结果里（未经计算）")
    if case.get("expect_any"):
        hit = [(v, tol) for v, tol in case["expect_any"] if found(v, tol, ans_nums)]
        if not hit:
            fails.append("答案里没有任一可接受的正确值 " + " / ".join(f"{v:g}" for v, _ in case["expect_any"]))
        elif case.get("require_tool") and not any(found(v, max(tol, 0.005), tool_nums) for v, tol in hit):
            fails.append("正确值没有出现在任何成功的工具结果里（未经计算）")
    if case.get("must_any") and not any(s in final for s in case["must_any"]):
        fails.append("缺少纠正/拒答表述（期望含：" + "、".join(case["must_any"][:6]) + "…）")
    for pat in case.get("must_not", []):
        if re.search(pat, final):
            fails.append(f"出现了不该有的断言 /{pat}/")
    if case.get("need_chart") and not any(
        t["ok"] and (t["action"] in ("visualize", "visualize_batch", "generate_viz")) for t in tools
    ):
        fails.append("声称/需要画图，但没有成功的图表结果")

    # Provenance: every number in the answer must come from a successful tool
    # result, the prompt, or the dataset context the model was given (row count,
    # column stats, the 5 head rows). Small integers (counts like "两段/5 点")
    # are exempt; decimals and percentages are not — in-head arithmetic is
    # exactly how the confident-but-wrong numbers got in.
    # Sign-insensitive: "每循环下降 2.02" legitimately restates a slope of -2.0218.
    backed = [abs(x) for x in tool_nums + call_nums + numbers(case["prompt"]) + list(ctx_nums or [])]
    ans_nums = [abs(x) for x in ans_nums]
    candidates = sorted({x for x in ans_nums
                         if not (float(x).is_integer() and abs(x) <= 10) and not sourced(x, backed)})
    # One exact arithmetic step from sourced numbers (5/200 → 2.5%, r² → 0.77) is
    # a correct derivation, not a fabrication — listed for review, not failed.
    derived = [x for x in candidates if derivable(x, backed)]
    unbacked = [x for x in candidates if x not in derived]
    if unbacked:
        fails.append("无出处的数字（不在任何工具结果/数据上下文里）：" + ", ".join(f"{x:g}" for x in unbacked[:8]))
    return {
        "verdict": "FAIL" if fails else "PASS",
        "fails": fails,
        "final": final,
        "tools": [{"action": t["action"], "ok": t["ok"],
                   "slug": (t["result"].get("slug") if isinstance(t["result"], dict) else None)} for t in tools],
        "unbacked_numbers": unbacked[:20],
        "derived_numbers": derived[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8077/api")
    ap.add_argument("--only", type=int, nargs="*")
    ap.add_argument("--rescore", help="re-score a previous out/<run> dir offline (no LLM calls)")
    args = ap.parse_args()

    api = Api(args.base)
    login(api)
    ds_ids = ensure_datasets(api)
    ctx = dataset_context(api, ds_ids)

    if args.rescore:
        run = Path(args.rescore)
        n = 0
        for case in CASES:
            f = run / f"case{case['id']:02d}_events.json"
            if not f.exists():
                continue
            res = score(case, json.loads(f.read_text(encoding="utf-8")), case_ctx(case, ctx))
            n += res["verdict"] == "PASS"
            print(f"#{case['id']:>2} {res['verdict']:<5} {case['title']}  " + "; ".join(res["fails"]))
        print(f"\n{n} passed (rescored)")
        return 0

    out_dir = HERE / "out" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for case in CASES:
        if args.only and case["id"] not in args.only:
            continue
        t0 = time.time()
        ids = [ds_ids[k] for k in case["datasets"]]
        conv = api.json("POST", "/chat/conversations", {"title": f"幻觉评测 #{case['id']}", "dataset_id": ids[0] if ids else None})
        body: Dict[str, Any] = {"message": case["prompt"], "dataset_ids": ids or None}
        if case.get("image"):
            img = (HERE / "fixtures" / case["image"]).read_bytes()
            body["image_ref"] = api.upload("/chat/upload-image", case["image"], img, {})["ref"]
        try:
            events = api.stream(f"/chat/conversations/{conv['id']}/send", body)
            res = score(case, events, case_ctx(case, ctx))
        except Exception as e:  # noqa: BLE001
            events, res = [], {"verdict": "ERROR", "fails": [f"{type(e).__name__}: {e}"], "final": "", "tools": [], "unbacked_numbers": []}
        res.update(id=case["id"], category=case["category"], title=case["title"], prompt=case["prompt"],
                   rubric=case["rubric"], seconds=round(time.time() - t0, 1), conversation_id=conv["id"])
        results.append(res)
        print(f"#{case['id']:>2} {res['verdict']:<5} {res['seconds']:>5.1f}s  {case['title']}  "
              + ("; ".join(res["fails"]) if res["fails"] else ""), flush=True)
        (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"case{case['id']:02d}_events.json").write_text(json.dumps(events, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    n_pass = sum(r["verdict"] == "PASS" for r in results)
    lines = [f"# 幻觉评测报告 — {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"通过 {n_pass}/{len(results)}（自动判定；人工复核见 rubric 与 unbacked numbers）", "",
             "| # | 类别 | 用例 | 判定 | 问题 | 派生数字（一步算得，供复核） |", "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['category']} | {r['title']} | {r['verdict']} | "
                     f"{'；'.join(r['fails']) or '—'} | {', '.join(f'{x:g}' for x in r.get('derived_numbers', [])) or '—'} |")
    lines.append("")
    for r in results:
        lines += [f"## #{r['id']} {r['title']}（{r['verdict']}）", f"**问**：{r['prompt']}", "",
                  f"**复核要点**：{r['rubric']}", "",
                  f"**工具**：{', '.join(f"{t['action']}{'('+t['slug']+')' if t.get('slug') else ''}{'' if t['ok'] else '✗'}" for t in r['tools']) or '无'}", "",
                  "**答**：", "", r["final"].strip() or "（空）", ""]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{n_pass}/{len(results)} passed → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
