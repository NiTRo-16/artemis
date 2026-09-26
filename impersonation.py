"""Signals that a domain is pretending to be someone else.

Uses only public data: the domain name itself, registration records (RDAP),
certificate transparency logs, and phishing/malware blocklists.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
import tldextract

from brands import BRANDS

OPENPHISH_FEED = "https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt"
FEED_TTL = 1800            # seconds between feed refreshes
FEED_RETRY = 300           # retry sooner after a failed refresh
CRTSH_MAX_BYTES = 5_000_000
RISKY_TLDS = {"xyz", "top", "icu", "buzz", "click", "link", "rest", "cyou", "sbs", "cfd", "monster",
              "tk", "ml", "ga", "cf", "gq", "zip", "mov", "support", "live", "online", "site", "shop"}

# Characters that read like Latin letters, mapped to what they imitate.
CONFUSABLES = {
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a", "|": "l", "i": "l",
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "ё": "e", "і": "l", "ј": "j", "к": "k", "м": "m", "н": "h", "о": "o",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s", "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "l", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "ω": "w",
    # Armenian and other lookalikes
    "օ": "o", "ս": "u", "ց": "g", "ո": "n", "ɡ": "g", "ɑ": "a", "ı": "l",
}
MULTI_CHAR = (("rn", "m"), ("vv", "w"))
TONE_ORDER = {"red": 0, "amber": 1, "green": 2, "info": 3}

_extract = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)
_feed: dict = {"hosts": set(), "links": set(), "next_refresh": 0.0}
# Link shorteners: anyone can create links on them, so a host-level blocklist match isn't meaningful.
SHARED_LINK_SERVICES = {"tinyurl.com", "bit.ly", "alturl.com", "t.co", "is.gd", "cutt.ly", "rb.gy", "ow.ly",
                        "shorturl.at", "rebrand.ly", "t.ly", "tiny.cc", "s.id", "shorturl.com", "v.gd", "qrco.de"}
_feed_lock = asyncio.Lock()


# ---------- name analysis ----------

def skeleton(text: str) -> str:
    """Reduce a name to what it looks like, so `pаypa1` and `paypal` compare equal."""
    text = unicodedata.normalize("NFKC", text.lower())
    text = "".join(CONFUSABLES.get(ch, ch) for ch in text)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    for pair, single in MULTI_CHAR:
        text = text.replace(pair, single)
    return text


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance that also counts a swap of neighbouring letters as one edit."""
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def decode_label(label: str) -> str:
    try:
        return label.encode("ascii").decode("idna") if label.startswith("xn--") else label
    except UnicodeError:
        return label


def registrable_domain(host: str) -> str:
    """The part of a hostname its owner registered, e.g. mail.google.com -> google.com."""
    parts = _extract(host)
    return f"{parts.domain}.{parts.suffix}" if parts.suffix else host


def official_brand(registrable: str) -> str | None:
    # Compare the registrable domain only: user-content hosts like foo.blogspot.com or
    # foo.github.io are their own registrable domains under the public suffix list.
    for name, _, domains in BRANDS:
        if registrable in domains:
            return name
    return None


def brand_lookalike(label: str, subdomain: str) -> tuple[int, str, str] | None:
    """Return (points, reason, brand name) for the closest brand the name imitates, if any."""
    shown = decode_label(label)
    label_skel = skeleton(shown)
    label_tokens = set(re.split(r"[^a-z]+", label_skel)) - {""}
    sub_tokens = set(re.split(r"[^a-z]+", skeleton(subdomain))) - {""}
    best = None
    for name, keywords, _ in BRANDS:
        for kw in keywords:
            kw_skel = skeleton(kw)
            if label_skel == kw_skel:
                hit = (40, f"Uses the {name} name on a domain {name} doesn't own", name) if shown == kw else \
                      (55, f"Spelled with lookalike characters to read as “{kw}” ({name})", name)
            elif len(kw) >= 5 and 0 < edit_distance(label_skel, kw_skel) <= (1 if len(kw) < 9 else 2):
                hit = (35, f"One or two typos away from “{kw}” ({name})", name)
            elif kw_skel in label_tokens or (len(kw) >= 6 and kw_skel in label_skel):
                hit = (35, f"Contains the brand name “{kw}” ({name})", name)
            elif kw_skel in sub_tokens:
                hit = (40, f"Puts “{kw}” in a subdomain so the address starts like {name}'s", name)
            else:
                continue
            if best is None or hit[0] > best[0]:
                best = hit
    return best


