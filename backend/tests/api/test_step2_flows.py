"""第 2 步：流程资格校验、锁定版本、显式输入、失败即停、软删除、在对话中运行。"""
from __future__ import annotations

import os
import sqlite3
import uuid

from .conftest import first_dataset


def _code(slug: str, add: float) -> str:
    return (
        f"META = {{'name': '加常数{add}', 'slug': '{slug}', 'category': 'custom', 'description': '给一列加常数',\n"
        f"        'params_schema': {{'column': {{'type': 'string'}}}}}}\n"
        f"def run(df, column=None, **p):\n"
        f"    out = df.copy()\n"
        f"    c = column or out.select_dtypes('number').columns[0]\n"
        f"    out[c] = out[c] + {add}\n"
        f"    return out\n"
    )


def _save_algo(client, user, ds, add=1.0, slug=None):
    slug = slug or f"addc_{uuid.uuid4().hex[:6]}"
    r = client.post("/api/algorithms/save", headers=user["h"], json={
        "code": _code(slug, add), "verify": True, "dataset_id": ds["id"], "params": {}})
    assert r.status_code == 200, r.text
    return r.json()


def _draft_algo(user_id, slug):
    url = os.environ["DATABASE_URL"].split("///", 1)[-1]
    with sqlite3.connect(url) as c:
        c.execute("INSERT INTO algorithms (owner_id, slug, name, category, description, source, language, code, "
                  "params_schema, returns, is_public, is_verified, test_report, version, created_at, updated_at) "
                  "VALUES (?, ?, 'AI 草稿', 'custom', '', 'ai', 'python', ?, '{}', 'dataframe', 0, 0, '{}', 1, "
                  "datetime('now'), datetime('now'))", (user_id, slug, _code(slug, 5)))


def _col(ds):
    return next(c["name"] for c in ds["schema"]["columns"] if "float" in c["dtype"] or "int" in c["dtype"])


def test_flow_with_draft_algorithm_rejected_everywhere(client, alice):
    ds = first_dataset(client, alice)
    slug = f"draft_{uuid.uuid4().hex[:6]}"
    _draft_algo(alice["id"], slug)
    step = {"slug": slug, "params": {}, "label": "草稿"}
    r = client.post("/api/templates", headers=alice["h"], json={"name": "x", "steps": [step]})
    assert r.status_code == 422 and "草稿" in r.json()["detail"]
    ok = client.post("/api/templates", headers=alice["h"], json={"name": "y", "steps": [
        {"slug": "moving_average", "params": {"window": 3}}]}).json()
    r = client.put(f"/api/templates/{ok['id']}", headers=alice["h"], json={"steps": [step]})
    assert r.status_code == 422


