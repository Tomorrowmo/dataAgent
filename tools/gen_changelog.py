# -*- coding: utf-8 -*-
"""Scaffold a new changelog entry from the git log.

The changelog (`backend/app/changelog.json`) is the single source of truth the
in-app「关于」面板 reads. This tool DRAFTS the next version's entry by reading the
commits since the previous version and bucketing them into 新增 / 优化 / 修复 / 其它
by their conventional-commit type — you then curate the wording before release.

Usage:
    python tools/gen_changelog.py --version 1.1.0
    python tools/gen_changelog.py --version 1.1.0 --since v1.0.0 --date 2026-07-01
    python tools/gen_changelog.py --version 1.1.0 --force      # overwrite an existing draft

Range selection (first that works):
    1. --since <ref>                      explicit
    2. git tag v<previous-changelog-ver>  if such a tag exists
    3. last 40 commits                     fallback (prints a warning)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys

# Windows consoles default to GBK and choke on ✓/⚠ — force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(ROOT, "backend", "app", "changelog.json")

# conventional-commit type -> changelog bucket. Unmapped types fall to 其它.
_BUCKET = {
    "feat": "新增", "feature": "新增",
    "fix": "修复", "bugfix": "修复", "hotfix": "修复",
    "perf": "优化", "refactor": "优化", "style": "优化", "ui": "优化",
}
_SKIP = {"chore", "build", "ci", "test", "docs", "release"}
_CC = re.compile(r"^(?P<type>\w+)(?:\([^)]*\))?(?P<bang>!)?:\s*(?P<desc>.+)$")


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return (out.stdout or "").strip()


def _tag_exists(tag: str) -> bool:
    return bool(_git("tag", "-l", tag))


def _commit_subjects(rng: str | None) -> list[str]:
    args = ["log", "--no-merges", "--pretty=%s"]
    if rng:
        args.append(rng)
    else:
        args += ["-n", "40"]
    log = _git(*args)
    return [line for line in log.splitlines() if line.strip()]


def _bucket_commits(subjects: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"新增": [], "优化": [], "修复": [], "其它": []}
    for s in subjects:
        m = _CC.match(s)
        if m:
            ctype = m.group("type").lower()
            if ctype in _SKIP:
                continue
            desc = m.group("desc").strip()
            bucket = _BUCKET.get(ctype, "其它")
        else:
            desc = s.strip()
            bucket = "其它"
        # de-dup within a bucket, preserve order
        if desc and desc not in buckets[bucket]:
            buckets[bucket].append(desc)
    # drop empty buckets
    return {k: v for k, v in buckets.items() if v}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="new version, e.g. 1.1.0")
    ap.add_argument("--since", help="git ref (tag/commit) to diff from")
    ap.add_argument("--date", help="release date YYYY-MM-DD (default: today)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing entry for --version")
    args = ap.parse_args()

    try:
        with open(CHANGELOG, "r", encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        log = []

    if any(e.get("version") == args.version for e in log) and not args.force:
        print(f"× 版本 {args.version} 已存在于 changelog.json（用 --force 覆盖草稿）。")
        return 1

    prev_ver = log[0]["version"] if log else None
    rng = args.since
    if not rng and prev_ver:
        tag = f"v{prev_ver}"
        if _tag_exists(tag):
            rng = f"{tag}..HEAD"
    if not rng:
        print("⚠ 未指定 --since 且找不到上一版本的 git tag；回退为最近 40 条提交。"
              "请在生成后人工核对范围。", file=sys.stderr)

    subjects = _commit_subjects(rng)
    buckets = _bucket_commits(subjects)
    date = args.date or _dt.date.today().isoformat()

    entry = {
        "version": args.version,
        "date": date,
        "title": "〈待填：版本标题〉",
        "summary": "〈待填：一句话概述本版主题〉",
        "changes": buckets or {"新增": ["〈无可归类提交，请手工补充〉"]},
    }

    log = [e for e in log if e.get("version") != args.version]
    log.insert(0, entry)
    with open(CHANGELOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
        f.write("\n")

    n = sum(len(v) for v in buckets.values())
    print(f"✓ 已写入 {args.version} 草稿（{n} 条，范围：{rng or '最近40条'}）→ {os.path.relpath(CHANGELOG, ROOT)}")
    for b, items in buckets.items():
        print(f"  {b}: {len(items)} 条")
    print("→ 请编辑 changelog.json：填 title/summary、润色措辞、删无关条目，再发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
