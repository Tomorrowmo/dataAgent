"""A chat turn outlives the browser connection that started it.

Bug: start an analysis, switch to a new one before it answers, come back — both
conversations had only the user's question. The turn ran inside the SSE response,
so a disconnect cancelled the agent AND the save in `finally`. Now the turn runs
as its own task: leaving only ends a subscription; only POST …/stop ends a turn.

TestClient buffers streamed bodies, so "leaving mid-stream" can't be done over
HTTP here. The turn is started on the server's own loop (client.portal) through
the same function /send uses, and subscribers are closed by hand.
"""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from .conftest import signup


class _FakeLLM:
    is_configured = True


def _fake_run_turn(delay: float, steps: int):
    async def run_turn(**kw):
        for i in range(steps):
            await asyncio.sleep(delay)
            yield SimpleNamespace(kind="thought", payload={"text": f"第 {i + 1} 步"})
        yield SimpleNamespace(kind="final", payload={"text": "最终回答：两次吹风一致"})
    return run_turn


@pytest.fixture()
def agent(monkeypatch, client):
    import app.api.chat as chat
    monkeypatch.setattr(chat, "llm_for", lambda user: _FakeLLM())

    def start(cid: int, uid: int, delay: float, steps: int = 3):
        monkeypatch.setattr(chat, "run_turn", _fake_run_turn(delay, steps))

        async def go():
            turn = chat.chat_turns.start(cid, uid)
            turn.task = asyncio.create_task(chat._run_turn_task(
                turn, owner_id=uid, llm=_FakeLLM(), dataset_ids=[], history=[], message="问题",
                image_ref=None, image_fresh=False, skill_ids=None))
            # a subscriber that reads the first event, then goes away (the user switches)
            sub = turn.follow(0)
            while not (await sub.__anext__()).startswith("data:"):
                pass
            await sub.aclose()
        client.portal.call(go)
    return start


def _conv(client, u) -> int:
    return client.post("/api/chat/conversations", headers=u["h"], json={}).json()["id"]


def _wait_assistant(client, u, cid, timeout=15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        msgs = client.get(f"/api/chat/conversations/{cid}/messages", headers=u["h"]).json()
        a = [m for m in msgs if m["role"] == "assistant"]
        if a:
            return a
        time.sleep(0.1)
    return []


def test_answer_survives_subscriber_leaving(client, agent):
    u = signup(client, "turn")
    cid = _conv(client, u)
    agent(cid, u["id"], delay=0.3)
    # the turn is still running after its only viewer left …
    assert client.post(f"/api/chat/conversations/{cid}/send", headers=u["h"], json={"message": "再问"}).status_code == 409
    # … and finishes and saves on its own
    a = _wait_assistant(client, u, cid)
    assert a and a[-1]["content"] == "最终回答：两次吹风一致" and not a[-1]["meta"].get("cancelled")
    kinds = [e["kind"] for e in a[-1]["meta"]["events"]]
    assert kinds.count("thought") == 3 and kinds[-1] == "final"


def test_stop_saves_partial_and_marks_cancelled(client, agent):
    u = signup(client, "turn")
    cid = _conv(client, u)
    agent(cid, u["id"], delay=0.5, steps=20)
    assert client.post(f"/api/chat/conversations/{cid}/stop", headers=u["h"]).json()["stopped"] is True
    a = _wait_assistant(client, u, cid)
    assert a and a[-1]["meta"].get("cancelled") is True
    assert any(e["kind"] == "thought" for e in a[-1]["meta"]["events"])


def test_live_reattach_replays_and_is_owner_only(client, agent):
    u = signup(client, "turn")
    cid = _conv(client, u)
    assert client.get(f"/api/chat/conversations/{cid}/live", headers=u["h"]).status_code == 204
    agent(cid, u["id"], delay=0.3)
    bob = signup(client, "bob")
    assert client.get(f"/api/chat/conversations/{cid}/live", headers=bob["h"]).status_code == 204
    assert client.post(f"/api/chat/conversations/{cid}/stop", headers=bob["h"]).json()["stopped"] is False
    r = client.get(f"/api/chat/conversations/{cid}/live", headers=u["h"])   # buffered: returns once the turn ends
    kinds = [json.loads(l[5:])["kind"] for l in r.text.splitlines() if l.startswith("data:")]
    assert kinds[0] == "thought" and kinds[-1] == "final"
