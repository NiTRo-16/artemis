"""Signs that a page copies a known brand's page, usually to collect logins or card details.

Works on page features read from the downloaded HTML and, when available, from the page as
rendered by a headless browser (render.py), plus the page's favicon. The brand's own favicons
are fetched from its official domains for comparison.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from brands import BRANDS
from impersonation import lookalike_brand, official_brand, registrable_domain

MAX_ICON_BYTES = 200_000
BRAND_ICON_TTL = 24 * 3600
IDENTITY_META = ("og:site_name", "og:title", "application-name", "twitter:title")
CARD_AUTOCOMPLETE = {"cc-number", "cc-csc", "cc-exp", "cc-exp-month", "cc-exp-year"}
CARD_FIELD = re.compile(r"card.?(num|no)|cc.?num|cvv|cvc|\bcsc\b|expir", re.IGNORECASE)

_brand_icons: dict[str, tuple[float, set[str]]] = {}   # brand name -> (fetched at, favicon sha256 hashes)

FetchAsset = Callable[[str], Awaitable[bytes | None]]


class PageParser(HTMLParser):
    """Collects the parts of a page that identify it and what it asks visitors to type."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.icons: list[str] = []
        self.resources: list[str] = []
        self.forms: list[dict] = []
        self._form: dict | None = None
        self._in_title = False
        # Fields outside any <form> are usually submitted by script; we can't see where they go.
        self.loose = {"action": None, "password": False, "card": False, "loose": True}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {key.lower(): (value or "") for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in IDENTITY_META:
                self.meta[key] = a.get("content", "")[:200]
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower().split()
            if any("icon" in r for r in rel):
                self.icons.append(a["href"])
            if "stylesheet" in rel or any("icon" in r for r in rel):
                self.resources.append(a["href"])
        elif tag in ("img", "script") and a.get("src"):
            self.resources.append(a["src"])
        elif tag == "form":
            self._form = {"action": a.get("action"), "password": False, "card": False, "loose": False}
            self.forms.append(self._form)
        elif tag == "input":
            target = self._form if self._form is not None else self.loose
            if a.get("type", "").lower() == "password":
                target["password"] = True
            hints = " ".join(a.get(k, "") for k in ("name", "id", "placeholder"))
            if a.get("autocomplete", "").lower() in CARD_AUTOCOMPLETE or CARD_FIELD.search(hints):
                target["card"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "form":
            self._form = None

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 300:
            self.title += data


def brand_terms(name: str, keywords: list[str]) -> set[str]:
    terms = {kw.lower() for kw in keywords} | {part.strip().lower() for part in name.split("/")}
    return {t for t in terms if len(t) >= 3}


def claimed_brands(identity_text: str) -> list[str]:
    """Brands the page names in its title or site-name tags, in BRANDS order."""
    text = identity_text.lower()
    found = []
    for name, keywords, _ in BRANDS:
        if any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) for term in brand_terms(name, keywords)):
            found.append(name)
    return found


def brand_domains(name: str) -> list[str]:
    return next(domains for brand, _, domains in BRANDS if brand == name)


def icon_hash(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data else None


def data_uri_bytes(uri: str) -> bytes | None:
    header, _, payload = uri.partition(",")
    if ";base64" not in header.lower():
        return None
    try:
        return base64.b64decode(payload, validate=False)[:MAX_ICON_BYTES]
    except (binascii.Error, ValueError):
        return None


async def official_icon_hashes(name: str) -> set[str]:
    """SHA-256 of /favicon.ico on the brand's first few official domains, cached for a day."""
    cached = _brand_icons.get(name)
    if cached and time.monotonic() - cached[0] < BRAND_ICON_TTL:
        return cached[1]
    # Official brand domains are a fixed list, so following their redirects is safe.
    async with httpx.AsyncClient(timeout=6.0, follow_redirects=True,
                                 headers={"User-Agent": "ArtemisScanner/0.2"}) as client:
        async def one(domain: str) -> str | None:
            try:
                resp = await client.get(f"https://{domain}/favicon.ico")
            except httpx.HTTPError:
                return None
            ok = resp.status_code == 200 and 0 < len(resp.content) <= MAX_ICON_BYTES
            return icon_hash(resp.content) if ok else None

        hashes = set(await asyncio.gather(*(one(d) for d in brand_domains(name)[:3]))) - {None}
    if hashes:
        _brand_icons[name] = (time.monotonic(), hashes)
    return hashes


@dataclass
class PageFeatures:
    """What the clone check needs from a page, whether read from HTML or from a rendered page."""
    url: str
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    icons: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)   # {"action": str | None, "password": bool, "card": bool}
    rendered: bool = False


