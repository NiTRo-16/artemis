"""Domain watch: following a log, capped scans, the summary API and the line in scan results."""
import asyncio
import os
import time

import testenv  # noqa: F401
import httpx  # noqa: E402

os.environ["WATCH_PUBLIC"] = "1"
import ct_logs  # noqa: E402
import db  # noqa: E402
import impersonation  # noqa: E402
import jobs  # noqa: E402
import main  # noqa: E402
import store  # noqa: E402
import watcher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from ct_fixture import leaf  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


NOW_MS = int(time.time() * 1000)
BASE = "https://log.test/"
served = {"size": 0, "ts": NOW_MS, "fail": 0, "names": ["hdfcbank-kyc.xyz", "www.gardening-tips.org"]}


def handler(request):
    if served["fail"]:
        return httpx.Response(429)
    if request.url.path == "/checkpoint":
        return httpx.Response(200, text=f"log.test\n{served['size']}\nroot=\n\nsig\n")
    return httpx.Response(200, content=leaf(served["names"], ts=served["ts"]) * ct_logs.TILE_ENTRIES)


async def following():
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        served["size"] = 1000
        ok("first run reads nothing", await watcher.read_log(client, "t", BASE) is False)
        ok("first run starts at the end of the log, on a tile edge", db.watch_log("t")["position"] == 768)
        ok("nothing stored yet", db.watch_first_seen("hdfcbank-kyc.xyz") is None)

        served["size"] = 1100
        await watcher.read_log(client, "t", BASE)
        state = db.watch_log("t")
        ok("reads a new complete tile", state["position"] == 1024 and state["entries_read"] == 256)
        ok("stores the match", db.watch_first_seen("hdfcbank-kyc.xyz") is not None)
        with db.pool().connection() as c:
            ok("stores one row, not the innocent name",
               c.execute("SELECT count(*) AS n FROM watch_domains").fetchone()["n"] == 1)

        served["size"] = 1100
        await watcher.read_log(client, "t", BASE)
        ok("restart or quiet log: position kept", db.watch_log("t")["position"] == 1024)

        served["fail"] = 1
        try:
            await watcher.read_log(client, "t", BASE)
            ok("rate limit raises for backoff", False)
        except httpx.HTTPStatusError:
            ok("rate limit raises for backoff", True)
        served["fail"] = 0
        ok("position unchanged after failure", db.watch_log("t")["position"] == 1024)

        served["size"] = 1024 + 256 * 40
        served["ts"] = NOW_MS - 2 * 3600 * 1000
        await watcher.read_log(client, "t", BASE)
        state = db.watch_log("t")
        ok("over an hour behind: jumps to the end", state["position"] == 1024 + 256 * 40)
        ok("records the gap", state["gaps"] == 1 and state["last_gap"] is not None)

asyncio.run(following())

# ---------- outcomes ----------
form = {"resolves": True, "impersonation": {"level": "likely", "facts": {"page": {"credential_form": "password"}}}}
ok("outcome: offline", watcher.scan_outcome({"resolves": False}) == "offline")
ok("outcome: form", watcher.scan_outcome(form) == "login_or_card_form")
ok("outcome: on a blocklist", watcher.scan_outcome({"resolves": True, "impersonation": {"level": "reported", "facts": {"page": None}}}) == "flagged")
ok("outcome: high score alone is not flagged", watcher.scan_outcome({"resolves": True, "impersonation": {"level": "likely", "facts": {"page": {"credential_form": None}}}}) == "no_form")


# ---------- capped scans ----------
def add(name, brand="HDFC Bank", age=3600):
    db.add_watch_domains([{"registrable": name, "brand": brand, "reason": "r", "host": "www." + name, "log": "t",
                           "first_seen": int(time.time()) - age}])


