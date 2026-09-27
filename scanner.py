"""Passive security checks for a public website.

Every check reads only what an ordinary visitor receives: the TLS handshake,
the homepage response headers, and public DNS records.
"""
from __future__ import annotations

import asyncio
import re
import socket
import ssl
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx

from clone import MAX_ICON_BYTES, check_clone, merge, parse_html
from netsafety import is_public_ip
from impersonation import assess, check_impersonation, lookup_records, same_owner
from payments import check_payment_page
from render import render_page

USER_AGENT = "ArtemisScanner/0.2 (passive checks)"
TIMEOUT = 8.0
MAX_REDIRECTS = 5
MAX_BODY = 1_000_000   # bytes of homepage HTML kept for the clone check
PUBLIC_RESOLVERS = ["1.1.1.1", "8.8.8.8"]
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z][a-z0-9-]{1,62}$")

WEIGHTS = {"tls": 30, "headers": 25, "email": 20, "cookies": 15, "disclosure": 10}
HIGH_RISK_FROM = 40  # risk scores from here up are "High"; lower scores are Low (<20) or Medium
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class ScanError(Exception):
    """A problem with the target that the user should see."""


class Unresolvable(ScanError):
    """The domain has no address records (never existed, or taken down)."""


@dataclass
class Finding:
    severity: str
    title: str
    location: str
    fix: str


@dataclass
class Category:
    key: str
    name: str
    score: int = 100
    notes: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def flag(self, penalty: int, severity: str, title: str, location: str, fix: str) -> None:
        self.score = max(0, self.score - penalty)
        self.findings.append(Finding(severity, title, location, fix))


@dataclass
class Page:
    url: str
    status: int
    headers: httpx.Headers
    cookies: list[str]
    body: str = ""   # HTML only, first MAX_BODY bytes


# ---------- target validation ----------

def normalize_domain(raw: str) -> str:
    text = raw.strip()
    try:
        host = urlsplit(text if "://" in text else f"//{text}").hostname or ""
        host = host.encode("idna").decode("ascii").rstrip(".").lower()
    except (UnicodeError, ValueError):
        host = ""
    if not DOMAIN_RE.match(host):
        raise ScanError("Enter a public domain or link, like example.com.")
    return host


def requested_path(raw: str) -> str | None:
    """Path and query from a pasted link (e.g. /account/verify.php?id=1), or None for a bare domain."""
    text = raw.strip()
    try:
        parts = urlsplit(text if "://" in text else f"//{text}")
    except ValueError:
        return None
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return path[:2000] if path not in ("", "/") else None


