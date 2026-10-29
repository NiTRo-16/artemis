"""Load test: many simulated visitors start scans and wait for their results.

    python loadtest/run.py --base-url http://app:8000 --users 50 --seconds 60

Every scan is a new made-up domain, so nothing is answered from the result cache. Use it only against a
test copy started with docker-compose.loadtest.yml, whose workers fake their scans (no site is contacted)
and whose rate limits are raised so one machine can stand in for many visitors.
"""
import argparse
import asyncio
import itertools
import statistics
import time

import httpx


async def visitor(client, targets, deadline, stats):
    while time.monotonic() < deadline:
        target = next(targets)
        started = time.monotonic()
        try:
            resp = await client.post("/api/scans", json={"target": target})
        except httpx.HTTPError as exc:
            stats["refused"][type(exc).__name__] = stats["refused"].get(type(exc).__name__, 0) + 1
            continue
        stats["submit"].append(time.monotonic() - started)
        if resp.status_code not in (200, 202):
            stats["refused"][resp.status_code] = stats["refused"].get(resp.status_code, 0) + 1
            await asyncio.sleep(1)
            continue
        job_id = resp.json()["id"]
        while True:
            state = (await client.get(f"/api/scans/{job_id}")).json()
            if state["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.5)
        stats["total"].append(time.monotonic() - started)
        stats["outcomes"][state["status"]] = stats["outcomes"].get(state["status"], 0) + 1


def pct(values, p):
    return sorted(values)[min(len(values) - 1, int(len(values) * p))] if values else 0.0


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=60)
    args = ap.parse_args()
    counter = itertools.count()
    targets = (f"load-{int(time.time())}-{n}.example" for n in counter)
    stats = {"submit": [], "total": [], "refused": {}, "outcomes": {}}
    deadline = time.monotonic() + args.seconds
    limits = httpx.Limits(max_connections=args.users, max_keepalive_connections=args.users)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=60, limits=limits) as client:
        await asyncio.gather(*(visitor(client, targets, deadline, stats) for _ in range(args.users)))
    done = len(stats["total"])
    print(f"visitors={args.users} seconds={args.seconds}")
    print(f"finished={done} per_minute={done / args.seconds * 60:.0f} outcomes={stats['outcomes']} refused={stats['refused'] or 'none'}")
    if stats["submit"]:
        print(f"start_request_ms median={statistics.median(stats['submit']) * 1000:.0f} p95={pct(stats['submit'], 0.95) * 1000:.0f}")
    if done:
        print(f"time_to_result_s median={statistics.median(stats['total']):.1f} p95={pct(stats['total'], 0.95):.1f}")


if __name__ == "__main__":
    asyncio.run(main())
