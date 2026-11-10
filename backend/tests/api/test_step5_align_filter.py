"""改进清单-10: filter_rows + align_datasets (a param of type "dataset")."""
import pandas as pd

from .conftest import signup


def _builtin(slug, df, params, frames=None):
    import app.algorithms.bootstrap  # noqa: F401  registers builtins
    from app.algorithms import registry
    return registry.execute_builtin(slug, df, params, frames=frames)


def _frame(res):
    return pd.read_parquet(res["result_path"])


DF = pd.DataFrame({"alpha_deg": [-4, 0, 4, 8, 12, 16], "CL": [-0.3, 0.1, 0.5, 0.9, 1.3, 1.1]})


def test_filter_rows_range_and_chain():
    a = _frame(_builtin("filter_rows", DF, {"condition": "alpha_deg >= 0 and alpha_deg <= 12"}))
    b = _frame(_builtin("filter_rows", DF, {"condition": "0 <= alpha_deg <= 12"}))
    assert a["alpha_deg"].tolist() == [0, 4, 8, 12] == b["alpha_deg"].tolist()


def test_filter_rows_all_removed_says_why():
    r = _builtin("filter_rows", DF, {"condition": "alpha_deg > 100"})
    assert r["status"] == "error" and "都筛掉了" in r["error"] and "alpha_deg" in r["error"]


def test_filter_rows_rejects_attribute_access():
    r = _builtin("filter_rows", DF, {"condition": "CL.to_csv('x.csv')"})
    assert r["status"] == "error"


def test_align_datasets_suffixes_and_inner_join():
    other = pd.DataFrame({"alpha_deg": [0, 4, 8, 20], "CL": [0.12, 0.49, 0.93, 0.8]})
    out = _frame(_builtin("align_datasets", DF, {"other": "B", "on": "alpha_deg", "columns": ["CL"]}, frames={"other": other}))
    assert out.columns.tolist() == ["alpha_deg", "CL_A", "CL_B"]
    assert out["alpha_deg"].tolist() == [0, 4, 8]


def test_align_datasets_unknown_second_dataset():
    r = _builtin("align_datasets", DF, {"other": "不存在的数据", "on": "alpha_deg"})
    assert r["status"] == "error" and "不存在的数据" in r["error"]


def test_align_via_api_resolves_by_name_and_records_name(client):
    u = signup(client, "align")
    srcs = [d for d in client.get("/api/datasets", headers=u["h"]).json() if d["kind"] == "source"]
    a, b = srcs[0], srcs[1]
    key = a["schema"]["columns"][0]["name"]
    # align a dataset with ITSELF by name: always alignable, proves the name lookup works
    r = client.post("/api/algorithms/run-to-dataset", headers=u["h"],
                    json={"slug": "align_datasets", "dataset_id": a["id"], "params": {"other": a["name"], "on": key}})
    assert r.status_code == 200, r.text
    d = r.json()
    full = client.get(f"/api/datasets/{d['id']}", headers=u["h"]).json()
    cols = [c["name"] for c in full["schema"]["columns"]]
    assert cols[0] == key and any(c.endswith("_A") for c in cols) and any(c.endswith("_B") for c in cols)
    # the run record keeps the plain name, not a table
    prov = client.get(f"/api/datasets/{d['id']}/provenance", headers=u["h"]).json()
    assert prov["run"]["params"]["other"] == a["name"]
    assert b["id"] != a["id"]
