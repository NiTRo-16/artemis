"""Domain watch: reads certificate logs, stores names that copy a brand, and has each scanned once.

    python watcher.py

Runs as one process. WATCH_SCANS=1 turns the capped scans on.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

import httpx

import ct_logs
import db
import jobs
import store
import watch_match

log = logging.getLogger("artemis.watcher")
SCANS_ON = os.environ.get("WATCH_SCANS") == "1"
BATCH_TILES = 16              # tiles fetched together
BEHIND_SECONDS = 3600         # further behind than this: jump to the end and record a gap
CAUGHT_UP_WAIT = 5.0
MAX_BACKOFF = 300.0
SCANS_A_DAY = 1000            # each scan calls crt.sh, RDAP and Safe Browsing, so this is the real limit
SCAN_AFTER = 600              # a certificate often comes before the site
GIVE_UP_AFTER = 48 * 3600
BUSY_QUEUE = 10               # people's scans come first
BRAND_FLOOD = 20_000          # a day for one brand: points to a bad rule (the busiest measured about 8,000)
KEEP_SECONDS = 90 * 24 * 3600
SCAN_TICK = 60.0


def find_matches(entries: list[ct_logs.Entry], log_name: str, now: int) -> dict[str, dict]:
    """Suspect domains in these entries, one per registrable domain."""
    found: dict[str, dict] = {}
    for entry in entries:
        for name in entry.names:
            hit = watch_match.match(name)
            if hit and hit.registrable not in found:
                found[hit.registrable] = {"registrable": hit.registrable, "brand": hit.brand, "reason": hit.reason,
                                          "host": hit.host, "log": log_name, "first_seen": now}
    return found


async def _tile(client: httpx.AsyncClient, base: str, index: int) -> bytes:
    resp = await client.get(f"{base}tile/data/{ct_logs.tile_path(index)}")
    resp.raise_for_status()
    return resp.content


async def read_log(client: httpx.AsyncClient, name: str, base: str) -> bool:
    """Read the next batch of one log. Returns True if there's more to read straight away."""
    resp = await client.get(base + "checkpoint")
    resp.raise_for_status()
    size = ct_logs.parse_checkpoint(resp.text)
    full_tiles = size // ct_logs.TILE_ENTRIES
    now = int(time.time())
    state = await asyncio.to_thread(db.watch_log, name)
    if state is None:   # first run: start from now, no backfill
        await asyncio.to_thread(db.start_watch_log, name, full_tiles * ct_logs.TILE_ENTRIES, now)
        return False
    next_tile = state["position"] // ct_logs.TILE_ENTRIES
    pending = full_tiles - next_tile
    if pending <= 0:
        await asyncio.to_thread(db.save_watch_log, name, state["position"], now, 0, 0)
        return False
    count = min(pending, BATCH_TILES)
    tiles = await asyncio.gather(*(_tile(client, base, next_tile + i) for i in range(count)))

    def work():
        entries, malformed = [], 0
        for data in tiles:
            got, bad = ct_logs.parse_tile(data)
            entries += got
            malformed += bad
        return entries, malformed, find_matches(entries, name, now)

    entries, malformed, found = await asyncio.to_thread(work)
    await asyncio.to_thread(db.add_watch_domains, list(found.values()))
    newest = max((e.timestamp_ms for e in entries), default=now * 1000) // 1000
    if pending > BATCH_TILES and newest < now - BEHIND_SECONDS:
        log.warning("%s is over an hour behind; skipping to the end and recording a gap", name)
        await asyncio.to_thread(db.save_watch_log, name, full_tiles * ct_logs.TILE_ENTRIES, now, len(entries), malformed, True)
        return False
    await asyncio.to_thread(db.save_watch_log, name, (next_tile + count) * ct_logs.TILE_ENTRIES, now, len(entries), malformed)
    return pending > count


async def follow_log(client: httpx.AsyncClient, name: str, base: str, stop: asyncio.Event) -> None:
    backoff = CAUGHT_UP_WAIT
    while not stop.is_set():
        try:
            more = await read_log(client, name, base)
            backoff = CAUGHT_UP_WAIT
            delay = 0.0 if more else CAUGHT_UP_WAIT
        except Exception as exc:   # the position is kept, so nothing is lost by trying again later
            backoff = min(backoff * 2, MAX_BACKOFF)
            delay = backoff
            log.warning("Reading %s failed, retrying in %.0f s: %s", name, delay, type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), delay)
        except asyncio.TimeoutError:
            pass


def scan_outcome(report: dict) -> str:
    """What one scan of a suspect domain found. The risk score isn't used: a new lookalike name alone scores high."""
    if report.get("resolves") is False:
        return "offline"
    impersonation = report.get("impersonation") or {}
    page = (impersonation.get("facts") or {}).get("page") or {}
    if page.get("credential_form"):
        return "login_or_card_form"
    return "flagged" if impersonation.get("level") == "reported" else "no_form"


async def settle_scans(r) -> None:
    for row in await asyncio.to_thread(db.watch_scans_running):
        state = await jobs.state(r, row["scan_job"])
        if state is None:
            outcome = "not_checked"
        elif state["status"] == "done":
            outcome = scan_outcome(state["report"])
        elif state["status"] == "error":
            outcome = "not_checked"
        else:
            continue
        await asyncio.to_thread(db.set_watch_outcome, row["registrable"], outcome)


async def queue_one_scan(r, now: int) -> bool:
    """Queue the next suspect domain due a scan (Indian brands first, then newest), unless the cap is reached or the queue is busy."""
    if await r.xlen(jobs.QUEUE) >= BUSY_QUEUE:
        return False
    if await asyncio.to_thread(db.watch_scans_since, now - 86400) >= SCANS_A_DAY:
        return False
    row = await asyncio.to_thread(db.next_watch_scan, now - SCAN_AFTER, now - 86400, BRAND_FLOOD, watch_match.INDIAN_BRANDS)
    if row is None:
        return False
    try:
        job_id, _ = await jobs.submit(r, row["host"], jobs.cache_key(row["host"], None), None)
    except jobs.QueueFull:
        return False
    await asyncio.to_thread(db.set_watch_scan, row["registrable"], job_id, now)
    return True


async def scan_tick(r) -> None:
    now = int(time.time())
    await settle_scans(r)
    await asyncio.to_thread(db.expire_watch_scans, now - GIVE_UP_AFTER)
    await asyncio.to_thread(db.purge_watch_domains, now - KEEP_SECONDS)
    if SCANS_ON:
        await queue_one_scan(r, now)


async def serve() -> None:
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):   # Windows
            pass
    r = store.async_client()
    await jobs.ensure_group(r)
    log.info("Watcher ready, reading %d logs, capped scans %s", len(ct_logs.LOGS), "on" if SCANS_ON else "off")

    async def scanning() -> None:
        while not stop.is_set():
            try:
                await scan_tick(r)
            except Exception:
                log.exception("Scan tick failed")
            try:
                await asyncio.wait_for(stop.wait(), SCAN_TICK)
            except asyncio.TimeoutError:
                pass

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={"User-Agent": ct_logs.USER_AGENT}) as client:
        await asyncio.gather(scanning(), *(follow_log(client, name, url, stop) for name, url, _ in ct_logs.LOGS))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    db.init()
    asyncio.run(serve())