def mixed_scripts(label: str) -> bool:
    shown = decode_label(label)
    scripts = {unicodedata.name(ch, "").split(" ")[0] for ch in shown if ch.isalpha()}
    return len(scripts) > 1


# ---------- public records ----------

def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def registration(client: httpx.AsyncClient, registrable: str) -> dict | None:
    try:
        resp = await client.get(f"https://rdap.org/domain/{registrable}", headers={"Accept": "application/rdap+json"})
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
    registrar = None
    for entity in data.get("entities", []):
        if "registrar" in entity.get("roles", []):
            for entry in (entity.get("vcardArray") or [None, []])[1]:
                if entry and entry[0] == "fn":
                    registrar = entry[3]
    return {"registered": parse_date(events.get("registration")), "registrar": registrar}


async def earliest_certificate(client: httpx.AsyncClient, registrable: str) -> dict | None:
    """Earliest certificate in CT logs. Cert Spotter's free tier covers roughly the last year;
    crt.sh has full history but is often overloaded, so it's the fallback."""
    try:
        resp = await client.get("https://api.certspotter.com/v1/issuances", params={"domain": registrable})
        if resp.status_code == 200:
            issued = [parse_date(i.get("not_before")) for i in resp.json()]
            issued = [d for d in issued if d]
            return {"first": min(issued) if issued else None, "count": len(issued), "source": "Cert Spotter"}
    except (httpx.HTTPError, ValueError):
        pass

    try:
        async with client.stream("GET", "https://crt.sh/", params={"q": registrable, "output": "json"}) as resp:
            if resp.status_code != 200:
                return None
            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > CRTSH_MAX_BYTES:
                    return {"first": None, "count": None, "extensive": True, "source": "crt.sh"}
        issued = [parse_date(e.get("not_before")) for e in json.loads(body)]
        issued = [d for d in issued if d]
        return {"first": min(issued) if issued else None, "count": len(issued), "source": "crt.sh"}
    except (httpx.HTTPError, ValueError):
        return None


# ---------- blocklists ----------

