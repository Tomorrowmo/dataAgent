"""第 0 步 · S5：旧结果重新运行。"""
from __future__ import annotations

import json
import os
import sqlite3

from .conftest import first_dataset


def _db():
    url = os.environ["DATABASE_URL"]
    return sqlite3.connect(url.split("///", 1)[-1])


def _seed_turn(client, user, ds, slug="moving_average", dataset_ref=None):
    conv = client.post("/api/chat/conversations", headers=user["h"],
                       json={"title": "t", "dataset_id": ds["id"]}).json()
    col = ds["schema"]["columns"][0]["name"]
    args = {"slug": slug, "params": {"columns": [col], "window": 3}}
    if dataset_ref is not None:
        args["dataset"] = dataset_ref
    events = [
        {"kind": "tool_call", "payload": {"action": "run_tool", "args": args}},
        {"kind": "tool_result", "payload": {"action": "run_tool", "result": {
            "status": "ok", "summary": {"type": "dataframe", "rows": 3},
            "derived_dataset": {"id": 999999, "name": "已不存在的中间结果"}}}},
        {"kind": "final", "payload": {"text": "done"}},
    ]
    with _db() as c:
        cur = c.execute("INSERT INTO messages (conversation_id, role, content, meta, created_at) "
                        "VALUES (?, 'assistant', 'old', ?, datetime('now'))",
                        (conv["id"], json.dumps({"events": events})))
        mid = cur.lastrowid
    return conv["id"], mid


def test_rerun_replays_on_original_data(client, alice):
    ds = first_dataset(client, alice)
    cid, mid = _seed_turn(client, alice, ds)
    chk = client.get(f"/api/chat/conversations/{cid}/messages/{mid}/rerun", headers=alice["h"]).json()
    assert chk == {"ok": True, "reason": None, "steps": 1}
    r = client.post(f"/api/chat/conversations/{cid}/messages/{mid}/rerun", headers=alice["h"])
    assert r.status_code == 200, r.text
    msg = r.json()
    assert msg["meta"]["rerun_of"] == mid
    results = [e for e in msg["meta"]["events"] if e["kind"] == "tool_result"]
    assert results and results[0]["payload"]["result"]["status"] == "ok"
    new_id = results[0]["payload"]["result"]["derived_dataset"]["id"]
    ids = [d["id"] for d in client.get("/api/datasets", headers=alice["h"]).json()]
    assert new_id in ids
    # persisted: shows up in the conversation history
    hist = client.get(f"/api/chat/conversations/{cid}/messages", headers=alice["h"]).json()
    assert hist[-1]["id"] == msg["id"]


def test_rerun_is_owner_only(client, alice, bob):
    ds = first_dataset(client, alice)
    cid, mid = _seed_turn(client, alice, ds)
    assert client.post(f"/api/chat/conversations/{cid}/messages/{mid}/rerun").status_code == 401
    assert client.post(f"/api/chat/conversations/{cid}/messages/{mid}/rerun", headers=bob["h"]).status_code == 404


def test_rerun_blocked_when_source_deleted(client, alice):
    ds = first_dataset(client, alice)
    cid, mid = _seed_turn(client, alice, ds, dataset_ref="一个不存在的数据集")
    chk = client.get(f"/api/chat/conversations/{cid}/messages/{mid}/rerun", headers=alice["h"]).json()
    assert chk["ok"] is False and "已删除" in chk["reason"]
    assert client.post(f"/api/chat/conversations/{cid}/messages/{mid}/rerun", headers=alice["h"]).status_code == 409


def test_rerun_blocked_when_algorithm_missing(client, alice):
    ds = first_dataset(client, alice)
    cid, mid = _seed_turn(client, alice, ds, slug="no_such_algorithm_xyz")
    chk = client.get(f"/api/chat/conversations/{cid}/messages/{mid}/rerun", headers=alice["h"]).json()
    assert chk["ok"] is False and "no_such_algorithm_xyz" in chk["reason"]


def test_rerun_blocked_when_no_algorithm_steps(client, alice):
    ds = first_dataset(client, alice)
    conv = client.post("/api/chat/conversations", headers=alice["h"], json={"dataset_id": ds["id"]}).json()
    with _db() as c:
        mid = c.execute("INSERT INTO messages (conversation_id, role, content, meta, created_at) "
                        "VALUES (?, 'assistant', 'chart only', ?, datetime('now'))",
                        (conv["id"], json.dumps({"events": [{"kind": "final", "payload": {"text": "x"}}]}))).lastrowid
    chk = client.get(f"/api/chat/conversations/{conv['id']}/messages/{mid}/rerun", headers=alice["h"]).json()
    assert chk["ok"] is False and "没有可以重新运行" in chk["reason"]
