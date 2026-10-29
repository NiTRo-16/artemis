"""Regression + security-fix tests against main.app with a throwaway database."""
import asyncio
import os
import secrets
import time
import types

import testenv  # noqa: F401  (test database; must come before importing the app)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

results = []


def ok(label, cond):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + label)


pw = secrets.token_urlsafe(16)
email = f"t-{secrets.token_hex(4)}@example.com"

with TestClient(main.app, base_url="http://testserver") as c:
    # --- existing behaviour still works ---
    ok("signup", c.post("/api/signup", json={"email": email, "password": pw}).status_code == 200)
    import mail, re
    link = mail.OUTBOX[-1].get_content()
    token = re.search(r"/verify#([A-Za-z0-9_\-]+)", link).group(1)
    ok("confirm email via link", c.post("/api/verify", json={"token": token, "password": pw}).status_code == 200)
    ok("settings save", c.put("/api/settings", json={"theme": "dark", "same_tab": False}).status_code == 200)
    r = c.post("/api/scan", json={"domain": "example.com"})
    ok("scan while signed in", r.status_code == 200 and r.json()["risk"]["label"] in ("Low", "Medium"))
    ok("history recorded", len(c.get("/api/history").json()["scans"]) == 1)
    ok("check endpoint", c.post("/api/check", json={"domain": "github.com"}).json()["level"] == "official")
    ok("cross-site signup still refused", c.post("/api/signup", json={"email": "x@example.com", "password": pw},
                                                 headers={"Origin": "https://evil.example"}).status_code == 403)

    # --- fix: request body limit ---
    big = '{"domain": "' + "a" * 200_000 + '"}'
    ok("oversized body refused with 413 (Content-Length)", c.post("/api/check", content=big,
       headers={"Content-Type": "application/json"}).status_code == 413)

    def chunks():
        for _ in range(100):
            yield b"a" * 1000
    ok("oversized chunked body refused with 413", c.post("/api/check", content=chunks(),
       headers={"Content-Type": "application/json"}).status_code == 413)
    ok("bad Content-Length refused", c.post("/api/check", content=b"{}", headers={"Content-Length": "abc",
       "Content-Type": "application/json"}).status_code in (400, 413))
    ok("normal small body still accepted", c.post("/api/check", json={"domain": "example.com"}).status_code == 200)

    # --- fix: headers ---
    h = c.get("/").headers
    ok("COOP + CORP headers present", h.get("cross-origin-opener-policy") == "same-origin"
       and h.get("cross-origin-resource-policy") == "same-origin")
    ok("API responses are no-store", c.get("/api/me").headers.get("cache-control") == "no-store")
    ok("pages still revalidate (no-cache)", h.get("cache-control") == "no-cache")

    # --- fix: health endpoint leaks nothing ---
    main.app.state.renderer_error = "Error: /home/pwuser/secret/path something failed"
    body = c.get("/healthz")
    ok("healthz degraded reveals no internal detail", body.status_code == 503 and body.json() == {"status": "degraded"})
    main.app.state.renderer_error = None
    ok("healthz ok", c.get("/healthz").json() == {"status": "ok"})

    # --- fix: per-account failed-password limit (spread across networks) ---
    c.post("/api/logout")
    victim = email
    main.auth_limiter.reset()
    codes = []
    for i in range(12):
        main.auth_limiter.reset()   # pretend each try comes from a different network
        codes.append(c.post("/api/login", json={"email": victim, "password": "wrong-" + str(i)}).status_code)
    ok(f"wrong passwords for one account locked after 10 (codes end {codes[-3:]})", codes[:10] == [401] * 10 and codes[10] == 429)
    main.auth_limiter.reset()
    ok("right password also refused while locked", c.post("/api/login", json={"email": victim, "password": pw}).status_code == 429)
    main.failed_login_limiter.reset()
    main.auth_limiter.reset()
    ok("login works again once the lock clears", c.post("/api/login", json={"email": victim, "password": pw}).status_code == 200)

    # --- fix: signup limit ---
    c.post("/api/logout")
    main.signup_limiter.reset()
    codes = [c.post("/api/signup", json={"email": f"s{i}-{secrets.token_hex(3)}@example.com", "password": pw}).status_code
             for i in range(7)]
    ok(f"signup limited to 5 per network per hour ({codes})", codes[:5] == [200] * 5 and codes[5] == 429)

    # --- a full queue refuses new scans ---
    import jobs  # noqa: E402
    main.scan_limiter.reset()
    jobs.MAX_QUEUED = 0
    ok("scans refused with 503 when the queue is full", c.post("/api/scan", json={"domain": "example.org"}).status_code == 503)
    jobs.MAX_QUEUED = 200

# --- fix: IPv6 /64 treated as one visitor ---
def req(ip):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=ip))
ok("two IPv6 addresses in one /64 share a limit key",
   main.client_key(req("2001:db8:1:2::1")) == main.client_key(req("2001:db8:1:2:ffff::9")))
ok("different /64s get different keys", main.client_key(req("2001:db8:1:2::1")) != main.client_key(req("2001:db8:1:3::1")))
ok("IPv4-mapped IPv6 keyed as the IPv4", main.client_key(req("::ffff:203.0.113.5")) == "203.0.113.5")

# --- rate limits are shared through Redis and hold no raw addresses ---
import store  # noqa: E402
main.scan_limiter.reset()
main.scan_limiter.check("203.0.113.9", 10, "x")
ok("limiter keys hold no raw addresses", not any("203.0.113.9" in k for k in store.sync_client().keys("rl:*")))

print(f"\n{sum(results)}/{len(results)} passed")