async def resolve_public(host: str) -> list[str]:
    """Resolve a host and refuse anything that points at a private or reserved network."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise Unresolvable(f"{host} does not resolve.")
    addrs = sorted({info[4][0].split("%")[0] for info in infos})
    if not addrs or not all(is_public_ip(a) for a in addrs):
        raise ScanError(f"{host} points to a private or reserved address, so it can't be scanned.")
    return addrs


# ---------- TLS ----------

def _tls_handshake(host: str, ip: str) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((ip, 443), timeout=TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                return {"ok": True, "cert": tls.getpeercert(), "version": tls.version()}
    except ssl.SSLCertVerificationError as exc:
        return {"ok": False, "reachable": True, "error": exc.verify_message or str(exc)}
    except OSError as exc:
        return {"ok": False, "reachable": False, "error": str(exc) or type(exc).__name__}


async def check_tls(host: str, ip: str) -> Category:
    cat = Category("tls", "TLS / HTTPS")
    result = await asyncio.to_thread(_tls_handshake, host, ip)
    if not result["ok"]:
        if result["reachable"]:
            cat.flag(100, "critical", "Certificate is not trusted", f"TLS: {result['error']}",
                     "Install a certificate from a public CA (e.g. Let's Encrypt) that covers this "
                     "hostname, and serve the full chain.")
        else:
            cat.flag(100, "critical", "HTTPS is not available", "Port 443",
                     "Serve the site over HTTPS with a valid certificate.")
        return cat

    cert, version = result["cert"], result["version"]
    days_left = int((ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) // 86400)
    issuer = dict(rdn[0] for rdn in cert.get("issuer", ())).get("organizationName", "an unknown issuer")
    cat.notes.append(f"{version}, certificate from {issuer}, expires in {days_left} days.")

    if days_left < 14:
        cat.flag(30, "high", f"Certificate expires in {days_left} days", "TLS certificate",
                 "Renew the certificate now and automate renewal.")
    elif days_left < 30:
        cat.flag(10, "medium", f"Certificate expires in {days_left} days", "TLS certificate",
                 "Renew soon, and automate renewal so it can't lapse.")
    if version != "TLSv1.3":
        cat.flag(5, "low", "TLS 1.3 is not supported", "TLS handshake",
                 "Enable TLS 1.3 in the web server or CDN configuration.")
    return cat


# ---------- HTTP response ----------

async def check_target(url: str) -> str:
    """Refuse anything but http(s) on standard ports to a public address. Run before every request hop.

    Returns the checked IP address; the request must then go to exactly that address (see pinned()),
    otherwise a second DNS lookup could return a private address (DNS rebinding).
    """
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme not in ("http", "https") or port not in (None, 80, 443) or not parts.hostname:
        raise ScanError(f"Won't request {url}")
    addrs = await resolve_public(parts.hostname)
    return next((a for a in addrs if ":" not in a), addrs[0])


def pinned(url: str, ip: str) -> tuple[str, dict, dict]:
    """The request for `url`, aimed at an already-checked IP: (URL with the IP, headers, httpx extensions).

    The original hostname goes in the Host header and, for HTTPS, in the TLS server name (SNI),
    so the site answers exactly as it would to a normal request.
    """
    parts = urlsplit(url)
    try:
        hostname = parts.hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise ScanError(f"Won't request {url}")
    port = f":{parts.port}" if parts.port else ""
    netloc = (f"[{ip}]" if ":" in ip else ip) + port
    target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    extensions = {"sni_hostname": hostname} if parts.scheme == "https" else {}
    return target, {"Host": hostname + port}, extensions


async def read_capped(resp: httpx.Response, limit: int) -> bytes:
    body = bytearray()
    async for chunk in resp.aiter_bytes():   # decompressed bytes, so a compression bomb is capped too
        body += chunk
        if len(body) >= limit:
            break
    return bytes(body[:limit])


def decode_html(body: bytes, charset: str | None) -> str:
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:   # unknown charset name in the Content-Type header
        return body.decode("utf-8", errors="replace")


async def fetch_page(client: httpx.AsyncClient, url: str) -> Page:
    """GET a page, following redirects by hand so every hop is re-checked."""
    cookies: list[str] = []
    for _ in range(MAX_REDIRECTS + 1):
        target, headers, extensions = pinned(url, await check_target(url))
        async with client.stream("GET", target, headers=headers, extensions=extensions) as resp:
            cookies += resp.headers.get_list("set-cookie")
            location = resp.headers.get("location")
            if resp.is_redirect and location:
                url = urljoin(url, location)
                continue
            body = ""
            if "html" in resp.headers.get("content-type", "").lower():
                body = decode_html(await read_capped(resp, MAX_BODY), resp.charset_encoding)
            return Page(url, resp.status_code, resp.headers, cookies, body)
    raise ScanError("Too many redirects.")


async def fetch_asset(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Download a small file (a favicon) with the same address checks as fetch_page; None on any problem."""
    try:
        for _ in range(3):
            target, headers, extensions = pinned(url, await check_target(url))
            async with client.stream("GET", target, headers=headers, extensions=extensions) as resp:
                location = resp.headers.get("location")
                if resp.is_redirect and location:
                    url = urljoin(url, location)
                    continue
                if resp.status_code != 200:
                    return None
                data = await read_capped(resp, MAX_ICON_BYTES + 1)
                return data if 0 < len(data) <= MAX_ICON_BYTES else None
    except (httpx.HTTPError, ScanError):
        return None
    return None


async def try_fetch(client: httpx.AsyncClient, url: str) -> Page | None:
    try:
        return await fetch_page(client, url)
    except (httpx.HTTPError, ScanError):
        return None


