"""Scan worker: takes scan jobs from Redis, runs them with the sandboxed browser and streams progress.

    python worker.py

Run as many as needed (docker compose up --scale worker=N); each runs WORKER_CONCURRENCY scans at once.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket

import db
import jobs
import render
import store
from scanner import ScanError, scan

log = logging.getLogger("artemis.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "4"))
SCAN_TIMEOUT = 45.0
STUB_SCANS = os.environ.get("ARTEMIS_STUB_SCANS") == "1"   # load tests only: no real site is contacted


async def stub_scan(target: str, progress=None) -> dict:
    """Stands in for a real scan during load tests: similar timing, no network."""
    for step in ("resolve", "certificate", "email", "records", "page", "impersonation"):
        await asyncio.sleep(0.3)
        if progress is not None:
            await progress(step, "ok")
    return {"domain": target, "resolves": True, "risk": {"score": 10, "label": "Low"},
            "impersonation": {"verdict": "Load test"}, "payment": None}


def record_history(user_id: int, target: str, report: dict) -> None:
    risk = report["risk"]
    verdict = (report.get("impersonation") or report["payment"])["verdict"]
    db.add_scan(user_id, target, risk and risk["score"], risk and risk["label"], verdict)


async def run_job(r, job_id: str, fields: dict) -> None:
    """Run one scan job and record how it ended. Shared by the worker and the API's inline mode."""
    if await jobs.start(r, job_id) > jobs.MAX_ATTEMPTS:
        await jobs.fail(r, job_id, "The scan failed. Try again.", 500)
        return

    async def progress(step: str, status: str) -> None:
        await jobs.publish(r, job_id, {"type": "step", "step": step, "status": status})

    run = stub_scan if STUB_SCANS else scan
    try:
        report = await asyncio.wait_for(run(fields["target"], progress=progress), SCAN_TIMEOUT)
    except ScanError as exc:
        await jobs.fail(r, job_id, str(exc), 400)
        return
    except asyncio.TimeoutError:
        await jobs.fail(r, job_id, "The scan timed out.", 504)
        return
    except Exception:
        log.exception("Scan %s failed", job_id)
        await jobs.fail(r, job_id, "The scan failed. Try again.", 500)
        return
    await jobs.finish(r, job_id, report, fields["cache_key"])
    if fields.get("user_id"):
        await asyncio.to_thread(record_history, int(fields["user_id"]), fields["target"], report)


async def serve(stop: asyncio.Event | None = None) -> None:
    r = store.async_client()
    await jobs.ensure_group(r)
    stop = stop or asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):   # Windows, or not the main thread
            pass
    renderer_error = None if STUB_SCANS else await render.self_test()
    if renderer_error:
        log.error("Headless browser self-test failed: %s", renderer_error)
    slots = asyncio.Semaphore(CONCURRENCY)
    running: set[asyncio.Task] = set()

    async def heartbeat() -> None:
        while True:
            await jobs.heartbeat(r, WORKER_ID, renderer_error)
            await asyncio.sleep(15)

    async def handle(entry_id: str, fields: dict) -> None:
        try:
            await run_job(r, fields["job"], fields)
        finally:
            await jobs.ack(r, entry_id)
            slots.release()

    beat = asyncio.create_task(heartbeat())
    log.info("Worker %s ready, %d scans at once", WORKER_ID, CONCURRENCY)
    try:
        while not stop.is_set():
            await slots.acquire()
            claimed = await jobs.claim(r, WORKER_ID, block_ms=1000)
            if claimed is None:
                slots.release()
                await asyncio.sleep(0.05)   # the in-memory Redis used in tests returns at once instead of waiting
                continue
            task = asyncio.create_task(handle(*claimed))
            running.add(task)
            task.add_done_callback(running.discard)
        await asyncio.gather(*running)   # finish the scans already started
    finally:
        beat.cancel()
        await r.delete(f"workers:{WORKER_ID}")
        await render.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # httpx logs every request at INFO, which would write the sites people scan into the container log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    db.init()
    asyncio.run(serve())