def test_pinned_version_and_upgrade(client, alice):
    ds = first_dataset(client, alice)
    col = _col(ds)
    a = _save_algo(client, alice, ds, add=1.0)
    tpl = client.post("/api/templates", headers=alice["h"], json={"name": "pin", "steps": [
        {"slug": a["slug"], "params": {"column": col}, "label": "加常数"}]}).json()
    assert tpl["steps"][0]["version"] == a["version"] and tpl["steps"][0]["algorithm_id"] == a["id"]
    base = client.get(f"/api/datasets/{ds['id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    # algorithm moves on to v2 (+100)
    r = client.put(f"/api/algorithms/{a['id']}", headers=alice["h"], json={
        "code": _code(a["slug"], 100.0), "dataset_id": ds["id"], "params": {}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    lst = {t["id"]: t for t in client.get("/api/templates", headers=alice["h"]).json()}
    assert lst[tpl["id"]]["newer_versions"] and lst[tpl["id"]]["newer_versions"][0]["current"] == a["version"] + 1
    run = client.post(f"/api/templates/{tpl['id']}/run", headers=alice["h"], json={"dataset_id": ds["id"]}).json()
    assert run["status"] == "ok"
    v1_val = client.get(f"/api/datasets/{run['new_dataset']['id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    assert abs(v1_val - (base + 1.0)) < 1e-9          # still the pinned v1
    up = client.put(f"/api/templates/{tpl['id']}", headers=alice["h"], json={"upgrade_versions": True}).json()
    assert up["steps"][0]["version"] == a["version"] + 1 and up["newer_versions"] == []
    run = client.post(f"/api/templates/{tpl['id']}/run", headers=alice["h"], json={"dataset_id": ds["id"]}).json()
    v2_val = client.get(f"/api/datasets/{run['new_dataset']['id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    assert abs(v2_val - (base + 100.0)) < 1e-9


def test_failure_stops_following_steps(client, alice):
    ds = first_dataset(client, alice)
    tpl = client.post("/api/templates", headers=alice["h"], json={"name": "fail", "steps": [
        {"slug": "moving_average", "params": {"window": 3}, "label": "一"},
        {"slug": "moving_average", "params": {"columns": ["没有这一列"], "window": 3}, "label": "二"},
        {"slug": "moving_average", "params": {"window": 3}, "label": "三"},
    ]}).json()
    run = client.post(f"/api/templates/{tpl['id']}/run", headers=alice["h"], json={"dataset_id": ds["id"]}).json()
    assert run["status"] == "partial"
    assert [s["label"] for s in run["steps"]] == ["一", "二"]


def test_explicit_input_start(client, alice):
    ds = first_dataset(client, alice)
    col = _col(ds)
    a = _save_algo(client, alice, ds, add=10.0)
    tpl = client.post("/api/templates", headers=alice["h"], json={"name": "inp", "steps": [
        {"slug": a["slug"], "params": {"column": col}, "label": "先加 10", "input": "start"},
        {"slug": a["slug"], "params": {"column": col}, "label": "从起始数据再加 10", "input": "start"},
        {"slug": a["slug"], "params": {"column": col}, "label": "接第 1 步再加 10", "input": 0},
    ]}).json()
    run = client.post(f"/api/templates/{tpl['id']}/run", headers=alice["h"], json={"dataset_id": ds["id"]}).json()
    assert run["status"] == "ok", run
    base = client.get(f"/api/datasets/{ds['id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    vals = [client.get(f"/api/datasets/{d['id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
            for d in run["derived_chain"]]
    assert [round(v - base, 6) for v in vals] == [10.0, 10.0, 20.0]
    bad = client.post("/api/templates", headers=alice["h"], json={"name": "bad", "steps": [
        {"slug": a["slug"], "params": {}, "input": 3}]})
    assert bad.status_code == 422


def test_soft_delete_keeps_history_and_blocks_flow(client, alice):
    ds = first_dataset(client, alice)
    a = _save_algo(client, alice, ds, add=2.0)
    tpl = client.post("/api/templates", headers=alice["h"], json={"name": "del", "steps": [
        {"slug": a["slug"], "params": {}, "label": "加 2"}]}).json()
    assert client.delete(f"/api/algorithms/{a['id']}", headers=alice["h"]).status_code == 200
    slugs = [x["slug"] for x in client.get("/api/algorithms", headers=alice["h"]).json()]
    assert a["slug"] not in slugs
    r = client.post(f"/api/templates/{tpl['id']}/run", headers=alice["h"], json={"dataset_id": ds["id"]})
    assert r.status_code == 422 and "已删除" in r.json()["detail"]
    url = os.environ["DATABASE_URL"].split("///", 1)[-1]
    with sqlite3.connect(url) as c:
        n = c.execute("SELECT COUNT(*) FROM algorithm_versions WHERE algorithm_id=?", (a["id"],)).fetchone()[0]
        row = c.execute("SELECT deleted_at, original_slug FROM algorithms WHERE id=?", (a["id"],)).fetchone()
    assert n >= 1 and row[0] is not None and row[1] == a["slug"]
    # the slug can be reused by a new algorithm
    again = _save_algo(client, alice, ds, add=3.0, slug=a["slug"])
    assert again["id"] != a["id"]


def test_run_in_chat_writes_message(client, alice, bob):
    ds = first_dataset(client, alice)
    tpl = client.post("/api/templates", headers=alice["h"], json={"name": "chat", "steps": [
        {"slug": "moving_average", "params": {"window": 3}, "label": "平滑"}]}).json()
    assert client.post(f"/api/templates/{tpl['id']}/run-in-chat", headers=bob["h"],
                       json={"dataset_id": ds["id"]}).status_code == 404
    r = client.post(f"/api/templates/{tpl['id']}/run-in-chat", headers=alice["h"], json={"dataset_id": ds["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    msgs = client.get(f"/api/chat/conversations/{out['conversation_id']}/messages", headers=alice["h"]).json()
    last = msgs[-1]
    assert last["id"] == out["message_id"] and last["meta"]["flow_run"] == tpl["id"]
    res = [e for e in last["meta"]["events"] if e["kind"] == "tool_result"]
    assert res and res[0]["payload"]["result"]["provenance"]["input"] == {"kind": "dataset", "dataset_id": ds["id"]}
