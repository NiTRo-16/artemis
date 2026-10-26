"""Tests for UPI and payment-page checks, site reports, and Google sign-in (Google mocked)."""
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"
for suffix in ("", "-wal", "-shm"):
    pathlib.Path(os.environ["ARTEMIS_DB"] + suffix).unlink(missing_ok=True)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
import google_auth  # noqa: E402
import main  # noqa: E402
from clone import PageFeatures, new_form, parse_html  # noqa: E402
from payments import check_payment_page, check_upi, is_upi  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def texts(pay):
    return " | ".join(s["text"] for s in pay["signals"])


# ---------- UPI ----------
ok("bare UPI ID is recognised", is_upi("shop.name@okaxis"))
ok("email address is not a UPI ID", not is_upi("someone@gmail.com"))
ok("domain is not UPI", not is_upi("example.com"))

plain = check_upi("upi://pay?pa=ramesh.kumar@okaxis&pn=Ramesh%20Kumar&am=250&cu=INR")
ok("ordinary UPI payment is clear", plain["level"] == "clear")
ok("amount shown in rupees", ["Amount", "₹250.00"] in plain["facts"])
ok("app named from handle", ["UPI app", "Google Pay (@okaxis)"] in plain["facts"])

refund = check_upi("upi://pay?pa=support123@ybl&pn=Customer%20Care&tn=Refund%20for%20your%20order&am=4999")
ok("refund note is danger", refund["level"] == "danger" and "refund" in texts(refund).lower())
ok("customer care name is flagged", "customer care" in texts(refund).lower())

kyc = check_upi("upi://pay?pa=kycupdate@paytm&pn=SBI%20KYC%20Update&tn=KYC%20verification")
ok("KYC pretext is caution or worse", kyc["level"] in ("caution", "danger") and "KYC" in texts(kyc))
ok("bank name in payee is flagged", "State Bank of India" in texts(kyc))

police = check_upi("upi://pay?pa=fine.payment@ybl&pn=Cyber%20Police&tn=Penalty")
ok("police name is caution", police["level"] in ("caution", "danger") and "police" in texts(police).lower())

gift_shop = check_upi("upi://pay?pa=giftshop@ybl&pn=Sharma%20Gift%20Store&am=500")
ok("gift shop is not flagged", gift_shop["level"] == "clear")
food_court = check_upi("upi://pay?pa=foodcourt@okicici&pn=City%20Food%20Court")
ok("food court is not flagged", food_court["level"] == "clear")

mandate = check_upi("upi://mandate?pa=x.y@ybl&am=100")
ok("non-pay action is caution", mandate["level"] == "caution")
bad_amount = check_upi("upi://pay?pa=x.y@ybl&am=abc")
ok("invalid amount flagged", "valid number" in texts(bad_amount))
inf_amount = check_upi("upi://pay?pa=x.y@ybl&am=inf")
ok("infinite amount flagged", "valid number" in texts(inf_amount))
try:
    check_upi("upi://pay?pn=NoId")
    ok("missing UPI ID rejected", False)
except ValueError:
    ok("missing UPI ID rejected", True)

# ---------- payment pages ----------
old = {"registration": {"registered": datetime.now(timezone.utc) - timedelta(days=3000)}, "lists": []}
new = {"registration": {"registered": datetime.now(timezone.utc) - timedelta(days=5)}, "lists": []}


def page(url, *forms, title=""):
    return PageFeatures(url, title=title, forms=list(forms))


def form(**fields):
    f = new_form(fields.pop("action", None))
    f.update(fields)
    return f


