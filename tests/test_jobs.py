"""The scan queue, job state, progress events and result cache (in-memory Redis by default)."""
import asyncio
import os

os.environ.setdefault("REDIS_URL", "fake://")   # or a real Redis database the test may empty
import jobs  # noqa: E402
import store  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def main():
    r = store.async_client()
    await r.flushdb()
    await jobs.ensure_group(r)
    await jobs.ensure_group(r)   # safe to call again
    key = jobs.cache_key("example.com", None)
    job_id, cached = await jobs.submit(r, "example.com", key, None)
    ok("a new target is queued", not cached and (await jobs.state(r, job_id))["status"] == "queued")

    entry_id, fields = await jobs.claim(r, "w1", block_ms=None)
    ok("a worker claims it with its fields", fields["job"] == job_id and fields["target"] == "example.com")
    ok("nothing else to claim", await jobs.claim(r, "w1", block_ms=None) is None)
    ok("first attempt", await jobs.start(r, job_id) == 1)
    await jobs.publish(r, job_id, {"type": "step", "step": "certificate", "status": "ok"})
    await jobs.finish(r, job_id, {"domain": "example.com"}, key)
    await jobs.ack(r, entry_id)
    events = [e async for e in jobs.events(r, job_id, timeout=2)]
    ok("events replay in order and end with done", [e["type"] for e in events] == ["step", "done"])
    ok("state holds the report", (await jobs.state(r, job_id))["report"] == {"domain": "example.com"})
    ok("acknowledged jobs leave the queue", await r.xlen(jobs.QUEUE) == 0)

    again, cached = await jobs.submit(r, "example.com", key, None)
    ok("the same target within 15 minutes returns the saved result", cached and again == job_id)

    failing, _ = await jobs.submit(r, "broken.example", jobs.cache_key("broken.example", None), None)
    entry_id, _ = await jobs.claim(r, "w1", block_ms=None)
    await jobs.fail(r, failing, "The scan timed out.", 504)
    await jobs.ack(r, entry_id)
    state = await jobs.state(r, failing)
    ok("a failed job keeps its message and code", state["status"] == "error" and state["code"] == 504)

    jobs.STALE_MS = 0   # treat any unacknowledged job as abandoned
    orphan, _ = await jobs.submit(r, "orphan.example", jobs.cache_key("orphan.example", None), None)
    await jobs.claim(r, "dead-worker", block_ms=None)
    reclaimed = await jobs.claim(r, "w2", block_ms=None)
    ok("a job a dead worker left behind is claimed by another", reclaimed and reclaimed[1]["job"] == orphan)

    jobs.MAX_QUEUED = 1
    try:
        await jobs.submit(r, "one-more.example", jobs.cache_key("one-more.example", None), None)
        ok("a full queue refuses new jobs", False)
    except jobs.QueueFull:
        ok("a full queue refuses new jobs", True)

    ok("an unknown job has no state", await jobs.state(r, "no-such-job") is None)
    await jobs.heartbeat(r, "w1", None)
    await jobs.heartbeat(r, "w2", "browser failed")
    ok("only workers with a working browser count as healthy", await jobs.healthy_workers(r) == 1)
    await r.flushdb()

asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