def check_headers(page: Page) -> Category:
    cat = Category("headers", "Security headers")
    h = page.headers
    csp = h.get("content-security-policy", "")
    directives = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0].lower()] = tokens[1:]

    if page.url.startswith("https://"):
        hsts = h.get("strict-transport-security")
        if not hsts:
            cat.flag(20, "high", "No Strict-Transport-Security header", "Response headers",
                     "Add `Strict-Transport-Security: max-age=31536000; includeSubDomains`.")
        else:
            match = re.search(r"max-age=(\d+)", hsts)
            if not match or int(match.group(1)) < 15552000:
                cat.flag(5, "low", "HSTS max-age is shorter than 6 months", "Strict-Transport-Security",
                         "Raise max-age to at least `31536000` (one year).")

    if not csp:
        cat.flag(20, "high", "No Content-Security-Policy header", "Response headers",
                 "Start with `Content-Security-Policy-Report-Only`, fix the violations it reports, "
                 "then enforce the policy.")
    elif "'unsafe-inline'" in directives.get("script-src", directives.get("default-src", [])):
        cat.flag(5, "low", "CSP allows inline scripts", "Content-Security-Policy",
                 "Replace `'unsafe-inline'` in script-src with nonces or hashes.")

    if h.get("x-content-type-options", "").lower() != "nosniff":
        cat.flag(10, "medium", "MIME sniffing is not disabled", "X-Content-Type-Options",
                 "Add `X-Content-Type-Options: nosniff`.")
    if not h.get("x-frame-options") and "frame-ancestors" not in directives:
        cat.flag(15, "medium", "Page can be embedded by other sites (clickjacking)", "Response headers",
                 "Add `Content-Security-Policy: frame-ancestors 'self'` or `X-Frame-Options: DENY`.")
    if not h.get("referrer-policy"):
        cat.flag(5, "low", "No Referrer-Policy header", "Response headers",
                 "Add `Referrer-Policy: strict-origin-when-cross-origin`.")
    if not h.get("permissions-policy"):
        cat.flag(5, "low", "No Permissions-Policy header", "Response headers",
                 "Add a Permissions-Policy that turns off features you don't use, e.g. "
                 "`camera=(), microphone=(), geolocation=()`.")

    cat.notes.append(f"Checked {page.url} (HTTP {page.status}).")
    return cat


def check_cookies(page: Page) -> Category:
    cat = Category("cookies", "Cookie configuration")
    seen = {}
    for raw in page.cookies:
        name = raw.split("=", 1)[0].strip()
        seen[name] = {a.strip().split("=", 1)[0].lower() for a in raw.split(";")[1:]}
    if not seen:
        cat.notes.append("No cookies set on the homepage.")
        return cat

    for name, attrs in seen.items():
        if page.url.startswith("https://") and "secure" not in attrs:
            cat.flag(15, "medium", f"Cookie `{name}` is missing the Secure flag", "Set-Cookie",
                     "Add `Secure` so the cookie is never sent over plain HTTP.")
        if "httponly" not in attrs:
            cat.flag(8, "low", f"Cookie `{name}` is readable by JavaScript", "Set-Cookie",
                     "Add `HttpOnly` unless client-side scripts genuinely need this cookie.")
        if "samesite" not in attrs:
            cat.flag(5, "low", f"Cookie `{name}` has no SameSite attribute", "Set-Cookie",
                     "Add `SameSite=Lax` (or `Strict`) to limit cross-site request forgery.")
    cat.notes.append(f"{len(seen)} cookie(s) inspected.")
    return cat


DISCLOSURE_HEADERS = {
    "x-powered-by": "X-Powered-By",
    "x-aspnet-version": "X-AspNet-Version",
    "x-aspnetmvc-version": "X-AspNetMvc-Version",
    "x-generator": "X-Generator",
}


def check_disclosure(page: Page) -> Category:
    cat = Category("disclosure", "Information disclosure")
    server = page.headers.get("server", "")[:80]
    if re.search(r"\d", server):
        cat.flag(30, "low", f"Server header reveals a version: {server}", "Server",
                 "Hide version numbers, e.g. `server_tokens off;` in nginx or `ServerTokens Prod` in Apache.")
    for key, label in DISCLOSURE_HEADERS.items():
        value = page.headers.get(key, "")[:80]
        if value:
            cat.flag(20, "low", f"{label} reveals the tech stack: {value}", label,
                     f"Remove the {label} header in the app or server configuration.")
    if not cat.findings:
        cat.notes.append("No version or framework details in response headers.")
    return cat


# ---------- DNS & email ----------

async def dns_records(resolver: dns.asyncresolver.Resolver, name: str, rdtype: str) -> list:
    try:
        return list(await resolver.resolve(name, rdtype))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []


async def txt_records(resolver: dns.asyncresolver.Resolver, name: str) -> list[str]:
    return [b"".join(r.strings).decode(errors="replace") for r in await dns_records(resolver, name, "TXT")]


def parent_domains(domain: str) -> list[str]:
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


