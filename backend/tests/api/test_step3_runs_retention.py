"""第 3 步：运行记录、存储目录、保留与清理、重跑与复现。"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .conftest import first_dataset
from .test_step2_flows import _code, _col, _save_algo


def _db():
    return sqlite3.connect(os.environ["DATABASE_URL"].split("///", 1)[-1])


def _derive(client, user, ds, slug="moving_average", params=None):
    r = client.post("/api/algorithms/run-to-dataset", headers=user["h"], json={
        "slug": slug, "params": params or {"window": 3}, "dataset_id": ds["id"]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ds(client, user, did):
    return next(d for d in client.get("/api/datasets", headers=user["h"]).json() if d["id"] == did)


def _admin(user):
    with _db() as c:
        c.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user["id"],))


def _set(did, **cols):
    sets = ", ".join(f"{k} = {v}" for k, v in cols.items())
    with _db() as c:
        c.execute(f"UPDATE datasets SET {sets} WHERE id = ?", (did,))


def _sweep(client, user):
    _admin(user)
    r = client.post("/api/datasets/retention/sweep", headers=user["h"])
    assert r.status_code == 200, r.text
    return r.json()


# ── runs ─────────────────────────────────────────────────────────────────────

def test_library_builtin_run_is_recorded_with_code(client, alice):
    ds = first_dataset(client, alice)
    r = client.post("/api/algorithms/run", headers=alice["h"], json={
        "slug": "moving_average", "params": {"window": 3}, "dataset_id": ds["id"]}).json()
    assert r["run_id"] and r["run_code"].startswith("R-")
    with _db() as c:
        row = c.execute("SELECT r.algorithm_slug, r.status, g.entry FROM runs r JOIN run_groups g ON g.id = r.group_id "
                        "WHERE r.id = ?", (r["run_id"],)).fetchone()
    assert row == ("moving_average", "ok", "library")


def test_failed_run_is_recorded(client, alice):
    ds = first_dataset(client, alice)
    r = client.post("/api/algorithms/run", headers=alice["h"], json={
        "slug": "moving_average", "params": {"columns": ["没有这列"], "window": 3}, "dataset_id": ds["id"]}).json()
    assert r["status"] == "error" and r["run_id"]
    with _db() as c:
        assert c.execute("SELECT status FROM runs WHERE id = ?", (r["run_id"],)).fetchone()[0] == "error"


def test_flow_run_records_one_group_with_ordered_runs(client, alice):
    ds = first_dataset(client, alice)
    tpl = client.post("/api/templates", headers=alice["h"], json={"name": "g", "steps": [
        {"slug": "moving_average", "params": {"window": 3}, "label": "一", "input": "start"},
        {"slug": "moving_average", "params": {"window": 5}, "label": "二", "input": 0}]}).json()
    out = client.post(f"/api/templates/{tpl['id']}/run", headers=alice["h"], json={"dataset_id": ds["id"]}).json()
    codes = [s["run_code"] for s in out["steps"]]
    assert codes[0].endswith(".1") and codes[1].endswith(".2") and codes[0].split(".")[0] == codes[1].split(".")[0]
    d2 = _ds(client, alice, out["derived_chain"][1]["id"])
    assert d2["origin"]["entry"] == "flow" and d2["origin"]["template"]["id"] == tpl["id"]
    assert d2["name"].startswith(ds["name"] + " · ")        # original name, not chained


def test_batch_numbers_unique_under_concurrency(client, alice):
    ds = first_dataset(client, alice)

    def go(_):
        return client.post("/api/algorithms/run", headers=alice["h"], json={
            "slug": "moving_average", "params": {"window": 3}, "dataset_id": ds["id"]}).json()["run_code"]
    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(go, range(12)))
    assert len(set(codes)) == 12


def test_deleting_algorithm_keeps_its_runs(client, alice):
    ds = first_dataset(client, alice)
    a = _save_algo(client, alice, ds, add=1.0)
    r = client.post("/api/algorithms/run", headers=alice["h"], json={"slug": a["slug"], "params": {}, "dataset_id": ds["id"]}).json()
    client.delete(f"/api/algorithms/{a['id']}", headers=alice["h"])
    with _db() as c:
        assert c.execute("SELECT algorithm_slug FROM runs WHERE id = ?", (r["run_id"],)).fetchone()[0] == a["slug"]


# ── storage ──────────────────────────────────────────────────────────────────

def test_new_files_use_relative_paths_and_layout(client, alice, upload_root):
    ds = first_dataset(client, alice)
    did = _derive(client, alice, ds)
    with _db() as c:
        src = c.execute("SELECT storage_path FROM datasets WHERE id = ?", (ds["id"],)).fetchone()[0]
        der = c.execute("SELECT storage_path FROM datasets WHERE id = ?", (did,)).fetchone()[0]
    assert not Path(src).is_absolute() and src.startswith(f"user_{alice['id']}/sources/")
    assert not Path(der).is_absolute() and der.startswith(f"user_{alice['id']}/runs/")
    assert (upload_root / der).exists()
    # read / preview / export / delete all go through the resolver
    assert client.get(f"/api/datasets/{did}/preview?limit=2", headers=alice["h"]).status_code == 200
    assert client.get(f"/api/datasets/{did}/export", headers=alice["h"]).status_code == 200
    assert client.delete(f"/api/datasets/{did}", headers=alice["h"]).status_code == 200
    assert not (upload_root / der).exists()


# ── retention rules ──────────────────────────────────────────────────────────

def test_not_expired_is_kept(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    _sweep(client, alice)
    assert _ds(client, alice, did)["state"] == "active"


def test_expired_but_not_acknowledged_is_kept(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    _set(did, expires_at="datetime('now','-1 day')")
    _sweep(client, alice)
    assert _ds(client, alice, did)["state"] == "active"
    items = client.get("/api/datasets/retention", headers=alice["h"]).json()["items"]
    assert did in [i["id"] for i in items]


def test_expired_and_acked_24h_ago_is_cleaned_row_kept(client, alice, upload_root):
    did = _derive(client, alice, first_dataset(client, alice))
    _set(did, expires_at="datetime('now','-1 day')", notice_acked_at="datetime('now','-25 hours')")
    with _db() as c:
        rel = c.execute("SELECT storage_path FROM datasets WHERE id = ?", (did,)).fetchone()[0]
        rid = c.execute("SELECT run_id FROM datasets WHERE id = ?", (did,)).fetchone()[0]
    _sweep(client, alice)
    d = _ds(client, alice, did)
    assert d["state"] == "cleaned" and not (upload_root / rel).exists()
    assert client.get(f"/api/datasets/{did}/preview", headers=alice["h"]).status_code == 410
    with _db() as c:
        assert c.execute("SELECT data_cleaned FROM runs WHERE id = ?", (rid,)).fetchone()[0] == 1


def test_acked_less_than_24h_ago_is_kept(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    _set(did, expires_at="datetime('now','-1 day')", notice_acked_at="datetime('now','-1 hour')")
    _sweep(client, alice)
    assert _ds(client, alice, did)["state"] == "active"


def test_ack_through_api_then_due(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    _set(did, expires_at="datetime('now','-1 day')")
    assert client.post("/api/datasets/retention", headers=alice["h"], json={"ids": [did], "action": "ack"}).json()["count"] == 1
    with _db() as c:
        assert c.execute("SELECT notice_acked_at IS NOT NULL FROM datasets WHERE id = ?", (did,)).fetchone()[0] == 1


def test_kept_and_its_ancestry_are_protected(client, alice):
    ds = first_dataset(client, alice)
    parent = _derive(client, alice, ds)
    child = _derive(client, alice, _ds(client, alice, parent))
    client.post(f"/api/datasets/{child}/keep", headers=alice["h"], json={"kept": True})
    for d in (parent, child):
        _set(d, expires_at="datetime('now','-30 days')", notice_acked_at="datetime('now','-30 days')",
             created_at="datetime('now','-90 days')")
    _sweep(client, alice)
    assert _ds(client, alice, parent)["state"] == "active" and _ds(client, alice, child)["state"] == "active"


def test_backstop_after_60_days_even_without_ack(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    _set(did, created_at="datetime('now','-61 days')", expires_at="datetime('now','-41 days')")
    _sweep(client, alice)
    assert _ds(client, alice, did)["state"] == "cleaned"


def test_extended_resets_clock_and_disables_backstop(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    _set(did, created_at="datetime('now','-61 days')", expires_at="datetime('now','-41 days')")
    client.post("/api/datasets/retention", headers=alice["h"], json={"ids": [did], "action": "extend"})
    _sweep(client, alice)
    d = _ds(client, alice, did)
    assert d["state"] == "active" and d["expires_at"] is not None


def test_manual_clean_button_cleans_unprotected_now(client, alice):
    did = _derive(client, alice, first_dataset(client, alice))
    r = client.post("/api/datasets/gc", headers=alice["h"]).json()
    assert did in [c["id"] for c in r["cleaned"]]
    assert _ds(client, alice, did)["state"] == "cleaned"


def test_policy_admin_only(client, alice, bob):
    assert client.put("/api/datasets/retention/policy", headers=bob["h"], json={"retention_days": 5}).status_code == 403
    _admin(alice)
    p = client.put("/api/datasets/retention/policy", headers=alice["h"], json={"retention_days": 25}).json()
    assert p["retention_days"] == 25
    client.put("/api/datasets/retention/policy", headers=alice["h"], json={"retention_days": 20})


# ── rerun / reproduce ────────────────────────────────────────────────────────

def test_reproduce_uses_old_version_rerun_uses_current(client, alice):
    ds = first_dataset(client, alice)
    col = _col(ds)
    a = _save_algo(client, alice, ds, add=1.0)
    did = client.post("/api/algorithms/run-to-dataset", headers=alice["h"], json={
        "slug": a["slug"], "params": {"column": col}, "dataset_id": ds["id"]}).json()["id"]
    client.put(f"/api/algorithms/{a['id']}", headers=alice["h"], json={"code": _code(a["slug"], 100.0), "dataset_id": ds["id"], "params": {}})
    base = client.get(f"/api/datasets/{ds['id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    prov = client.get(f"/api/datasets/{did}/provenance", headers=alice["h"]).json()
    assert prov["run"]["version"] == a["version"] and prov["actions"]["reproduce"] and prov["actions"]["rerun"]
    rp = client.post(f"/api/datasets/{did}/reproduce", headers=alice["h"]).json()
    rr = client.post(f"/api/datasets/{did}/rerun", headers=alice["h"]).json()
    v_rp = client.get(f"/api/datasets/{rp['dataset_id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    v_rr = client.get(f"/api/datasets/{rr['dataset_id']}/preview?limit=1", headers=alice["h"]).json()["rows"][0][col]
    assert abs(v_rp - (base + 1.0)) < 1e-9 and abs(v_rr - (base + 100.0)) < 1e-9


def test_reproduce_blocked_when_input_cleaned(client, alice):
    ds = first_dataset(client, alice)
    parent = _derive(client, alice, ds)
    child = _derive(client, alice, _ds(client, alice, parent))
    _set(parent, expires_at="datetime('now','-1 day')", notice_acked_at="datetime('now','-2 days')")
    _sweep(client, alice)
    prov = client.get(f"/api/datasets/{child}/provenance", headers=alice["h"]).json()
    assert prov["actions"]["reproduce"] is False and "清理" in prov["actions"]["reproduce_reason"]
    assert client.post(f"/api/datasets/{child}/reproduce", headers=alice["h"]).status_code == 409


# ── migration ────────────────────────────────────────────────────────────────

def test_startup_migration_is_repeatable(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as c:   # a legacy runs table, as shipped before 第 3 步
        c.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, owner_id INTEGER, algorithm_id INTEGER NOT NULL, params JSON)")
    code = (
        "import asyncio, sys; sys.path.insert(0, r'%s');"
        "from app.db.base import init_db;"
        "asyncio.run(init_db()); asyncio.run(init_db()); print('ok')"
    ) % str(Path(__file__).resolve().parents[2])
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db.as_posix()}", UPLOAD_DIR=str(tmp_path / "up"))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(runs)")}
        dcols = {r[1] for r in c.execute("PRAGMA table_info(datasets)")}
    assert {"group_id", "algorithm_slug", "data_cleaned"} <= cols
    assert {"run_id", "expires_at", "notice_acked_at", "state"} <= dcols


# ── F2: chat images are owner-scoped ────────────────────────────────────────

_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                     "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_chat_image_ref_is_relative_and_owner_only(client, alice, bob):
    r = client.post("/api/chat/upload-image", headers=alice["h"], files={"file": ("a.png", _PNG, "image/png")})
    assert r.status_code == 200, r.text
    ref = r.json()["ref"]
    assert not Path(ref).is_absolute() and ref.startswith(f"user_{alice['id']}/tmp/")
    conv = client.post("/api/chat/conversations", headers=bob["h"], json={"title": "x"}).json()
    r = client.post(f"/api/chat/conversations/{conv['id']}/send", headers=bob["h"],
                    json={"message": "看图", "image_ref": ref})
    assert r.status_code == 400