def parse_html(html: str, page_url: str) -> PageFeatures:
    parser = PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:   # malformed markup shouldn't break the scan; use whatever was parsed
        pass
    loose = [parser.loose] if parser.loose["password"] or parser.loose["card"] else []
    return PageFeatures(page_url, parser.title.strip(), parser.meta, parser.icons, parser.resources,
                        parser.forms + loose)


def credential_forms(features: PageFeatures | None) -> list[dict]:
    return [f for f in features.forms if f["password"] or f["card"]] if features else []


def merge(static: PageFeatures | None, rendered: PageFeatures | None) -> PageFeatures | None:
    """Rendered page wins for identity (scripts can change the title); forms and resources are combined."""
    if not static or not rendered:
        return rendered or static
    return PageFeatures(
        url=rendered.url,
        title=rendered.title or static.title,
        meta={**static.meta, **rendered.meta},
        icons=rendered.icons + static.icons,
        resources=[urljoin(static.url, r) for r in static.resources] + rendered.resources,
        forms=[{**f, "action": urljoin(static.url, f["action"]) if f["action"] else None} for f in static.forms]
              + rendered.forms,
        rendered=True,
    )


async def check_clone(host: str, features: PageFeatures, fetch_asset: FetchAsset,
                      static: PageFeatures | None = None) -> tuple[list[dict], dict]:
    """Return (signals, facts) about whether the page imitates a known brand.

    `static` is the page as read from its HTML alone; it's used to report whether a login form
    only appeared after the page's scripts ran.
    """
    page_url = features.url
    site = registrable_domain(host)
    creds = credential_forms(features)
    asks_card = any(f["card"] for f in creds)
    asks_for = "card details" if asks_card else "a password"

    offsite_targets = []
    for form in creds:
        action = (form["action"] or "").strip()
        if not action or action.lower().startswith(("javascript:", "#")):
            continue
        target = urljoin(page_url, action)
        target_host = urlsplit(target).hostname or ""
        if target.startswith(("http://", "https://")) and target_host and registrable_domain(target_host) != site:
            offsite_targets.append(target_host)

    identity = " ".join([features.title, *features.meta.values()])
    claimed = claimed_brands(identity)
    facts = {
        "brands_named": claimed,
        "credential_form": ("card" if asks_card else "password") if creds else None,
        "form_target": offsite_targets[0] if offsite_targets else None,
        "rendered": features.rendered,
        "form_built_by_script": bool(creds) and features.rendered and not credential_forms(static),
    }
    if official_brand(site):
        return [], facts

    signals: list[dict] = []

    def signal(points: int, tone: str, text: str) -> None:
        signals.append({"points": points, "tone": tone, "text": text})

    imitated = lookalike_brand(host)
    candidates = list(dict.fromkeys(claimed + ([imitated] if imitated else [])))
    # Naming a brand is harmless on its own (reviews, guides, recipes); it matters combined with a login form.
    if claimed:
        signal(5, "info", f"Page title or site name mentions {' / '.join(claimed[:2])}")

    if creds and claimed:
        signal(40, "red", f"Asks for {asks_for} on a page that presents itself as {claimed[0]}")
    elif creds and imitated:
        signal(40, "red", f"Asks for {asks_for} on a site whose name imitates {imitated}")
    if offsite_targets:
        signal(30 if candidates else 25, "red" if candidates else "amber",
               f"Form sends what you type to a different site: {offsite_targets[0]}")

    if creds and candidates:
        official = {d for b in candidates for d in brand_domains(b)}
        hotlinked = sorted({registrable_domain(urlsplit(urljoin(page_url, r)).hostname or "")
                            for r in features.resources} & official)
        if hotlinked:
            signal(15, "amber", f"Loads images or scripts straight from {candidates[0]}'s servers ({hotlinked[0]})")

    if candidates:
        href = next((h for h in features.icons if h.strip()), "/favicon.ico").strip()
        page_icon = data_uri_bytes(href) if href.lower().startswith("data:") else await fetch_asset(urljoin(page_url, href))
        page_hash = icon_hash(page_icon)
        for name in candidates[:2]:
            if page_hash and page_hash in await official_icon_hashes(name):
                signal(40, "red", f"Uses {name}'s own favicon")
                break

    return signals, facts