async def check_email(host: str) -> Category:
    cat = Category("email", "DNS & email auth")
    domain = host.removeprefix("www.")
    # Home routers often can't return large TXT answers (SPF-heavy domains), so ask public resolvers.
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = PUBLIC_RESOLVERS
    resolver.lifetime = TIMEOUT

    spf = [t for t in await txt_records(resolver, domain) if t.lower().startswith("v=spf1")]
    if not spf:
        cat.flag(30, "medium", "No SPF record", f"{domain} TXT",
                 "Publish an SPF record listing the servers allowed to send your mail, ending in `-all` or `~all`.")
    elif spf[0].rstrip().endswith("+all"):
        cat.flag(30, "high", "SPF allows any server to send as this domain", f"{domain} TXT",
                 "Replace `+all` with `-all` or `~all`.")
    elif spf[0].rstrip().endswith("?all"):
        cat.flag(10, "medium", "SPF is neutral about unlisted senders", f"{domain} TXT",
                 "Replace `?all` with `-all` or `~all`.")

    dmarc, dmarc_at = None, domain
    for name in parent_domains(domain):
        found = [t for t in await txt_records(resolver, f"_dmarc.{name}") if t.lower().startswith("v=dmarc1")]
        if found:
            dmarc, dmarc_at = found[0], name
            break
    policy = None
    if not dmarc:
        cat.flag(35, "medium", "No DMARC policy", f"_dmarc.{domain} TXT",
                 "Publish `v=DMARC1; p=none; rua=mailto:you@yourdomain` to collect reports, "
                 "then move to `p=quarantine` or `p=reject`.")
    else:
        match = re.search(r"\bp\s*=\s*(\w+)", dmarc, re.IGNORECASE)
        policy = match.group(1).lower() if match else "none"
        if policy == "none":
            cat.flag(20, "medium", 'DMARC policy is "none", so spoofed mail is not blocked',
                     f"_dmarc.{dmarc_at} TXT", "Move to `p=quarantine`, then `p=reject` once reports look clean.")

    has_caa = False
    for name in parent_domains(domain):
        if await dns_records(resolver, name, "CAA"):
            has_caa = True
            break
    if not has_caa:
        cat.flag(10, "low", "No CAA record", f"{domain} CAA",
                 "Add a CAA record naming the certificate authorities allowed to issue for this domain.")

    cat.notes.append(f"SPF {'present' if spf else 'missing'}, DMARC {policy or 'missing'}, "
                     f"CAA {'present' if has_caa else 'missing'}.")
    return cat


# ---------- scoring ----------

