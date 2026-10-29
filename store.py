"""Shared Redis connections: one synchronous client (rate limits) and one asyncio client per event loop
(job queue, live progress, caches).

REDIS_URL=fake:// uses an in-memory fake (fakeredis), for tests that don't need a real Redis.
"""
from __future__ import annotations

import asyncio
import os
import weakref

import redis
import redis.asyncio

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_sync: redis.Redis | None = None
_async: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.asyncio.Redis]" = weakref.WeakKeyDictionary()
_fake_server = None


def _fake_server_instance():
    global _fake_server
    import fakeredis
    if _fake_server is None:
        _fake_server = fakeredis.FakeServer()
    return _fake_server


def sync_client() -> redis.Redis:
    global _sync
    if _sync is None:
        if REDIS_URL.startswith("fake://"):
            import fakeredis
            _sync = fakeredis.FakeRedis(server=_fake_server_instance(), decode_responses=True)
        else:
            _sync = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    return _sync


def async_client() -> redis.asyncio.Redis:
    """The asyncio client for the running event loop (one client can't be shared between loops)."""
    loop = asyncio.get_running_loop()
    client = _async.get(loop)
    if client is None:
        if REDIS_URL.startswith("fake://"):
            import fakeredis
            client = fakeredis.FakeAsyncRedis(server=_fake_server_instance(), decode_responses=True)
        else:
            # Longer than the longest blocking read (5 s), so a quiet queue isn't taken for a dead connection.
            client = redis.asyncio.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=10,
                                                  socket_connect_timeout=2)
        _async[loop] = client
    return client
