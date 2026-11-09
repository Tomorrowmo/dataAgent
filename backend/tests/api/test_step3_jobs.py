"""第 3 步 · R1：每日清理任务的循环、补跑与并发锁。"""
from __future__ import annotations

import asyncio

import pytest


def test_daily_loop_runs_now_then_every_24h(monkeypatch):
    from app.services import retention

    calls, sleeps = [], []

    async def fake_sweep():
        calls.append(1)
        return {"cleaned": 0}

    async def fake_sleep(sec):
        sleeps.append(sec)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(retention, "sweep_all", fake_sweep)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retention.daily_loop())
    assert len(calls) == 3                       # once at start (catch-up), then after each day
    assert sleeps == [24 * 3600] * 3


def test_daily_loop_survives_a_crashing_sweep(monkeypatch):
    from app.services import retention

    n = {"sweep": 0, "sleep": 0}

    async def boom():
        n["sweep"] += 1
        raise RuntimeError("disk full")

    async def fake_sleep(sec):
        n["sleep"] += 1
        if n["sleep"] >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(retention, "sweep_all", boom)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retention.daily_loop())
    assert n["sweep"] == 2                       # the crash didn't stop the loop


def test_lock_prevents_concurrent_sweeps(client):
    from app.services import retention
    lock = retention._acquire_lock()
    assert lock is not None
    try:
        assert retention._acquire_lock() is None            # a second sweep is refused
        assert asyncio.run(retention.sweep_all()) == {"skipped": "another sweep is running"}
    finally:
        lock.unlink()
    again = retention._acquire_lock()
    assert again is not None
    again.unlink()


def test_stale_lock_is_taken_over(client):
    import os
    import time
    from app.services import retention
    lock = retention._acquire_lock()
    old = time.time() - 7200
    os.utime(lock, (old, old))                               # a crashed run 2 h ago
    taken = retention._acquire_lock()
    assert taken is not None
    taken.unlink()
