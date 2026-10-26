"""Build or extend the labelled evaluation dataset (evaluation/data/dataset.jsonl).

    python evaluation/collect.py phishing              add new links from the OpenPhish public feed
    python evaluation/collect.py phishing --file x.txt  add phishing links from a text file (one per line)
    python evaluation/collect.py genuine --count 500    add genuine sites from the Tranco popular-sites list

The OpenPhish feed holds only about 300 current links, so run the phishing command every few hours to
build up a larger set. Phishing sites go offline quickly: scan new entries soon after collecting them.

Each line of the dataset is {"url", "label": "phishing" | "genuine", "source", "added"}. Links already in
the dataset are skipped, and at most --per-site links are kept for any one registrable domain, so a single
campaign can't dominate the results.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from impersonation import OPENPHISH_FEED, registrable_domain  # noqa: E402
from scanner import ScanError, normalize_domain  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
DATASET = DATA / "dataset.jsonl"
TRANCO = "https://tranco-list.eu/top-1m.csv.zip"


def load() -> list[dict]:
    if not DATASET.exists():
        return []
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def site_of(url: str) -> str | None:
    try:
        return registrable_domain(normalize_domain(url))
    except ScanError:
        return None


def append(rows: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    with DATASET.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def add(candidates: list[str], label: str, source: str, per_site: int) -> int:
    existing = load()
    seen_urls = {r["url"] for r in existing}
    per = {}
    other_label_sites = set()
    for r in existing:
        s = site_of(r["url"])
        per[(s, r["label"])] = per.get((s, r["label"]), 0) + 1
        if r["label"] != label:
            other_label_sites.add(s)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for url in candidates:
        url = url.strip()
        site = site_of(url)
        if not url or url in seen_urls or site is None:
            continue
        if site in other_label_sites:      # a site can't be both; leave it out rather than guess
            continue
        if per.get((site, label), 0) >= per_site:
            continue
        per[(site, label)] = per.get((site, label), 0) + 1
        seen_urls.add(url)
        rows.append({"url": url, "label": label, "source": source, "added": now})
    append(rows)
    return len(rows)


def phishing(args) -> None:
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8", errors="replace").splitlines()
        source = Path(args.file).name
    else:
        lines = httpx.get(OPENPHISH_FEED, timeout=30).raise_for_status().text.splitlines()
        source = "openphish"
    added = add([l for l in lines if l.startswith(("http://", "https://"))], "phishing", source, args.per_site)
    print(f"added {added} phishing links from {source}")


def genuine(args) -> None:
    raw = httpx.get(TRANCO, timeout=120, follow_redirects=True).raise_for_status().content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        rows = z.read(z.namelist()[0]).decode().splitlines()
    domains = [line.split(",", 1)[1] for line in rows if "," in line]
    rng = random.Random(args.seed)
    # half from the most popular sites (mostly big brands), half from further down the list, where
    # ordinary genuine sites are that Artemis has never heard of: that's where false alarms show up
    top = domains[:1000]
    rest = domains[1000:100_000]
    half = args.count // 2
    picks = rng.sample(top, min(half, len(top))) + rng.sample(rest, args.count - half)
    added = add([f"https://{d}/" for d in picks], "genuine", "tranco", args.per_site)
    print(f"added {added} genuine sites from Tranco")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("phishing")
    p.add_argument("--file", help="text file of phishing links, one per line")
    p.add_argument("--per-site", type=int, default=3)
    g = sub.add_parser("genuine")
    g.add_argument("--count", type=int, default=500)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--per-site", type=int, default=1)
    args = ap.parse_args()
    {"phishing": phishing, "genuine": genuine}[args.cmd](args)
    rows = load()
    print(f"dataset: {sum(r['label'] == 'phishing' for r in rows)} phishing, "
          f"{sum(r['label'] == 'genuine' for r in rows)} genuine")


if __name__ == "__main__":
    main()
