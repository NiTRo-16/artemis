"""The worker loop: takes jobs, streams progress, stores results, gives up after two attempts."""
import asyncio
import os

os.environ["REDIS_URL"] = "fake://"
import jobs  # noqa: E402
import render  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402
from scanner import ScanError  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def fake_scan(target, progress=None):
    if target == "bad input":
        raise ScanError("Enter a public domain or link, like example.com.")
    await progress("certificate", "ok")
    return {"domain": target, "risk": {"score": 5, "label": "Low"},
            "impersonation": {"verdict": "No impersonation signs"}, "payment": None}


async def no_browser():
    return None

worker.scan = fake_scan
render.self_test = no_browser
render.shutdown = no_browser


async def wait_for(r, job_id, status, seconds=5):
    for _ in range(seconds * 20):
        state = await jobs.state(r, job_id)
        if state and state["status"] == status:
            return state
        await asyncio.sleep(0.05)
    return await jobs.state(r, job_id)


async def main():
    r = store.async_client()
    await r.flushdb()
    stop = asyncio.Event()
    loop = asyncio.create_task(worker.serve(stop))
    job_id, _ = await jobs.submit(r, "site.example", jobs.cache_key("site.example", None), None)
    state = await wait_for(r, job_id, "done")
    ok("the worker finishes a queued scan", state["status"] == "done" and state["report"]["domain"] == "site.example")
    events = [e async for e in jobs.events(r, job_id, timeout=2)]
    ok("its progress was streamed", {"type": "step", "step": "certificate", "status": "ok"} in events)
    ok("the job left the queue", await r.xlen(jobs.QUEUE) == 0)
    ok("the worker reported in as healthy", await jobs.healthy_workers(r) == 1)

    bad, _ = await jobs.submit(r, "bad input", "k-bad", None)
    state = await wait_for(r, bad, "error")
    ok("a rejected target ends with the scanner's message and 400",
       state["code"] == 400 and state["error"].startswith("Enter a public domain"))

    stop.set()
    await asyncio.wait_for(loop, 10)
    ok("the worker stops cleanly and removes its heartbeat", await jobs.healthy_workers(r) == 0)

    tired, _ = await jobs.submit(r, "site2.example", "k-tired", None)
    await r.hset(f"scan:{tired}", "attempts", jobs.MAX_ATTEMPTS)
    entry_id, fields = await jobs.claim(r, "w", block_ms=None)
    await worker.run_job(r, fields["job"], fields)
    ok("a job past its attempts fails instead of running again", (await jobs.state(r, tired))["status"] == "error")

asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
