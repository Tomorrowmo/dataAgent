"""A conversation remembers EVERY source dataset of a turn, not just the primary.

A comparison dataset that is only overlaid on a chart never gets a processing
chain, so reopening the conversation used to restore only the primary and the
next turn silently lost the second dataset. Each user message now records the
turn's full source set in meta.dataset_ids (primary first).
"""
from .conftest import signup


def test_user_message_records_all_sources(client):
    u = signup(client, "src")
    srcs = [d for d in client.get("/api/datasets", headers=u["h"]).json() if d["kind"] == "source"]
    assert len(srcs) >= 2, "signup should seed several example datasets"
    a, b = srcs[0]["id"], srcs[1]["id"]
    cid = client.post("/api/chat/conversations", headers=u["h"], json={"dataset_id": a}).json()["id"]

    # The reply itself may fail (no model configured in tests); the user message
    # is stored before the agent runs, which is all this checks.
    with client.stream("POST", f"/api/chat/conversations/{cid}/send", headers=u["h"],
                       json={"message": "两份数据对比一下", "dataset_ids": [a, b]}) as r:
        for _ in r.iter_lines():
            pass

    msgs = client.get(f"/api/chat/conversations/{cid}/messages", headers=u["h"]).json()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert user_msgs and user_msgs[-1]["meta"].get("dataset_ids") == [a, b]
