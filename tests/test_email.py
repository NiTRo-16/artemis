"""End-to-end tests for email verification and password reset (console mail backend)."""
import os
import re
import secrets
import statistics
import time

import testenv  # noqa: F401  (test database; must come before importing the app)

from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
import mail  # noqa: E402
import main  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def reset_limits():
    for limiter in (main.auth_limiter, main.signup_limiter, main.failed_login_limiter, main.reset_limiter,
                    main.email_limiter):
        limiter.hits.clear()


def last_mail(to, subject_part):
    for m in reversed(mail.OUTBOX):
        if m["To"] == to and subject_part in m["Subject"]:
            return m
    return None


def token_from(message, path):
    match = re.search(re.escape(mail.APP_URL + path) + r"#([A-Za-z0-9_\-]+)", message.get_content())
    return match.group(1) if match else None


victim = f"victim-{secrets.token_hex(3)}@example.com"
victim_pw = secrets.token_urlsafe(14)
attacker_pw = secrets.token_urlsafe(14)

with TestClient(main.app, base_url="http://testserver") as c:
    # --- sign-up and confirmation ---
    r = c.post("/api/signup", json={"email": victim, "password": victim_pw})
    ok("sign-up replies 'check your email' and does not sign in", r.json() == {"status": "check_email"}
       and "set-cookie" not in r.headers and c.get("/api/me").json()["account"] is None)
    m = last_mail(victim, "Confirm")
    token = token_from(m, "/verify") if m else None
    ok("confirmation email sent with a /verify#token link", token is not None)
    ok("token is in the # part (never sent to the server or logs)", "#" + token in m.get_content() and "?" not in m.get_content().split("/verify")[1].split()[0])

    r = c.post("/api/login", json={"email": victim, "password": victim_pw})
    ok("unconfirmed account can't log in, gets a new link", r.status_code == 403 and "Confirm your email" in r.json()["detail"])
    new_token = token_from(last_mail(victim, "Confirm"), "/verify")
    ok("the older link stops working once a new one is sent",
       c.post("/api/verify", json={"token": token, "password": victim_pw}).status_code == 400)
    ok("confirming with the wrong password fails", c.post("/api/verify", json={"token": new_token, "password": attacker_pw}).status_code == 401)
    r = c.post("/api/verify", json={"token": new_token, "password": victim_pw})
    ok("confirming with the right password signs in", r.status_code == 200 and c.get("/api/me").json()["account"]["email"] == victim)
    ok("a used confirmation link can't be reused", c.post("/api/verify", json={"token": new_token, "password": victim_pw}).status_code == 400)
    c.post("/api/logout")
    reset_limits()
    ok("confirmed account logs in normally", c.post("/api/login", json={"email": victim, "password": victim_pw}).status_code == 200)
    c.post("/api/logout")

    # --- sign-up doesn't reveal who has an account ---
    reset_limits()
    before = len(mail.OUTBOX)
    r_existing = c.post("/api/signup", json={"email": victim, "password": attacker_pw})
    fresh = f"fresh-{secrets.token_hex(3)}@example.com"
    r_new = c.post("/api/signup", json={"email": fresh, "password": attacker_pw})
    ok("identical reply for a registered and an unregistered address",
       r_existing.status_code == r_new.status_code == 200 and r_existing.json() == r_new.json())
    ok("the real owner is told someone tried to sign up", last_mail(victim, "Sign-up attempt") is not None)
    reset_limits()
    login_attempt = c.post("/api/login", json={"email": victim, "password": attacker_pw})
    ok("that attempt didn't change the owner's password", login_attempt.status_code == 401)

    def timed(email):
        reset_limits()
        t = time.perf_counter()
        c.post("/api/signup", json={"email": email, "password": attacker_pw})
        return time.perf_counter() - t
    existing_times = [timed(victim) for _ in range(5)]
    new_times = [timed(f"t{i}-{secrets.token_hex(3)}@example.com") for i in range(5)]
    e, n = statistics.median(existing_times) * 1000, statistics.median(new_times) * 1000
    ok(f"sign-up takes similar time either way ({e:.0f} ms registered vs {n:.0f} ms new)", abs(e - n) < 40)

    # --- pre-account takeover: attacker registers the victim's address first ---
    reset_limits()
    target = f"target-{secrets.token_hex(3)}@example.com"
    c.post("/api/signup", json={"email": target, "password": attacker_pw})            # attacker's sign-up
    link_token = token_from(last_mail(target, "Confirm"), "/verify")
    ok("owner clicking the attacker's link can't activate it with their own password",
       c.post("/api/verify", json={"token": link_token, "password": victim_pw}).status_code == 401)
    reset_limits()
    c.post("/api/password/forgot", json={"email": target})                               # owner uses Forgot password
    reset_token = token_from(last_mail(target, "Reset"), "/reset")
    ok("owner can take the address back with a reset", c.post("/api/password/reset",
       json={"token": reset_token, "password": victim_pw}).status_code == 200)
    c.post("/api/logout")
    reset_limits()
    ok("attacker's password no longer works", c.post("/api/login", json={"email": target, "password": attacker_pw}).status_code == 401)

    # --- password reset ---
    reset_limits()
    before = len(mail.OUTBOX)
    unknown = c.post("/api/password/forgot", json={"email": f"nobody-{secrets.token_hex(3)}@example.com"})
    known = c.post("/api/password/forgot", json={"email": victim})
    ok("forgot-password replies the same for unknown and known addresses", unknown.json() == known.json() == {"status": "check_email"})
    ok("only the real account got an email", len(mail.OUTBOX) == before + 1 and mail.OUTBOX[-1]["To"] == victim)
    reset_token = token_from(mail.OUTBOX[-1], "/reset")

    reset_limits()
    c.post("/api/login", json={"email": victim, "password": victim_pw})                 # a signed-in device
    old_cookie = c.cookies.get(main.SESSION_COOKIE)
    ok("weak new password refused", c.post("/api/password/reset", json={"token": reset_token, "password": "short"}).status_code == 400)
    new_pw = secrets.token_urlsafe(14)
    r = c.post("/api/password/reset", json={"token": reset_token, "password": new_pw})
    ok("reset works and signs in", r.status_code == 200)
    ok("reset signs out every other device", db.user_for_session(old_cookie) is None)
    ok("owner is notified the password changed", last_mail(victim, "password was changed") is not None)
    ok("a used reset link can't be reused", c.post("/api/password/reset", json={"token": reset_token, "password": new_pw}).status_code == 400)
    c.post("/api/logout")
    reset_limits()
    ok("old password rejected, new one accepted",
       c.post("/api/login", json={"email": victim, "password": victim_pw}).status_code == 401
       and c.post("/api/login", json={"email": victim, "password": new_pw}).status_code == 200)
    c.post("/api/logout")

    # --- expiry ---
    reset_limits()
    c.post("/api/password/forgot", json={"email": victim})
    expired = token_from(last_mail(victim, "Reset"), "/reset")
    db._exec("UPDATE email_tokens SET expires_at = %s WHERE purpose = 'reset'", (int(time.time()) - 1,))
    ok("expired reset link refused", c.post("/api/password/reset", json={"token": expired, "password": new_pw}).status_code == 400)

    # --- links can't be pointed at another site with a forged Host header ---
    reset_limits()
    c.post("/api/password/forgot", json={"email": victim}, headers={"Host": "evil.example"})
    body = last_mail(victim, "Reset").get_content()
    ok("reset link uses the configured address, not the request's Host", mail.APP_URL + "/reset#" in body and "evil.example" not in body)

    # --- no flooding an inbox ---
    reset_limits()
    mail.OUTBOX.clear()
    before = 0
    for _ in range(6):
        main.reset_limiter.hits.clear()   # even from many networks
        c.post("/api/password/forgot", json={"email": victim})
    ok(f"at most 3 emails an hour to one address ({len(mail.OUTBOX) - before} sent for 6 requests)", len(mail.OUTBOX) - before == 3)

    # --- unconfirmed accounts are cleaned up ---
    reset_limits()
    stale = f"stale-{secrets.token_hex(3)}@example.com"
    c.post("/api/signup", json={"email": stale, "password": attacker_pw})
    db._exec("UPDATE users SET created_at = %s WHERE email = %s", (int(time.time()) - db.UNVERIFIED_SECONDS - 10, stale))
    c.post("/api/signup", json={"email": f"another-{secrets.token_hex(3)}@example.com", "password": attacker_pw})
    ok("unconfirmed account older than 7 days is deleted", db.user_by_email(stale) is None)

    # --- header injection ---
    reset_limits()
    r = c.post("/api/signup", json={"email": "a@example.com\r\nBcc: x@evil.example", "password": attacker_pw})
    ok("address containing a line break is rejected", r.status_code == 400)

    # --- /verify and /reset serve the page ---
    ok("/verify and /reset serve the page", c.get("/verify").status_code == 200 and c.get("/reset").status_code == 200
       and "<title>Artemis" in c.get("/reset").text)
    ok("healthz ok in local mode", c.get("/healthz").json() == {"status": "ok"})

# --- production without SMTP must fail loudly ---
old = mail.APP_URL
mail.APP_URL = "https://artemis.example"
ok("missing SMTP on a real domain is reported", mail.config_problem() is not None)
mail.APP_URL = old

print(f"\n{sum(results)}/{len(results)} passed")