def link_key(url: str) -> str | None:
    """Compare links ignoring scheme, www., trailing slash and #fragment."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.hostname:
        return None
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.hostname.removeprefix('www.')}{parts.path.rstrip('/')}{query}"


async def openphish_feed(client: httpx.AsyncClient) -> dict | None:
    """{"hosts": set, "links": set} from the OpenPhish feed, refreshed every FEED_TTL seconds."""
    async with _feed_lock:
        if time.monotonic() >= _feed["next_refresh"]:
            try:
                resp = await client.get(OPENPHISH_FEED)
                resp.raise_for_status()
                lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
                _feed["hosts"] = {urlsplit(line).hostname for line in lines} - {None}
                _feed["links"] = {link_key(line) for line in lines} - {None}
                _feed["next_refresh"] = time.monotonic() + FEED_TTL
            except httpx.HTTPError:
                _feed["next_refresh"] = time.monotonic() + FEED_RETRY
        return {"hosts": _feed["hosts"], "links": _feed["links"]} if _feed["hosts"] else None


async def openphish_hosts(client: httpx.AsyncClient) -> set[str] | None:
    feed = await openphish_feed(client)
    return feed["hosts"] if feed else None


async def check_openphish(client: httpx.AsyncClient, host: str, link: str | None = None) -> dict:
    feed = await openphish_feed(client)
    if feed is None:
        return {"name": "OpenPhish", "status": "error", "detail": "Feed unavailable"}
    if link and link_key(link) in feed["links"]:
        return {"name": "OpenPhish", "status": "listed", "detail": "This exact link is reported as phishing"}
    bare = host.removeprefix("www.")
    on_host = bare in feed["hosts"] or f"www.{bare}" in feed["hosts"]
    if on_host and registrable_domain(host) in SHARED_LINK_SERVICES:
        # Anyone can make links on these services; one bad link says nothing about the rest.
        return {"name": "OpenPhish", "status": "clean",
                "detail": "Link service with some reported links; only exact links count"}
    return {"name": "OpenPhish", "status": "listed" if on_host else "clean",
            "detail": "Active phishing URL on this host" if on_host
            else f"Not among {len(feed['hosts'])} active phishing hosts"}


async def check_safe_browsing(client: httpx.AsyncClient, host: str) -> dict:
    key = os.environ.get("SAFE_BROWSING_API_KEY")
    if not key:
        return {"name": "Google Safe Browsing", "status": "skipped", "detail": "Set SAFE_BROWSING_API_KEY to enable"}
    body = {
        "client": {"clientId": "artemis", "clientVersion": "0.2"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": f"http://{host}/"}, {"url": f"https://{host}/"}],
        },
    }
    try:
        resp = await client.post("https://safebrowsing.googleapis.com/v4/threatMatches:find",
                                 json=body, headers={"X-Goog-Api-Key": key})
        resp.raise_for_status()
        threats = sorted({m.get("threatType", "?") for m in resp.json().get("matches", [])})
    except (httpx.HTTPError, ValueError):
        return {"name": "Google Safe Browsing", "status": "error", "detail": "Lookup failed"}
    if threats:
        return {"name": "Google Safe Browsing", "status": "listed",
                "detail": "Flagged for " + ", ".join(t.replace("_", " ").lower() for t in threats)}
    return {"name": "Google Safe Browsing", "status": "clean", "detail": "No matches"}


async def check_urlhaus(client: httpx.AsyncClient, host: str) -> dict:
    key = os.environ.get("URLHAUS_AUTH_KEY")
    if not key:
        return {"name": "URLhaus", "status": "skipped", "detail": "Set URLHAUS_AUTH_KEY to enable"}
    try:
        resp = await client.post("https://urlhaus-api.abuse.ch/v1/host/", data={"host": host},
                                 headers={"Auth-Key": key})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {"name": "URLhaus", "status": "error", "detail": "Lookup failed"}
    online = [u for u in data.get("urls", []) if u.get("url_status") == "online"]
    if data.get("query_status") == "ok" and online:
        return {"name": "URLhaus", "status": "listed", "detail": f"{len(online)} active malware URL(s) on this host"}
    return {"name": "URLhaus", "status": "clean", "detail": "No active malware URLs"}


# ---------- verdict ----------

def age_text(days: int) -> str:
    if days < 60:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 730:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


def lookalike_brand(host: str) -> str | None:
    """Name of the brand this host's name imitates, or None (also None for the brand's own domains)."""
    parts = _extract(host)
    if official_brand(registrable_domain(host)):
        return None
    hit = brand_lookalike(parts.domain, parts.subdomain)
    return hit[2] if hit else None


async def lookup_records(host: str, link: str | None = None) -> dict:
    """Registration, certificate history and blocklist results for a host (and the exact link, if given)."""
    registrable = registrable_domain(host)
    # Only fixed third-party services are called here, never the scanned host, so redirects are safe to follow.
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True,
                                 headers={"User-Agent": "ArtemisScanner/0.2"}) as client:
        reg, cert, *lists = await asyncio.gather(
            registration(client, registrable),
            earliest_certificate(client, registrable),
            check_openphish(client, host, link),
            check_safe_browsing(client, host),
            check_urlhaus(client, host),
        )
    return {"registration": reg, "certificate": cert, "lists": lists}


async def check_impersonation(host: str, link: str | None = None) -> dict:
    """Impersonation verdict without the page (used when the site can't be loaded)."""
    return assess(host, await lookup_records(host, link))


def assess(host: str, records: dict, page_signals: list[dict] | None = None, page_facts: dict | None = None) -> dict:
    """Combine name, registration, blocklist and (optionally) page signals into one verdict."""
    parts = _extract(host)
    registrable = registrable_domain(host)
    now = datetime.now(timezone.utc)
    reg, cert, lists = records["registration"], records["certificate"], records["lists"]
    signals: list[dict] = list(page_signals or [])

    def signal(points: int, tone: str, text: str) -> None:
        signals.append({"points": points, "tone": tone, "text": text})

    brand = official_brand(registrable)
    if brand:
        signal(-100, "green", f"Official domain of {brand}")
    else:
        lookalike = brand_lookalike(parts.domain, parts.subdomain)
        if lookalike:
            signal(lookalike[0], "red" if lookalike[0] >= 50 else "amber", lookalike[1])
        if mixed_scripts(parts.domain):
            signal(25, "red", "Mixes letters from different alphabets, a common trick to fake a familiar name")
        elif parts.domain.startswith("xn--"):
            signal(5, "info", f"Uses non-Latin characters: {decode_label(parts.domain)}")
        if parts.suffix.split(".")[-1] in RISKY_TLDS:
            signal(5, "amber", f"Uses the .{parts.suffix} ending, which is popular for throwaway domains")

    registered = reg and reg["registered"]
    age_days = (now - registered).days if registered else None
    if age_days is None:
        signal(0, "info", "Registration date not published by the registry")
    elif age_days < 30:
        signal(30, "red", f"Registered only {age_text(age_days)}")
    elif age_days < 180:
        signal(15, "amber", f"Registered recently ({age_text(age_days)})")
    elif age_days >= 5 * 365:
        signal(-20, "green", f"Registered {age_text(age_days)} ({registered.year})")
    else:
        signal(0, "info", f"Registered {age_text(age_days)}")

    first_cert = cert and cert.get("first")
    cert_days = (now - first_cert).days if first_cert else None
    if cert_days is not None and cert_days < 30 and (age_days is None or age_days < 365):
        signal(10, "amber", f"First TLS certificate issued {age_text(cert_days)}")

    listed = [entry for entry in lists if entry["status"] == "listed"]
    for entry in reversed(listed):
        signals.insert(0, {"points": 0, "tone": "red", "text": f"{entry['name']}: {entry['detail']}"})
    signals.sort(key=lambda s: TONE_ORDER[s["tone"]])  # stable, so blocklist hits stay first among reds

    points = max(0, sum(s["points"] for s in signals))
    if listed and not brand:
        level, verdict = "reported", "Reported as malicious"
    elif brand:
        level, verdict = "official", f"Official {brand} domain"
    elif points >= 60:
        level, verdict = "likely", "Likely impersonation"
    elif points >= 25:
        level, verdict = "suspicious", "Suspicious"
    else:
        level, verdict = "clear", "No impersonation signs"

    warnings = [s["text"] for s in signals if s["tone"] in ("red", "amber")]
    summary = "; ".join(warnings[:2]) + "." if warnings and level != "official" else (
        "Nothing suggests this domain is pretending to be a known brand." if level == "clear"
        else f"{registrable} is on the list of domains {brand} owns.")

    return {
        "level": level,
        "verdict": verdict,
        "summary": summary,
        "points": points,
        "registrable": registrable,
        "signals": [{"tone": s["tone"], "text": s["text"]} for s in signals],
        "facts": {
            "registered": registered.date().isoformat() if registered else None,
            "registrar": reg and reg["registrar"],
            "first_certificate": first_cert.date().isoformat() if first_cert else None,
            "certificate_source": cert and cert.get("source"),
            "page": page_facts,
        },
        "lists": lists,
    }
