"""Render a page in a locked-down headless Chromium to see login forms that JavaScript builds.

The page's scripts run, so the browser is treated as hostile:
- every request (page, frames, popups, redirects, subresources) is checked and blocked unless it
  goes to a public address over http(s) on port 80/443, so a page can't reach private networks;
- WebSockets never connect, service workers are blocked, downloads are refused, and WebRTC is
  limited so it can't probe local addresses;
- Chromium's sandbox is on, every render gets a fresh empty profile, and renders are capped in
  number, time and requests. Nothing is typed or clicked.

Known gap: Chromium resolves DNS itself, so a domain that answers our check with a public address
and Chromium with a private one (DNS rebinding) could slip through. Run the renderer somewhere that
cannot reach private networks at all (a container or VM with egress-only firewall rules) before launch.
"""
from __future__ import annotations

import asyncio
import os
import re
import socket
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Browser, Playwright, Route, async_playwright
from playwright.async_api import Error as PlaywrightError

from clone import PageFeatures
from netsafety import is_public_ip

# Chromium's own sandbox. Keep it on. Some hosts' kernels refuse the namespaces it needs inside
# containers; setting ARTEMIS_CHROMIUM_SANDBOX=0 is the last-resort fix (see DEPLOY.md).
CHROMIUM_SANDBOX = os.environ.get("ARTEMIS_CHROMIUM_SANDBOX", "1") != "0"
RENDER_TIMEOUT = 14.0     # seconds for a whole render, including browser start-up
NAV_TIMEOUT_MS = 10_000   # page load
SETTLE_MS = 2_500         # extra time for scripts to finish building the page
MAX_CONCURRENT = 2
MAX_REQUESTS = 300        # per render
MAX_FRAMES = 10
MAX_HOPS = 5              # redirects followed per request
MAX_RESPONSE_BYTES = 5_000_000    # largest single response given to the page
MAX_RENDER_BYTES = 25_000_000     # total per render; later requests are refused
FETCH_TIMEOUT_MS = 8_000
# Not needed to find forms. Images are skipped too: every allowed request is downloaded in full by the
# redirect-checking filter below, and page image URLs are still read from the DOM.
BLOCKED_TYPES = {"image", "media", "font", "manifest"}
# A regular desktop Chrome user agent: phishing kits often show a harmless page to obvious bots.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
CHROMIUM_ARGS = [
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--no-first-run",
]

# Runs inside each frame. Returns the same shape PageFeatures needs, with absolute URLs.
EXTRACT_JS = r"""
() => {
  const abs = (u) => { if (!u) return null; try { return new URL(u, document.baseURI).href; } catch (e) { return null; } };
  const CARD = /card.?(num|no)|cc.?num|cvv|cvc|\bcsc\b|expir/i;
  const CARD_AUTO = ["cc-number", "cc-csc", "cc-exp", "cc-exp-month", "cc-exp-year"];
  const roots = [document];
  const walk = (root) => {
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot && roots.length < 200) { roots.push(el.shadowRoot); walk(el.shadowRoot); }
    }
  };
  walk(document);

  const forms = new Map();
  const loose = { action: null, password: false, card: false };
  let seen = 0;
  for (const root of roots) {
    for (const input of root.querySelectorAll("input")) {
      if (++seen > 2000) break;
      let target = loose;
      const form = input.form;
      if (form) {
        if (!forms.has(form)) {
          forms.set(form, { action: form.hasAttribute("action") ? abs(form.getAttribute("action")) : null,
                            password: false, card: false });
        }
        target = forms.get(form);
      }
      if ((input.type || "").toLowerCase() === "password") target.password = true;
      const hints = [input.name, input.id, input.placeholder].join(" ");
      if (CARD_AUTO.includes((input.autocomplete || "").toLowerCase()) || CARD.test(hints)) target.card = true;
    }
  }
  const outForms = [...forms.values()];
  if (loose.password || loose.card) outForms.push(loose);

  const meta = {};
  for (const m of document.querySelectorAll("meta")) {
    const key = (m.getAttribute("property") || m.getAttribute("name") || "").toLowerCase();
    if (["og:site_name", "og:title", "application-name", "twitter:title"].includes(key)) {
      meta[key] = (m.getAttribute("content") || "").slice(0, 200);
    }
  }
  const icons = [...document.querySelectorAll("link[rel][href]")]
    .filter((l) => /icon/i.test(l.getAttribute("rel"))).map((l) => abs(l.getAttribute("href"))).filter(Boolean);
  const resources = [...document.querySelectorAll('img[src], script[src], link[rel~="stylesheet"][href], link[rel*="icon"][href]')]
    .slice(0, 500).map((e) => abs(e.getAttribute("src") || e.getAttribute("href"))).filter(Boolean);
  return { url: location.href, title: (document.title || "").slice(0, 300), meta, icons, resources, forms: outForms };
}
"""

_playwright: Playwright | None = None
_browser: Browser | None = None
_browser_lock = asyncio.Lock()
_slots = asyncio.Semaphore(MAX_CONCURRENT)


async def is_public(host: str, cache: dict[str, bool]) -> bool:
    if host not in cache:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
            cache[host] = bool(infos) and all(is_public_ip(info[4][0]) for info in infos)
        except (OSError, ValueError):
            cache[host] = False
    return cache[host]


