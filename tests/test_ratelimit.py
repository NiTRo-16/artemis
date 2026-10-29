"""Rate limits shared through Redis (the in-memory fake here)."""
import os
import time

os.environ["REDIS_URL"] = "fake://"
os.environ["RATE_LIMIT_SECRET"] = "test-secret"
from fastapi import HTTPException  # noqa: E402

import store  # noqa: E402
from ratelimit import RateLimiter  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def refused(limiter, key, limit):
    try:
        limiter.check(key, limit, "slow down")
        return False
    except HTTPException as exc:
        return exc.status_code == 429 and exc.detail == "slow down"


rl = RateLimiter("test", 60.0)
for _ in range(3):
    rl.check("203.0.113.5", 3, "slow down")
ok("fourth hit within the window is refused", refused(rl, "203.0.113.5", 3))
ok("another visitor has their own count", not refused(rl, "198.51.100.7", 3))
ok("Redis never holds the address itself", not any("203.0.113.5" in k for k in store.sync_client().keys("*")))
ok("keys expire on their own", all(0 < store.sync_client().ttl(k) <= 60 for k in store.sync_client().keys("rl:test:*")))
rl.forget("203.0.113.5")   # 198.51.100.7 still has the one hit from above
ok("forget clears one key", not refused(rl, "203.0.113.5", 3) and rl.blocked("198.51.100.7", 1))
rl.reset()
ok("reset clears every key", not refused(rl, "203.0.113.5", 3) and not rl.blocked("198.51.100.7", 1))

short = RateLimiter("short", 0.3)
short.check("k", 1, "x")
ok("blocked inside the window", short.blocked("k", 1))
time.sleep(0.4)
ok("allowed again once the window passes", not short.blocked("k", 1))

second = RateLimiter("test", 60.0)   # what another API process would create
rl.check("shared", 1, "x")
ok("another process sees the same count", second.blocked("shared", 1))
print(f"\n{sum(results)}/{len(results)} passed")
