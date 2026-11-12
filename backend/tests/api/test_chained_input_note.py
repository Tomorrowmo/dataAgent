"""Chained run_tool input is visible, and the agent can switch back to the source.

Reported: the home page's first example ("取α≤10°为线性段，求升力线斜率…") gave a
stall angle of 10° / CLmax 1.14 instead of 14° / 1.38 — the AI filtered to the
15 linear-range rows, and its next tool silently ran on those 15 rows. Chaining
stays the default; every step that didn't read the source now carries
`input_note` (which step, how many rows vs. the source), and `input: "source"`
reruns a step on the full data.
"""
from __future__ import annotations

import io
import json
import time

import pytest

from .conftest import signup

_CSV = "alpha_deg,CL\n" + "\n".join(f"{a},{min(0.1 * a + 0.2, 1.38 - 0.05 * max(0, a - 14) ** 2):.4f}"
                                    for a in range(-4, 27)) + "\n"   # 31 rows, CLmax at 14°


def _act(action: str, **args) -> str:
    return json.dumps({"thought": action, "action": action, "args": args}, ensure_ascii=False)


class _ScriptedLLM:
    is_configured = True
    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    async def stream(self, messages, **kw):
        yield self.replies.pop(0) if self.replies else _act("answer", text="完")

    async def chat(self, messages, **kw):
        return "{}"


@pytest.fixture()
def scripted(monkeypatch):
    import app.api.chat as chat

    def use(replies):
        llm = _ScriptedLLM(replies)
        monkeypatch.setattr(chat, "llm_for", lambda user: llm)
    return use


def _wait_events(client, u, cid, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        msgs = client.get(f"/api/chat/conversations/{cid}/messages", headers=u["h"]).json()
        a = [m for m in msgs if m["role"] == "assistant"]
        if a:
            return a[-1]["meta"].get("events", [])
        time.sleep(0.1)
    raise AssertionError("turn did not finish")


def test_input_note_marks_reduced_chain_and_source_switch(client, scripted):
    u = signup(client, "chain")
    r = client.post("/api/datasets", headers=u["h"],
                    files={"file": ("polar.csv", io.BytesIO(_CSV.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    did = r.json()["dataset"]["id"]
    n_src = r.json()["dataset"]["rows"]
    assert n_src >= 25

    scripted([
        _act("run_tool", slug="filter_rows", params={"condition": "alpha_deg <= 10"}),
        _act("run_tool", slug="filter_rows", params={"condition": "alpha_deg > -100"}),                   # chained on 15 rows
        _act("run_tool", slug="filter_rows", params={"condition": "alpha_deg > -100"}, input="source"),   # full data
        _act("answer", text="完成"),
    ])
    cid = client.post("/api/chat/conversations", headers=u["h"], json={}).json()["id"]
    r = client.post(f"/api/chat/conversations/{cid}/send", headers=u["h"],
                    json={"message": "求失速攻角", "dataset_ids": [did]})
    assert r.status_code == 200, r.text

    results = [e["payload"]["result"] for e in _wait_events(client, u, cid)
               if e["kind"] == "tool_result" and e["payload"].get("action") == "run_tool"]
    assert len(results) == 3, results

    first, chained, from_source = results
    assert "input_note" not in first                      # step 1 read the source itself
    note = chained["input_note"]
    assert note["source"] is False and note["rows"] == 15 and note["source_rows"] == n_src
    assert note["reduced"] is True and '"input": "source"' in note["text"]
    assert list(chained)[0] == "input_note"               # first key → survives the LLM-copy cap
    assert from_source["input_note"]["source"] is True
    assert from_source["input_note"]["rows"] == n_src
    assert from_source["summary"]["rows"] == n_src
