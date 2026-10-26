"""Scan the evaluation dataset with the real Artemis scanner and save every result.

    python evaluation/run.py                  scan everything not scanned yet, newest first
    python evaluation/run.py --limit 50       stop after 50 new scans (a quick trial)

Results go to evaluation/data/results.jsonl, one line per scan, with what report.py needs and what a
future model can learn from. A run can be stopped and started again; links already scanned are skipped.

Run it on a server or virtual machine if you can: it loads live phishing pages (in Artemis's sandboxed
browser) from your network.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render  # noqa: E402
from scanner import scan  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
DATASET = DATA / "dataset.jsonl"
RESULTS = DATA / "results.jsonl"
SCAN_TIMEOUT = 45.0


def summarise(row: dict, report: dict, seconds: float) -> dict:
    imp = report["impersonation"]
    risk = report.get("risk")
    pay = report.get("payment")
    return {
        **row,
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(seconds, 1),
        "online": bool(report.get("resolves")) and risk is not None,
        "risk_score": risk and risk["score"],
        "risk_label": risk and risk["label"],
        "imp_level": imp["level"],
        "imp_points": imp["points"],
        "signals": imp["signals"],
        "facts": imp["facts"],
        "lists": imp["lists"],
        "payment_level": pay and pay["level"],
        "payment_signals": pay and pay["signals"],
        "allowed": report["visit"]["allowed"],
        "failed_criteria": [c["text"] for c in report["visit"]["criteria"] if not c["passed"]],
        "grades": {c["key"]: c["score"] for c in report.get("categories", [])},
        "findings": [f["title"] for f in report.get("findings", [])],
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="at most this many new scans")
    ap.add_argument("--workers", type=int, default=6, help="scans at the same time")
    args = ap.parse_args()
    if not DATASET.exists():
        sys.exit("No dataset yet. Run evaluation/collect.py first.")
    rows = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]
    done = set()
    if RESULTS.exists():
        done = {json.loads(l)["url"] for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()}
    rows.sort(key=lambda r: r["added"], reverse=True)   # newest first: phishing sites go offline fast
    by_label = {}
    for r in rows:
        if r["url"] not in done:
            by_label.setdefault(r["label"], []).append(r)
    todo = []                                            # alternate labels so a --limit trial is balanced
    queues = list(by_label.values())
    while any(queues):
        for q in queues:
            if q:
                todo.append(q.pop(0))
    todo = todo[:args.limit]
    print(f"{len(done)} already scanned, {len(todo)} to scan")

    slots, lock, count = asyncio.Semaphore(args.workers), asyncio.Lock(), 0

    async def one(row):
        nonlocal count
        async with slots:
            started = time.monotonic()
            try:
                line = summarise(row, await asyncio.wait_for(scan(row["url"]), SCAN_TIMEOUT),
                                 time.monotonic() - started)
            except Exception as exc:   # every outcome is recorded, including errors and timeouts
                line = {**row, "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "error": f"{type(exc).__name__}: {exc}"[:200]}
            async with lock:
                with RESULTS.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(line) + "\n")
                count += 1
                if count % 10 == 0 or count == len(todo):
                    print(f"{count}/{len(todo)} scanned")

    try:
        await asyncio.gather(*(one(r) for r in todo))
    finally:
        await render.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
