"""In-flight chat turns, decoupled from the HTTP request that started them.

A turn used to run INSIDE the SSE response generator, so when the browser went
away (the user switched to another conversation, opened a new analysis, reloaded
the page) the generator was cancelled: the agent stopped mid-way, and even the
"persist what we have" step in `finally` was cancelled again by the request's
cancel scope — the conversation was left with the user's question and no answer.

Now each turn runs as its own asyncio task with its own DB session. It records
every event here; any number of SSE connections replay the events so far and then
follow new ones. A client disconnect only ends that subscription — the turn runs
to completion and saves its answer. Only an explicit stop (POST …/stop) cancels it.

Single-process registry: turns live in this worker's memory. A server restart
ends running turns (their partial answer is not saved), same as before.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

# How long a finished turn stays attachable, so a client that re-attaches right
# as it ends still gets the final event instead of a gap before the DB row loads.
_LINGER_S = 30.0
# Comment line sent while waiting, so idle proxies don't drop the stream.
_HEARTBEAT_S = 15.0


class Turn:
    def __init__(self, conv_id: int, owner_id: int) -> None:
        self.conv_id = conv_id
        self.owner_id = owner_id
        self.events: List[Dict[str, Any]] = []
        self.done = False
        self.task: Optional[asyncio.Task] = None
        self._cond = asyncio.Condition()

    async def push(self, event: Dict[str, Any]) -> None:
        self.events.append(event)
        async with self._cond:
            self._cond.notify_all()

    async def finish(self) -> None:
        self.done = True
        async with self._cond:
            self._cond.notify_all()
        asyncio.get_running_loop().call_later(_LINGER_S, _forget, self)

    async def follow(self, start: int = 0) -> AsyncIterator[str]:
        """SSE lines: every event from `start`, then new ones until the turn ends.
        Cancelling this generator (client gone) never touches the turn itself."""
        yield ": numetrix-stream-open\n\n"
        i = start
        while True:
            while i < len(self.events):
                yield _sse(self.events[i])
                i += 1
            if self.done:
                return
            async with self._cond:
                if i >= len(self.events) and not self.done:
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=_HEARTBEAT_S)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"


def _sse(event: Dict[str, Any]) -> str:
    try:
        return f"data: {json.dumps(event, default=str)}\n\n"
    except Exception:  # pragma: no cover — json failure is essentially never
        logger.exception("failed to serialize SSE event")
        return 'data: {"kind":"final","payload":{"text":"(serialization failed)","error":true}}\n\n'


_TURNS: Dict[int, Turn] = {}


def _forget(turn: Turn) -> None:
    if _TURNS.get(turn.conv_id) is turn:
        _TURNS.pop(turn.conv_id, None)


def running(conv_id: int, owner_id: int) -> Optional[Turn]:
    """The conversation's turn if one is still generating (owner-checked)."""
    t = _TURNS.get(conv_id)
    return t if t is not None and t.owner_id == owner_id and not t.done else None


def latest(conv_id: int, owner_id: int) -> Optional[Turn]:
    """Running, or finished within the linger window."""
    t = _TURNS.get(conv_id)
    return t if t is not None and t.owner_id == owner_id else None


def start(conv_id: int, owner_id: int) -> Turn:
    t = Turn(conv_id, owner_id)
    _TURNS[conv_id] = t
    return t
