"""删除对话后，运行记录与该对话脱钩；SQLite 重用编号时新对话不继承旧结果。"""
from __future__ import annotations

from .conftest import first_dataset
from .test_step3_runs_retention import _db, _derive, _ds


def test_deleted_conversation_does_not_leak_results_into_a_reused_id(client, alice):
    ds = first_dataset(client, alice)
    conv = client.post("/api/chat/conversations", headers=alice["h"], json={"title": "旧对话"}).json()
    did = _derive(client, alice, ds)
    # Pretend the run came from this conversation (a chat run sets this).
    with _db() as c:
        gid = c.execute("SELECT r.group_id FROM runs r WHERE r.result_dataset_id = ?", (did,)).fetchone()[0]
        c.execute("UPDATE run_groups SET conversation_id = ?, entry = 'chat' WHERE id = ?", (conv["id"], gid))
    assert _ds(client, alice, did)["origin"]["conversation"]["id"] == conv["id"]

    assert client.delete(f"/api/chat/conversations/{conv['id']}", headers=alice["h"]).status_code == 200
    with _db() as c:
        assert c.execute("SELECT conversation_id FROM run_groups WHERE id = ?", (gid,)).fetchone()[0] is None
    origin = _ds(client, alice, did)["origin"]["conversation"]
    assert origin == {"id": None, "title": "（已删除的对话）", "exists": False}

    # A new conversation — possibly with the same id — has no results of its own.
    new = client.post("/api/chat/conversations", headers=alice["h"], json={"title": "新对话"}).json()
    owned = [d for d in client.get("/api/datasets", headers=alice["h"]).json()
             if (d.get("origin") or {}).get("conversation", {}).get("id") == new["id"]]
    assert owned == []