async def allowed(url: str, cache: dict[str, bool]) -> bool:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme in ("http", "https") and port in (None, 80, 443) and bool(parts.hostname)
            and await is_public(parts.hostname, cache))


async def _get_browser() -> Browser:
    global _playwright, _browser
    async with _browser_lock:
        if _browser is None or not _browser.is_connected():
            if _playwright is None:
                _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True, chromium_sandbox=CHROMIUM_SANDBOX,
                                                         args=CHROMIUM_ARGS)
        return _browser


async def shutdown() -> None:
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


async def _render(url: str) -> PageFeatures | None:
    browser = await _get_browser()
    context = await browser.new_context(
        user_agent=USER_AGENT, locale="en-US", viewport={"width": 1280, "height": 800},
        accept_downloads=False, service_workers="block", ignore_https_errors=True,
    )
    try:
        cache: dict[str, bool] = {}
        requests = 0
        downloaded = 0   # bytes passed to the page so far
        pending_navigation: list[str] = []   # main-frame redirect target, checked, for us to navigate to
        page = await context.new_page()

        # Chromium follows redirects without calling route handlers for the later hops, so redirects are
        # resolved here instead: every hop is fetched with redirects off and checked before the next one.
        async def filter_request(route: Route) -> None:
            nonlocal requests, downloaded
            requests += 1
            request = route.request
            if (requests > MAX_REQUESTS or downloaded > MAX_RENDER_BYTES or request.resource_type in BLOCKED_TYPES
                    or not await allowed(request.url, cache)):
                await route.abort("blockedbyclient")
                return
            try:
                current = request.url
                response = await route.fetch(max_redirects=0, timeout=FETCH_TIMEOUT_MS)
                for _ in range(MAX_HOPS + 1):
                    location = response.headers.get("location")
                    if not (300 <= response.status < 400 and location):
                        size = len(await response.body())
                        downloaded += size
                        if size > MAX_RESPONSE_BYTES or downloaded > MAX_RENDER_BYTES:
                            break   # too big: abort below rather than hand it to the page
                        await route.fulfill(response=response)
                        return
                    current = urljoin(current, location)
                    if not await allowed(current, cache):
                        break
                    if request.is_navigation_request() and request.frame == page.main_frame:
                        pending_navigation.append(current)   # re-navigate so the page gets its real address
                        break
                    response = await context.request.get(current, max_redirects=0, timeout=FETCH_TIMEOUT_MS)
                await route.abort("blockedbyclient")
            except PlaywrightError:
                await route.abort("failed")

        async def never_connect(ws) -> None:   # a handler that doesn't call connect_to_server keeps it offline
            return None

        await context.route("**/*", filter_request)
        await context.route_web_socket(re.compile(".*"), never_connect)

        target = url
        for _ in range(MAX_HOPS + 1):
            pending_navigation.clear()
            try:
                await page.goto(target, wait_until="load", timeout=NAV_TIMEOUT_MS)
            except PlaywrightError:
                pass   # blocked redirect, slow load or navigation error; handled below
            if not pending_navigation:
                try:
                    await page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
                except PlaywrightError:
                    pass
            if not pending_navigation:   # also catches script navigations that redirected while settling
                break
            target = pending_navigation[-1]
        else:
            return None
        if not page.url.startswith(("http://", "https://")):
            return None

        frames = []
        for frame in page.frames[:MAX_FRAMES]:
            try:
                frames.append(await frame.evaluate(EXTRACT_JS))
            except PlaywrightError:
                continue   # detached or navigating frame
        if not frames:
            return None
        main = frames[0]
        return PageFeatures(
            url=page.url,
            title=main["title"].strip(),
            meta=main["meta"],
            icons=main["icons"],
            resources=[r for f in frames for r in f["resources"]],
            forms=[form for f in frames for form in f["forms"]],
            rendered=True,
        )
    finally:
        await context.close()


SELF_TEST_PAGE = ("<title>self-test</title><body><script>"
                  "const f = document.createElement('form'); f.innerHTML = '<input type=password>';"
                  "document.body.appendChild(f);</script></body>")


async def self_test() -> str | None:
    """Launch the sandboxed browser and check a script-built password form is found. Returns an error or None."""
    try:
        browser = await _get_browser()
        context = await browser.new_context(service_workers="block", accept_downloads=False)
        try:
            await context.route("**/*", lambda route: route.abort("blockedbyclient"))   # no network at all
            page = await context.new_page()
            await page.set_content(SELF_TEST_PAGE, timeout=NAV_TIMEOUT_MS)
            found = await page.main_frame.evaluate(EXTRACT_JS)
        finally:
            await context.close()
        if not any(form["password"] for form in found["forms"]):
            return "browser ran, but the script-built test form wasn't found"
        return None
    except Exception as exc:   # report anything: this runs once at startup to surface a broken deployment
        return f"{type(exc).__name__}: {exc}".splitlines()[0][:300]


async def render_page(url: str) -> PageFeatures | None:
    """Rendered page features, or None if the page couldn't be rendered safely in time."""
    if not await allowed(url, {}):
        return None
    try:
        async with _slots:
            return await asyncio.wait_for(_render(url), RENDER_TIMEOUT)
    except (PlaywrightError, asyncio.TimeoutError, OSError, NotImplementedError):
        return None
