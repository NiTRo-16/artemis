"""Redis connection helpers, against the in-memory fake."""
import asyncio
import os

os.environ["REDIS_URL"] = "fake://"
import store  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


store.sync_client().set("k", "v")
ok("sync client works", store.sync_client().get("k") == "v")


async def read():
    return await store.async_client().get("k")

ok("async client sees the same data", asyncio.run(read()) == "v")


async def same_twice():
    return store.async_client() is store.async_client()

ok("one async client per event loop", asyncio.run(same_twice()))
print(f"\n{sum(results)}/{len(results)} passed")