ok("page without payment fields: no section", check_payment_page("shop.example", page("https://shop.example/", form(password=True)), old, None) is None)
pin_page = check_payment_page("upi-help.example", page("https://upi-help.example/", form(pin=True)), old, None)
ok("UPI PIN field is danger", pin_page["level"] == "danger" and "UPI PIN" in texts(pin_page))
own_card_old = check_payment_page("shop.example", page("https://shop.example/pay", form(card=True)), old, None)
ok("card form on old site is clear (info only)", own_card_old["level"] == "clear")
own_card_new = check_payment_page("shop.example", page("https://shop.example/pay", form(card=True)), new, None)
ok("card form on 5-day-old site is danger", own_card_new["level"] == "danger" and "registered only" in texts(own_card_new))
http_card = check_payment_page("shop.example", page("http://shop.example/pay", form(card=True)), old, None)
ok("card form over HTTP is danger", http_card["level"] == "danger")
offsite = check_payment_page("shop.example", page("https://shop.example/pay", form(card=True, action="https://collector.example/x")), old, None)
ok("card details sent elsewhere is danger", offsite["level"] == "danger" and "collector.example" in texts(offsite))
to_provider = check_payment_page("shop.example", page("https://shop.example/pay", form(card=True, action="https://api.razorpay.com/pay")), old, None)
ok("card details sent to a payment provider is fine", to_provider["level"] == "clear")
otp_card = check_payment_page("shop.example", page("https://shop.example/pay", form(card=True, otp=True)), old, None)
ok("card plus OTP is caution", otp_card["level"] == "caution")
stripe_frame = form(card=True)
stripe_frame["frame"] = "js.stripe.com"
hosted = check_payment_page("shop.example", page("https://shop.example/pay", stripe_frame), new, None)
ok("card fields in Stripe's frame are not blamed on a new site", hosted["level"] == "clear" and "Stripe" in texts(hosted))
ok("provider homepage: no section", check_payment_page("razorpay.com", page("https://razorpay.com/"), old, None) is None)
rzp = check_payment_page("rzp.io", page("https://rzp.io/l/abc", title="Sharma Tuition Fees"), old, "https://rzp.io/l/abc")
ok("real Razorpay link is clear", rzp["kind"] == "provider" and rzp["level"] == "clear" and "Real Razorpay" in texts(rzp))
rzp_brand = check_payment_page("rzp.io", page("https://rzp.io/l/abc", title="SBI Reward Points Redemption"), old, "https://rzp.io/l/abc")
ok("provider page naming a bank with reward bait is caution", rzp_brand["level"] == "caution")
listed = {**old, "lists": [{"name": "OpenPhish", "status": "listed", "detail": "x"}]}
rzp_listed = check_payment_page("rzp.io", page("https://rzp.io/l/abc", title="Pay"), listed, "https://rzp.io/l/abc")
ok("listed provider link is danger", rzp_listed["level"] == "danger")
ok("bank's own site: no section", check_payment_page("onlinesbi.sbi", page("https://onlinesbi.sbi/", form(pin=True)), old, None) is None)

parsed = parse_html('<form action="/x"><input name="upi_pin"><input autocomplete="one-time-code"></form>'
                    '<input placeholder="Enter MPIN"><input name="pincode">', "https://a.example/")
ok("HTML parser finds UPI PIN and OTP fields", parsed.forms[0]["pin"] and parsed.forms[0]["otp"])
ok("HTML parser finds MPIN outside a form", parsed.forms[-1]["loose"] and parsed.forms[-1]["pin"])
postal = parse_html('<form><input name="pincode" placeholder="PIN code"></form>', "https://a.example/")
ok("postal PIN code is not a UPI PIN", not any(f["pin"] for f in postal.forms))

# ---------- API: UPI scan, reports ----------
client = TestClient(main.app)
origin = {"Origin": "http://testserver"}
res = client.post("/api/scan", json={"domain": "upi://pay?pa=win.prize@ybl&tn=Claim%20your%20prize"})
body = res.json()
ok("UPI scan returns a payment report", res.status_code == 200 and body["kind"] == "upi" and body["risk"]["label"] == "High")
res = client.post("/api/scan", json={"domain": "upi://pay?pn=x"})
ok("UPI scan without an ID is a 400", res.status_code == 400)

res = client.post("/api/report", json={"target": "evil-login.example/verify", "category": "phishing",
                                       "details": "Got it by SMS\x1b[31m"}, headers=origin)
ok("report accepted", res.status_code == 200)
rows = db.reports()
ok("report stored with host and without control characters",
   len(rows) == 1 and rows[0]["host"] == "evil-login.example" and "\x1b" not in rows[0]["details"])
