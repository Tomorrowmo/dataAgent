"""Behaviour tests for the HTTP API, run against a throw-away database and
upload directory (never the developer's real data).

    cd backend && .venv/Scripts/python -m pytest tests/api -q
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="rlab_test_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'app.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = ""
os.environ["OIDC_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app import main

    with TestClient(main.app) as c:
        t0 = time.time()
        while not main._WARM["ready"]:
            assert main._WARM["error"] is None, main._WARM["error"]
            assert time.time() - t0 < 600, "backend warmup timed out"
            time.sleep(0.2)
        yield c


@pytest.fixture(scope="session")
def upload_root() -> Path:
    from app.services.storage import upload_root as _ur
    return _ur()


_n = [0]


def signup(client, name: str = "u") -> dict:
    _n[0] += 1
    email = f"{name}{_n[0]}_{int(time.time() * 1000)}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "name": name, "password": "pw-123456"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"id": r.json()["user_id"], "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture()
def alice(client):
    return signup(client, "alice")


@pytest.fixture()
def bob(client):
    return signup(client, "bob")


def first_dataset(client, user) -> dict:
    r = client.get("/api/datasets", headers=user["h"])
    assert r.status_code == 200, r.text
    ds = [d for d in r.json() if d["kind"] == "source"]
    assert ds, "signup should seed example datasets"
    return ds[0]


def find_paths(obj, needles) -> list:
    """Every string anywhere in obj that contains a server path marker."""
    hits = []
    if isinstance(obj, dict):
        for v in obj.values():
            hits += find_paths(v, needles)
    elif isinstance(obj, list):
        for v in obj:
            hits += find_paths(v, needles)
    elif isinstance(obj, str):
        if any(n.lower() in obj.lower() for n in needles):
            hits.append(obj)
    return hits