async def scans():
    r = store.async_client()
    await jobs.ensure_group(r)
    now = int(time.time())
    with db.pool().connection() as c:
        c.execute("DELETE FROM watch_domains")
    add("fresh-hdfcbank.xyz", age=60)
    ok("too new: not scanned yet", await watcher.queue_one_scan(r, now) is False)

    add("older-hdfcbank.xyz")
    ok("due: queued", await watcher.queue_one_scan(r, now) is True)
    row = db.watch_scans_running()
    ok("one scan running, with the full host", len(row) == 1 and row[0]["registrable"] == "older-hdfcbank.xyz")
    entry = (await r.xrange(jobs.QUEUE))[-1][1]
    ok("queued with no user, so in nobody's history", entry["target"] == "www.older-hdfcbank.xyz" and entry["user_id"] == "")
    ok("not queued twice", await watcher.queue_one_scan(r, now) is False)

    await jobs.finish(r, row[0]["scan_job"], form, "k")
    await watcher.settle_scans(r)
    ok("outcome saved", db.watch_scans_running() == [] and db.watch_outcomes()["login_or_card_form"] == 1)

    add("busy-hdfcbank.xyz")
    for i in range(watcher.BUSY_QUEUE):
        await r.xadd(jobs.QUEUE, {"job": "x", "target": "x", "cache_key": "x", "user_id": ""})
    ok("pauses while the queue is busy", await watcher.queue_one_scan(r, now) is False)
    await r.delete(jobs.QUEUE)
    await jobs.ensure_group(r)

    cap = watcher.SCANS_A_DAY
    watcher.SCANS_A_DAY = 1
    ok("daily cap holds", await watcher.queue_one_scan(r, now) is False)
    watcher.SCANS_A_DAY = cap

    flood = watcher.BRAND_FLOOD
    watcher.BRAND_FLOOD = 1
    add("flood-paytm-a.xyz", "Paytm")
    add("flood-paytm-b.xyz", "Paytm")
    with db.pool().connection() as c:
        c.execute("DELETE FROM watch_domains WHERE brand = 'HDFC Bank' AND outcome IS NULL")
    ok("a flooding brand isn't scanned", await watcher.queue_one_scan(r, now) is False)
    watcher.BRAND_FLOOD = flood

    with db.pool().connection() as c:
        c.execute("DELETE FROM watch_domains WHERE outcome IS NULL AND scan_job IS NULL")
    add("newer-google.xyz", "Google", age=700)
    add("older-paytm.xyz", "Paytm", age=5000)
    ok("Indian brands are scanned first, even if older", await watcher.queue_one_scan(r, now) is True
       and db.watch_scans_running()[-1]["registrable"] == "older-paytm.xyz")
    with db.pool().connection() as c:
        c.execute("DELETE FROM watch_domains WHERE outcome IS NULL")

    add("stale-hdfcbank.xyz", age=watcher.GIVE_UP_AFTER + 60)
    db.expire_watch_scans(now - watcher.GIVE_UP_AFTER)
    ok("not reached in 48 hours: marked not checked", db.watch_outcomes().get("not_checked") == 1)

    add("ancient-hdfcbank.xyz", age=watcher.KEEP_SECONDS + 60)
    db.purge_watch_domains(now - watcher.KEEP_SECONDS)
    ok("deleted after 90 days", db.watch_first_seen("ancient-hdfcbank.xyz") is None)
    await r.delete("watch:summary")

asyncio.run(scans())

# ---------- summary API ----------
client = TestClient(main.app)
with client:
    with db.pool().connection() as c:
        c.execute("UPDATE watch_logs SET started = %s", (int(time.time()) - 3 * 86400,))
    resp = client.get("/api/watch/summary")
    data = resp.json()
    ok("summary answers", resp.status_code == 200 and data["public"] is True)
    hdfc = next(b for b in data["brands"] if b["brand"] == "HDFC Bank")
    ok("counts per brand", hdfc["matches"] >= 2 and hdfc["forms"] == 1)
    ok("brands with no matches show zero", next(b for b in data["brands"] if b["brand"] == "Visa")["matches"] == 0)
    ok("most matches first", data["brands"][0]["matches"] >= data["brands"][-1]["matches"])
    ok("no domain name anywhere", "hdfcbank" not in resp.text and ".xyz" not in resp.text)
    ok("names the logs read", any("Sycamore" in name for name in data["logs"]))
    ok("reports the gap", data["last_gap"] is not None and data["stopped"] is False and data["just_started"] is False)

    store.sync_client().delete("watch:summary")
    with db.pool().connection() as c:
        c.execute("UPDATE watch_logs SET last_read = %s, started = %s", (int(time.time()) - 2 * 3600, int(time.time()) - 3600))
    data = client.get("/api/watch/summary").json()
    ok("says when reading stopped, and that it just started", data["stopped"] is True and data["just_started"] is True)

    cached = client.get("/api/watch/summary").json()
    ok("cached", cached == data)

    main.WATCH_PUBLIC = False
    store.sync_client().delete("watch:summary")
    resp = client.get("/api/watch/summary")
    ok("before opening: says nothing but that", resp.json() == {"public": False})
    main.WATCH_PUBLIC = True

# ---------- line in scan results ----------
records = {"registration": None, "certificate": None, "lists": []}
plain = impersonation.assess("hdfcbank-kyc.xyz", records)
day = "2026-10-30"
marked = impersonation.assess("hdfcbank-kyc.xyz", {**records, "watch_first_seen": 1793318400})
line = [s for s in marked["signals"] if "public logs" in s["text"]]
ok("line appears for a watched domain", len(line) == 1 and "30 October 2026" in line[0]["text"] and line[0]["tone"] == "info")
ok("adds no risk points", marked["points"] == plain["points"] and marked["level"] == plain["level"])
ok("no line otherwise", not any("public logs" in s["text"] for s in plain["signals"]))
ok("warnings summary is unchanged", marked["summary"] == plain["summary"])

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