client.post("/api/report", json={"target": "https://evil-login.example/", "category": "phishing"}, headers=origin)
ok("repeat report from the same network is counted once", len(db.reports()) == 1)
res = client.post("/api/report", json={"target": "win.prize@ybl", "category": "payment"}, headers=origin)
ok("UPI ID can be reported", res.status_code == 200 and db.reports()[0]["host"] == "win.prize@ybl")
ok("bad category rejected", client.post("/api/report", json={"target": "a.example", "category": "spam"}, headers=origin).status_code == 422)
ok("bad target rejected", client.post("/api/report", json={"target": "not a site", "category": "other"}, headers=origin).status_code == 400)
ok("cross-site report refused", client.post("/api/report", json={"target": "b.example", "category": "other"},
                                            headers={"Origin": "https://attacker.example"}).status_code == 403)
for i in range(12):
    client.post("/api/report", json={"target": f"site{i}.example", "category": "other"}, headers=origin)
ok("reports are rate limited", client.post("/api/report", json={"target": "z.example", "category": "other"},
                                           headers=origin).status_code == 429)
cli = subprocess.run([sys.executable, "reports.py"], capture_output=True, text=True, env=os.environ,
                     encoding="utf-8")
ok("review tool lists reports", cli.returncode == 0 and "evil-login.example" in cli.stdout and "\x1b" not in cli.stdout)
subprocess.run([sys.executable, "reports.py", "done", "evil-login.example"], capture_output=True, env=os.environ)
ok("review tool marks a site reviewed", all(r["host"] != "evil-login.example" for r in db.reports()))

# ---------- Google sign-in (Google's token endpoint mocked) ----------
main.auth_limiter.hits.clear()
next_claims = {}


