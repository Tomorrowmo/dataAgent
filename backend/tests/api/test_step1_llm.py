"""第 1 步 · O2：有效模型配置判断（用户密钥 / 仅服务器密钥 / 都没有）。"""
from __future__ import annotations

import pytest


@pytest.fixture()
def server_key(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()

    def _set(v: str):
        monkeypatch.setattr(s, "deepseek_api_key", v, raising=False)
    return _set


def test_no_key_anywhere(client, alice, server_key):
    server_key("")
    me = client.get("/api/auth/me", headers=alice["h"]).json()
    assert me["has_llm_key"] is False and me["llm_available"] is False


def test_server_key_only(client, alice, server_key):
    server_key("sk-server-default")
    me = client.get("/api/auth/me", headers=alice["h"]).json()
    assert me["has_llm_key"] is False and me["llm_available"] is True


def test_user_key(client, alice, server_key):
    server_key("")
    r = client.put("/api/auth/llm-key", headers=alice["h"], json={"api_key": "sk-user"})
    assert r.status_code == 200, r.text
    me = client.get("/api/auth/me", headers=alice["h"]).json()
    assert me["has_llm_key"] is True and me["llm_available"] is True
