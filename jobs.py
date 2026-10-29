"""The scan job queue, live progress and result cache, all in Redis.

A scan is a job: the API adds it to the stream QUEUE; a worker takes it through the consumer group GROUP,
streams progress events to scan:<id>:events, stores the report and acknowledges the job. A job a worker
took but never acknowledged (because the worker died) is claimed by another worker after STALE_MS.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator

from redis.exceptions import ResponseError

QUEUE = "scans:queue"
GROUP = "workers"
MAX_QUEUED = 200            # waiting or running; beyond this the API answers "busy"
STALE_MS = 90_000           # unacknowledged this long: retried by another worker (a scan takes at most 45 s)
MAX_ATTEMPTS = 2
RESULT_SECONDS = 24 * 3600  # job state and results
EVENTS_SECONDS = 3600       # progress streams
CACHE_SECONDS = 15 * 60     # the same target scanned again within this gets the saved result
HEARTBEAT_SECONDS = 60      # a worker silent for this long counts as gone


class QueueFull(Exception):
    pass


def _job(job_id: str) -> str:
    return f"scan:{job_id}"


def _events(job_id: str) -> str:
    return f"scan:{job_id}:events"


def _result(job_id: str) -> str:
    return f"scan:{job_id}:result"


def cache_key(host: str, path: str | None) -> str:
    return hashlib.sha256(f"{host}{path or ''}".encode()).hexdigest()


async def ensure_group(r) -> None:
    try:
        await r.xgroup_create(QUEUE, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):   # already exists: fine
            raise


async def submit(r, target: str, cache_key: str, user_id: int | None) -> tuple[str, bool]:
    """Queue a scan, or return a recent result for the same target. Returns (job id, was cached)."""
    cached = await r.get(f"cache:{cache_key}")
    if cached and await r.exists(_result(cached)):
        return cached, True
    if await r.xlen(QUEUE) >= MAX_QUEUED:
        raise QueueFull
    job_id = secrets.token_urlsafe(16)
    await r.hset(_job(job_id), mapping={"status": "queued", "target": target, "attempts": 0,
                                        "created": int(time.time())})
    await r.expire(_job(job_id), RESULT_SECONDS)
    await r.xadd(QUEUE, {"job": job_id, "target": target, "cache_key": cache_key, "user_id": str(user_id or "")})
    return job_id, False


async def claim(r, consumer: str, block_ms: int | None = 5000) -> tuple[str, dict] | None:
    """The next job for this worker: first one a dead worker left behind, else a new one.
    block_ms=None returns at once when there's nothing to do."""
    reply = await r.xautoclaim(QUEUE, GROUP, consumer, min_idle_time=STALE_MS, start_id="0-0", count=1)
    entries = [e for e in reply[1] if e and e[1]]   # skip entries deleted meanwhile
    if not entries:
        found = await r.xreadgroup(GROUP, consumer, {QUEUE: ">"}, count=1, block=block_ms)
        entries = found[0][1] if found else []
    if not entries:
        return None
    entry_id, fields = entries[0]
    return entry_id, fields


async def ack(r, entry_id: str) -> None:
    await r.xack(QUEUE, GROUP, entry_id)
    await r.xdel(QUEUE, entry_id)


async def start(r, job_id: str) -> int:
    """Mark a job running; returns which attempt this is."""
    attempts = await r.hincrby(_job(job_id), "attempts", 1)
    await r.hset(_job(job_id), "status", "running")
    return attempts


async def publish(r, job_id: str, event: dict) -> None:
    await r.xadd(_events(job_id), {"data": json.dumps(event)})
    await r.expire(_events(job_id), EVENTS_SECONDS)


async def finish(r, job_id: str, report: dict, cache_key: str) -> None:
    await r.set(_result(job_id), json.dumps(report), ex=RESULT_SECONDS)
    await r.hset(_job(job_id), "status", "done")
    await r.set(f"cache:{cache_key}", job_id, ex=CACHE_SECONDS)
    await publish(r, job_id, {"type": "done"})


async def fail(r, job_id: str, message: str, code: int) -> None:
    await r.hset(_job(job_id), mapping={"status": "error", "error": message, "code": code})
    await publish(r, job_id, {"type": "error", "message": message, "code": code})


async def state(r, job_id: str) -> dict | None:
    """{"id", "status": queued, running, done or error, "report" when done, "error" and "code" when failed}."""
    job = await r.hgetall(_job(job_id))
    if not job:
        return None
    out = {"id": job_id, "status": job["status"]}
    if job["status"] == "done":
        raw = await r.get(_result(job_id))
        if raw is None:
            return None
        out["report"] = json.loads(raw)
    elif job["status"] == "error":
        out["error"] = job.get("error", "The scan failed. Try again.")
        out["code"] = int(job.get("code", 500))
    return out


async def events(r, job_id: str, timeout: float = 120.0) -> AsyncIterator[dict]:
    """A job's progress events from the first, ending with "done" or "error" (or at the timeout)."""
    last, deadline = "0", time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = await r.xread({_events(job_id): last}, count=100, block=1000)
        if not reply:
            await asyncio.sleep(0.05)   # the in-memory Redis used in tests returns at once instead of waiting
            continue
        for entry_id, fields in reply[0][1]:
            last = entry_id
            event = json.loads(fields["data"])
            yield event
            if event["type"] in ("done", "error"):
                return


async def past_events(r, job_id: str) -> list[dict]:
    """Every event recorded so far, without waiting (empty once the progress stream has expired)."""
    return [json.loads(fields["data"]) for _, fields in await r.xrange(_events(job_id))]


async def heartbeat(r, worker_id: str, renderer_error: str | None) -> None:
    await r.set(f"workers:{worker_id}", json.dumps({"renderer_error": renderer_error}), ex=HEARTBEAT_SECONDS)


async def healthy_workers(r) -> int:
    """Workers that reported recently and whose sandboxed browser passed its self-test."""
    count = 0
    async for key in r.scan_iter("workers:*"):
        raw = await r.get(key)
        if raw and not json.loads(raw)["renderer_error"]:
            count += 1
    return count