def id_token(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


def token_endpoint(request: httpx.Request) -> httpx.Response:
    form_data = parse_qs(request.content.decode())
    if form_data.get("client_secret") != ["test-secret"] or not form_data.get("code_verifier"):
        return httpx.Response(400, json={"error": "invalid_grant"})
    return httpx.Response(200, json={"id_token": id_token(next_claims)})


real_client = httpx.AsyncClient
google_auth.httpx.AsyncClient = lambda **kw: real_client(transport=httpx.MockTransport(token_endpoint), **kw)


def google_login(browser, sub, email, verified=True, tamper=None):
    """Run the redirect dance; returns the final ?signin= outcome."""
    main.auth_limiter.hits.clear()   # every test shares one client address
    start =browser.get("/api/auth/google", follow_redirects=False)
    assert start.status_code == 303, start.status_code
    q = parse_qs(urlsplit(start.headers["location"]).query)
    next_claims.clear()
    next_claims.update({"iss": "https://accounts.google.com", "aud": google_auth.CLIENT_ID, "sub": sub,
                        "email": email, "email_verified": verified, "exp": time.time() + 300,
                        "nonce": q["nonce"][0]})
    if tamper:
        tamper(next_claims)
    state = q["state"][0]
    back = browser.get(f"/api/auth/google/callback?state={state}&code=abc", follow_redirects=False)
    return parse_qs(urlsplit(back.headers["location"]).query).get("signin", [None])[0]


start = client.get("/api/auth/google", follow_redirects=False)
q = parse_qs(urlsplit(start.headers["location"]).query)
ok("start redirects to Google with PKCE and openid email scope",
   start.headers["location"].startswith("https://accounts.google.com/") and q["code_challenge_method"] == ["S256"]
   and q["scope"] == ["openid email"] and q["redirect_uri"] == ["http://localhost:8000/api/auth/google/callback"])
ok("state cookie is HttpOnly and scoped", "httponly" in start.headers["set-cookie"].lower()
   and "path=/api/auth/google" in start.headers["set-cookie"].lower())
ok("/api/me says Google sign-in is on", client.get("/api/me").json()["google_signin"] is True)

g = TestClient(main.app)
ok("new Google user gets an account", google_login(g, "sub-1", "Asha@Gmail.com") == "new")
me = g.get("/api/me").json()["account"]
ok("signed in as the Google email, no password", me and me["email"] == "asha@gmail.com" and me["has_password"] is False and me["google"])
ok("password login can't use the no-password marker", client.post("/api/login", json={"email": "asha@gmail.com", "password": db.NO_PASSWORD}, headers=origin).status_code == 401)
g.post("/api/logout", headers=origin)
ok("same Google user signs in again", google_login(g, "sub-1", "asha@gmail.com") == "ok")

# state from another browser (login CSRF) is refused
attacker = TestClient(main.app)
a_start = attacker.get("/api/auth/google", follow_redirects=False)
a_state = parse_qs(urlsplit(a_start.headers["location"]).query)["state"][0]
victim = TestClient(main.app)
back = victim.get(f"/api/auth/google/callback?state={a_state}&code=abc", follow_redirects=False)
ok("callback with another browser's state fails", "signin=failed" in back.headers["location"] and not victim.get("/api/me").json()["account"])

ok("unverified Google email refused", google_login(TestClient(main.app), "sub-2", "x@example.com", verified=False) == "failed")
ok("token for another app refused", google_login(TestClient(main.app), "sub-3", "y@example.com", tamper=lambda c: c.update(aud="other")) == "failed")
ok("wrong nonce refused", google_login(TestClient(main.app), "sub-4", "z@example.com", tamper=lambda c: c.update(nonce="x")) == "failed")
ok("expired token refused", google_login(TestClient(main.app), "sub-5", "w@example.com", tamper=lambda c: c.update(exp=time.time() - 10)) == "failed")
main.auth_limiter.hits.clear()
cancel = TestClient(main.app).get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
ok("cancel on Google's screen returns home quietly", cancel.headers["location"] == "/")

# existing verified password account gets linked
db.create_user("linked@example.com", "a-long-password-1")
db.mark_verified(db.user_by_email("linked@example.com")["id"])
lg = TestClient(main.app)
ok("verified password account is linked, not duplicated", google_login(lg, "sub-6", "linked@example.com") == "ok")
ok("linked account keeps its password", lg.get("/api/me").json()["account"]["has_password"] is True)
ok("different Google ID can't take a linked email", google_login(TestClient(main.app), "sub-7", "linked@example.com") == "failed")

# someone pre-registered the victim's email with their own password (never confirmed)
db.create_user("victim@example.com", "attackers-password")
pre_id = db.user_by_email("victim@example.com")["id"]
main.auth_limiter.hits.clear()
vg = TestClient(main.app)
ok("unconfirmed pre-registered account is replaced", google_login(vg, "sub-8", "victim@example.com") == "new")
fresh = db.user_by_email("victim@example.com")
ok("attacker's password no longer works", fresh["password_hash"] == db.NO_PASSWORD
   and db.authenticate("victim@example.com", "attackers-password") is None)

# deleting a Google-only account needs the email typed
ok("delete with wrong email refused", vg.post("/api/account/delete", json={"password": "nope@example.com"}, headers=origin).status_code == 401)
vid = db.user_by_email("victim@example.com")["id"]
db._exec("UPDATE sessions SET expires_at = expires_at - 3600 WHERE user_id = ?", (vid,))   # signed in an hour ago
stale = vg.post("/api/account/delete", json={"password": "victim@example.com"}, headers=origin)
ok("delete from an hour-old Google session refused", stale.status_code == 403 and db.get_user(vid) is not None)
db._exec("UPDATE sessions SET expires_at = expires_at + 3600 WHERE user_id = ?", (vid,))
pw_user = TestClient(main.app)
db.create_user("pw@example.com", "a-long-password-2"); db.mark_verified(db.user_by_email("pw@example.com")["id"])
main.auth_limiter.hits.clear()
pw_user.post("/api/login", json={"email": "pw@example.com", "password": "a-long-password-2"}, headers=origin)
db._exec("UPDATE sessions SET expires_at = expires_at - 86400 WHERE user_id = ?", (db.user_by_email("pw@example.com")["id"],))
ok("password account can still delete from an old session with its password",
   pw_user.post("/api/account/delete", json={"password": "a-long-password-2"}, headers=origin).status_code == 200)
ok("delete with own email works", vg.post("/api/account/delete", json={"password": "Victim@Example.com"}, headers=origin).status_code == 200)
ok("account gone", db.user_by_email("victim@example.com") is None)

# reports survive account deletion, anonymously
main.report_limiter.hits.clear()
rg = TestClient(main.app)
google_login(rg, "sub-9", "reporter@example.com")
rg.post("/api/report", json={"target": "anon-check.example", "category": "other"}, headers={"Origin": "http://testserver"})
rid = db._one("SELECT user_id FROM reports WHERE host = 'anon-check.example'")
rg.post("/api/account/delete", json={"password": "reporter@example.com"}, headers=origin)
after = db._one("SELECT user_id FROM reports WHERE host = 'anon-check.example'")
ok("report keeps no link to a deleted account", rid["user_id"] is not None and after["user_id"] is None)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
