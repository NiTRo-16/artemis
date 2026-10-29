"""Rate limits shared by every API process, kept in Redis.

Keys are HMACs of what's being limited (a network address, an account, an email address), so Redis never
holds the address itself, and each key expires once it has been idle for its window. Redis runs without
writing to disk, which keeps the privacy policy's promise that IP addresses stay in memory.

The sync client is used on purpose: each check is two short round trips to Redis on the same machine,
and keeping it synchronous leaves every call site in main.py unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets
import time

from fastapi import HTTPException

import store

SECRET = os.environ.get("RATE_LIMIT_SECRET", "development-only-secret").encode()
MULTIPLIER = int(os.environ.get("RATE_LIMIT_MULTIPLIER", "1"))   # raised only by docker-compose.loadtest.yml


class RateLimiter:
    """At most `limit` hits per key within `window` seconds (a sliding window)."""

    def __init__(self, name: str, window: float) -> None:
        self.name = name
        self.window = window

    def _key(self, key: str) -> str:
        return f"rl:{self.name}:" + hmac.new(SECRET, key.encode(), hashlib.sha256).hexdigest()[:32]

    def blocked(self, key: str, limit: int) -> bool:
        k, now = self._key(key), time.time()
        pipe = store.sync_client().pipeline()
        pipe.zremrangebyscore(k, 0, now - self.window)
        pipe.zcard(k)
        return pipe.execute()[1] >= limit * MULTIPLIER

    def record(self, key: str) -> None:
        k, now = self._key(key), time.time()
        pipe = store.sync_client().pipeline()
        pipe.zadd(k, {f"{now}:{secrets.token_hex(4)}": now})
        pipe.expire(k, math.ceil(self.window))
        pipe.execute()

    def check(self, key: str, limit: int, message: str) -> None:
        """Count a hit, or refuse with 429 if the key is already at its limit."""
        if self.blocked(key, limit):
            raise HTTPException(429, message)
        self.record(key)

    def forget(self, key: str) -> None:
        """Clear one key's count, e.g. an account's wrong-password lockout once its password is reset."""
        store.sync_client().delete(self._key(key))

    def reset(self) -> None:
        """Forget every key of this limiter (used by tests)."""
        client = store.sync_client()
        for k in client.scan_iter(f"rl:{self.name}:*"):
            client.delete(k)