def grade(score: int) -> str:
    for floor, letter in ((97, "A+"), (90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def status(score: int) -> str:
    return "good" if score >= 85 else "warn" if score >= 60 else "bad"


def risk_label(risk: int) -> str:
    return "Low" if risk < 20 else "Medium" if risk < HIGH_RISK_FROM else "High"


def visit_decision(host: str, https_page: Page | None, http_page: Page | None, tls: Category | None,
                   impersonation: dict, risk: int | None, path: str | None = None,
                   leads_to: str | None = None, payment: dict | None = None) -> dict:
    """Decide whether the site is safe to link to directly; `allowed` is True only when every criterion passes."""
    final_host = (urlsplit(https_page.url).hostname or "") if https_page else ""
    online = https_page is not None or http_page is not None
    criteria = [  # (passed, requirement, problem shown when it fails)
        (https_page is not None, "Homepage loads over HTTPS",
         "Homepage doesn't load over HTTPS" if online else "Site is offline"),
        (tls is not None and not any(f.severity == "critical" for f in tls.findings),
         "Certificate is valid and trusted", "Certificate isn't valid or trusted"),
        (https_page is not None and same_owner(final_host, host),
         "Homepage stays on the same site", "Homepage redirects to a different site"),
        (impersonation["level"] in ("official", "clear"), "No signs of impersonating a brand",
         f"Impersonation check: {impersonation['verdict']}"),
        (not any(entry["status"] == "listed" for entry in impersonation["lists"]),
         "Not on any phishing or malware list", "Listed as phishing or malware"),
        (risk is not None and risk < HIGH_RISK_FROM, "Risk level is Low or Medium", "Risk level is High"),
        (leads_to is None, "Link stays on the scanned site",
         f"Link leads to a different site ({leads_to}) that wasn't checked"),
        (payment is None or payment["level"] != "danger", "No signs of a payment scam",
         f"Payment check: {payment['verdict'] if payment else ''}"),
    ]
    if not online:
        criteria = [c for c in criteria if c[1] in ("Homepage loads over HTTPS", "No signs of impersonating a brand",
                                                     "Not on any phishing or malware list")]
    return {
        "allowed": all(passed for passed, _, _ in criteria),
        # Offered either as the safe link or behind a "Continue anyway" warning; None when offline.
        # The page that was scanned: the pasted link if there was one, otherwise the homepage.
        "url": f"https://{host}{path or '/'}" if https_page else f"http://{host}{path or '/'}" if http_page else None,
        "criteria": [{"text": text, "problem": problem, "passed": passed} for passed, text, problem in criteria],
    }


async def scan(raw_domain: str) -> dict:
    started = time.monotonic()
    host = normalize_domain(raw_domain)
    path = requested_path(raw_domain)
    link = f"https://{host}{path}" if path else None
    try:
        addrs = await resolve_public(host)
    except Unresolvable:
        # Nothing to connect to, but the name, registration and blocklists can still be checked.
        impersonation = await check_impersonation(host, link)
        return {
            "domain": host,
            "resolves": False,
            "addresses": [],
            "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "risk": None,
            "categories": [],
            "findings": [],
            "impersonation": impersonation,
            "payment": None,
            "visit": visit_decision(host, None, None, None, impersonation, None),
        }
    ip = next((a for a in addrs if ":" not in a), addrs[0])

    # Certificate trust is graded by check_tls; this client only reads headers, so a
    # broken certificate shouldn't stop the header, cookie and disclosure checks.
    # The page to inspect for a fake login form: the pasted link (fake login pages usually sit at a
    # specific path) or the homepage. It's rendered with its scripts in parallel with everything else.
    target = link or f"https://{host}/"
    render_task = asyncio.create_task(render_page(target))
    try:
        async with httpx.AsyncClient(verify=False, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            tls, https_page, http_page, email, records = await asyncio.gather(
                check_tls(host, ip),
                try_fetch(client, f"https://{host}/"),
                try_fetch(client, f"http://{host}/"),
                check_email(host),
                lookup_records(host, link),
            )
            if path:
                loaded = await try_fetch(client, f"https://{host}{path}") or await try_fetch(client, f"http://{host}{path}")
            else:
                loaded = https_page or http_page
            rendered = await render_task

            static = parse_html(loaded.body, loaded.url) if loaded is not None and loaded.body else None
            landed = next((urlsplit(p.url).hostname or "" for p in (loaded, rendered) if p is not None
                           and not same_owner(urlsplit(p.url).hostname or "", host)), None)
            features = merge(static, rendered)
            payment = None if landed else check_payment_page(host, features, records, link)
            if landed:
                # Link shorteners and redirects (including script redirects): the page belongs to another
                # site, so don't judge this one by it.
                page_signals = [{"points": 0, "tone": "info",
                                 "text": f"Leads to a different site, {landed}. Scan that address to check it."}]
                page_facts = {"url": (rendered or loaded).url, "redirected_to": landed, "brands_named": [],
                              "credential_form": None, "form_target": None, "rendered": rendered is not None}
            elif features is not None:
                page_signals, page_facts = await check_clone(host, features, lambda url: fetch_asset(client, url),
                                                             static=static)
                page_facts["url"] = features.url
            else:
                page_signals, page_facts = [], None
    finally:
        render_task.cancel()   # no-op when finished; stops a render if the scan is cut short
    impersonation = assess(host, records, page_signals, page_facts)

    if http_page is not None and not http_page.url.startswith("https://"):
        tls.flag(25, "high", "HTTP does not redirect to HTTPS", f"http://{host}/",
                 "Redirect every HTTP request to HTTPS with a 301.")

    page = https_page or http_page
    if page is None:
        # Taken-down phishing sites often still resolve; the domain checks are still worth returning.
        tls.notes.append("The homepage didn't load, so headers, cookies and disclosure weren't checked.")
        categories = [tls, email]
    else:
        categories = [tls, check_headers(page), email, check_cookies(page), check_disclosure(page)]
    security = sum(c.score * WEIGHTS[c.key] for c in categories) / sum(WEIGHTS[c.key] for c in categories)
    risk = round(100 - security)
    findings = [(f, c.name) for c in categories for f in c.findings]
    if any(f.severity == "critical" for f, _ in findings):
        risk = max(risk, 60)
    findings.sort(key=lambda item: SEVERITY_ORDER[item[0].severity])

    return {
        "domain": host,
        "resolves": True,
        "addresses": addrs,
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_ms": round((time.monotonic() - started) * 1000),
        "risk": {"score": risk, "label": risk_label(risk)},
        "categories": [
            {"key": c.key, "name": c.name, "score": c.score, "grade": grade(c.score),
             "status": status(c.score), "notes": c.notes, "issues": len(c.findings)}
            for c in categories
        ],
        "findings": [{**asdict(f), "category": name} for f, name in findings],
        "impersonation": impersonation,
        "payment": payment,
        "visit": visit_decision(host, https_page, http_page, tls, impersonation, risk, path,
                                (page_facts or {}).get("redirected_to"), payment),
    }
