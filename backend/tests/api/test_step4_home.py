"""改进清单-4 · 第 3 步：主页示例问题（管理员维护，示例结果来自运行记录的快照）。"""
from __future__ import annotations

from .conftest import first_dataset
from .test_step3_runs_retention import _admin, _derive, _set


def _numeric(ds):
    cols = ds["schema"]["columns"]
    return [c["name"] for c in cols if any(t in c["dtype"] for t in ("float", "int"))]


def test_default_is_unconfigured_and_readable_by_everyone(client, alice):
    client.put("/api/home/examples", headers=alice["h"], json={"tabs": None})  # 403 for non-admin; harmless
    r = client.get("/api/home/examples", headers=alice["h"])
    assert r.status_code == 200
    assert "tabs" in r.json()


def test_non_admin_cannot_change_or_snapshot(client, alice):
    r = client.put("/api/home/examples", headers=alice["h"], json={"tabs": []})
    assert r.status_code == 403
    assert client.get("/api/home/examples/runs", headers=alice["h"]).status_code == 403
    r = client.post("/api/home/examples/snapshot", headers=alice["h"], json={"run_id": 1, "x": "a", "ys": ["b"]})
    assert r.status_code == 403


def test_admin_config_with_snapshot_survives_cleaning(client, alice, bob):
    _admin(alice)
    ds = first_dataset(client, alice)
    num = _numeric(ds)
    assert len(num) >= 2, ds["schema"]
    did = _derive(client, alice, ds, "moving_average", {"window": 3})

    runs = client.get("/api/home/examples/runs", headers=alice["h"]).json()
    run = next(r for r in runs if r["slug"] == "moving_average")
    assert run["code"].startswith("R-") and len(run["columns"]) >= 2

    snap = client.post("/api/home/examples/snapshot", headers=alice["h"], json={
        "run_id": run["id"], "x": run["columns"][0], "ys": [run["columns"][1]], "title": "测试结果"}).json()
    assert snap["title"] == "测试结果" and snap["run_id"] == run["id"]
    assert len(snap["x"]["values"]) == len(snap["ys"][0]["values"]) <= 500
    assert any("moving_average" in s for s in snap["chain"])

    cfg = {"tabs": [{"id": "t1", "name": "结构试验", "questions": [
        {"id": "q1", "text": "应变峰值在哪里？", "needs": "应变时间序列", "snapshot": snap,
         "kpis": [{"label": "峰值", "value": "1200", "unit": "με"}]},
        {"id": "q2", "text": "只有文字说明的问题", "methods": "find_peaks"},
    ]}]}
    r = client.put("/api/home/examples", headers=alice["h"], json=cfg)
    assert r.status_code == 200, r.text

    # Another (non-admin) user reads the same config, snapshot included.
    got = client.get("/api/home/examples", headers=bob["h"]).json()
    q1 = got["tabs"][0]["questions"][0]
    assert got["tabs"][0]["name"] == "结构试验" and q1["snapshot"]["x"]["values"] == snap["x"]["values"]

    # The source result is cleaned → the copied example is unaffected.
    _set(did, state="'cleaned'")
    again = client.get("/api/home/examples", headers=bob["h"]).json()
    assert again["tabs"][0]["questions"][0]["snapshot"]["ys"][0]["values"] == snap["ys"][0]["values"]

    # Restore defaults.
    assert client.put("/api/home/examples", headers=alice["h"], json={"tabs": None}).json() == {"tabs": None}
    assert client.get("/api/home/examples", headers=bob["h"]).json() == {"tabs": None}


def test_snapshot_only_from_own_runs(client, alice, bob):
    _admin(alice)
    _admin(bob)
    ds = first_dataset(client, bob)
    _derive(client, bob, ds, "moving_average", {"window": 3})
    bob_run = client.get("/api/home/examples/runs", headers=bob["h"]).json()[0]
    r = client.post("/api/home/examples/snapshot", headers=alice["h"], json={
        "run_id": bob_run["id"], "x": bob_run["columns"][0], "ys": [bob_run["columns"][1]]})
    assert r.status_code == 404


def test_validation_limits(client, alice):
    _admin(alice)
    too_many = {"tabs": [{"id": f"t{i}", "name": f"页{i}", "questions": []} for i in range(9)]}
    assert client.put("/api/home/examples", headers=alice["h"], json=too_many).status_code == 422
    bad = {"tabs": [{"id": "t", "name": "页", "questions": [{"id": "q", "text": "x", "snapshot": {
        "title": "t", "x": {"name": "a", "values": [1, 2, 3]}, "ys": [{"name": "b", "values": [1, 2]}]}}]}]}
    assert client.put("/api/home/examples", headers=alice["h"], json=bad).status_code == 400
