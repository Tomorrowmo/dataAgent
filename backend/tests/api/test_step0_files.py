"""第 0 步：文件访问鉴权与结果归属。"""
from __future__ import annotations

from .conftest import find_paths, first_dataset


def _run_smooth(client, user):
    ds = first_dataset(client, user)
    col = ds["schema"]["columns"][0]["name"]
    r = client.post("/api/algorithms/run", headers=user["h"], json={
        "slug": "moving_average", "params": {"columns": [col], "window": 3}, "dataset_id": ds["id"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok", body
    return ds, body


def test_run_returns_artifact_id_and_no_paths(client, alice, upload_root):
    _, body = _run_smooth(client, alice)
    assert isinstance(body.get("artifact_id"), int)
    assert "result_path" not in body
    assert find_paths(body, [str(upload_root), upload_root.as_posix(), "da_sbox_"]) == []


def test_result_written_under_owner_dir(client, alice, upload_root):
    _run_smooth(client, alice)
    assert not (upload_root / "results").exists()
    tmp = upload_root / f"user_{alice['id']}" / "tmp"
    assert any(tmp.glob("*.parquet"))


def test_artifact_owner_can_preview_and_export(client, alice):
    _, body = _run_smooth(client, alice)
    aid = body["artifact_id"]
    r = client.get(f"/api/artifacts/{aid}/preview?limit=5", headers=alice["h"])
    assert r.status_code == 200 and r.json()["shown"] <= 5
    for fmt, ctype in (("csv", "text/csv"), ("xlsx", "spreadsheet")):
        r = client.get(f"/api/artifacts/{aid}/export?format={fmt}", headers=alice["h"])
        assert r.status_code == 200 and ctype in r.headers["content-type"]


def test_artifact_requires_login_and_ownership(client, alice, bob):
    _, body = _run_smooth(client, alice)
    aid = body["artifact_id"]
    assert client.get(f"/api/artifacts/{aid}/preview").status_code == 401
    assert client.get(f"/api/artifacts/{aid}/export").status_code == 401
    assert client.get(f"/api/artifacts/{aid}/preview", headers=bob["h"]).status_code == 404
    assert client.get(f"/api/artifacts/{aid}/export", headers=bob["h"]).status_code == 404


def test_dataset_export_requires_ownership(client, alice, bob):
    ds = first_dataset(client, alice)
    assert client.get(f"/api/datasets/{ds['id']}/export").status_code == 401
    assert client.get(f"/api/datasets/{ds['id']}/export", headers=bob["h"]).status_code == 404
    r = client.get(f"/api/datasets/{ds['id']}/export?format=csv", headers=alice["h"])
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")


def test_legacy_path_endpoints_are_gone(client, alice, upload_root):
    p = str(upload_root / f"user_{alice['id']}" / "x.parquet")
    for url in (f"/api/result-file?path={p}", f"/api/datasets/export?path={p}", f"/api/datasets/preview-file?path={p}"):
        r = client.get(url, headers=alice["h"])
        assert r.status_code in (404, 405, 422), (url, r.status_code)
        assert r.status_code != 200


def test_no_server_paths_in_error_responses(client, alice, upload_root):
    ds = first_dataset(client, alice)
    # A failing sandbox run produces a traceback — it must not carry server paths.
    r = client.post("/api/algorithms/test", headers=alice["h"], json={
        "code": "META = {'name': 'x', 'slug': 'x'}\ndef run(df, **p):\n    raise ValueError(open('nope.txt').read())\n",
        "params": {}, "dataset_id": ds["id"],
    })
    assert r.status_code == 200
    assert find_paths(r.json(), [str(upload_root), upload_root.as_posix(), "da_sbox_"]) == []
