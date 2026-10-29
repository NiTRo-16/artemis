"""Artemis web server: serves the UI, runs passive scans, and handles optional accounts."""
import asyncio
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import google_auth
import jobs
import mail
import render
import store
from impersonation import check_impersonation
from payments import UPI_ID, is_upi, parse_upi, upi_report
from ratelimit import RateLimiter
from scanner import ScanError, normalize_domain, requested_path
from worker import record_history, run_job

ROOT = Path(__file__).parent
WAIT_FOR_SCAN = 50.0              # POST /api/scan waits this long for its job (the job itself stops at 45 s)
CHECK_TIMEOUT = 20.0
CHECK_CACHE_SECONDS = 6 * 3600
SESSION_COOKIE = "artemis_session"
OAUTH_COOKIE = "artemis_oauth"      # ties a Google sign-in to the browser that started it
MAX_BODY_BYTES = 64 * 1024        # largest accepted request body; every API body is tiny
MAX_CONCURRENT_CHECKS = 16        # extension checks at once
RECENT_SIGNIN_SECONDS = 15 * 60   # accounts without a password must have signed in this recently to delete
INLINE_SCANS = os.environ.get("ARTEMIS_INLINE_SCANS") == "1"   # run jobs in this process (tests, local dev without a worker)
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")   # all but tab and newline

# Sent on every response. Scripts come only from this site (the page's code is in /app.js);
# inline style attributes are allowed because the markup uses a few.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

log = logging.getLogger("artemis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()   # apply database migrations before the first request
    await jobs.ensure_group(store.async_client())
    app.state.mail_error = mail.config_problem() or google_auth.config_problem()
    if app.state.mail_error:
        log.error("Account email is not configured: %s", app.state.mail_error)
    elif not mail.SMTP_HOST:
        log.warning("No SMTP_HOST: account emails are printed to this log instead of sent (local development).")
    # Scans run in the worker processes, which check the sandboxed browser themselves. Only in inline mode
    # does this process run scans, and so need the browser check here.
    app.state.renderer_error = await render.self_test() if INLINE_SCANS else None
    if app.state.renderer_error:
        # Details go to the log only; /healthz is public and just reports "degraded".
        log.error("Headless browser self-test failed: %s", app.state.renderer_error)
    app.state.inline_jobs = set()
    yield
    if INLINE_SCANS:
        await render.shutdown()   # close the headless browser with the server


app = FastAPI(title="Artemis", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"   # account data and results never go in a shared cache
    elif request.url.path.startswith("/assets/") and response.status_code == 200:
        # Built files have a hash of their content in the name, so a new build always has new names.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response




class LimitBody:
    """Reject request bodies over MAX_BODY_BYTES, counting bytes as they arrive (chunked bodies included),
    so a huge upload can't be read into memory before validation rejects it."""

    def __init__(self, app, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.limit):
            return await self.reject(send)
        received = 0
        rejected = False        # we've answered 413 ourselves; drop whatever the app sends after
        response_started = False

        async def guarded_send(message):
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive():
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    if not response_started:
                        await self.reject(send)
                        rejected = True
                    return {"type": "http.disconnect"}   # stop the app reading any further
            return message

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not rejected:   # the app's own error; only swallow the fallout of our disconnect
                raise

    @staticmethod
    async def reject(send) -> None:
        body = json.dumps({"detail": "Request is too large."}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(LimitBody, limit=MAX_BODY_BYTES)


# ---------- rate limits (in Redis, shared by every process; see ratelimit.py) ----------

scan_limiter = RateLimiter("scan", 60.0)            # 10 scans a minute per visitor; 30 per account (60 per network)
auth_limiter = RateLimiter("auth", 600.0)           # 10 login or account-deletion attempts per 10 minutes per network
signup_limiter = RateLimiter("signup", 3600.0)      # 5 new accounts an hour per network
failed_login_limiter = RateLimiter("failed_login", 3600.0)   # 10 wrong passwords an hour per account, from anywhere
check_limiter = RateLimiter("check", 60.0)          # extension checks: 60 a minute per network
reset_limiter = RateLimiter("reset", 3600.0)        # 5 password-reset requests an hour per network
email_limiter = RateLimiter("email", 3600.0)        # 3 account emails an hour to any one address, so nobody gets flooded
report_limiter = RateLimiter("report", 3600.0)      # 10 site reports an hour per network
repeat_report_limiter = RateLimiter("repeat_report", 86400.0)   # one report a day per site per network; repeats aren't counted
share_limiter = RateLimiter("share", 3600.0)        # 30 shared results an hour per network
check_slots = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def client_key(request: Request) -> str:
    """Rate-limit key for a visitor. IPv6 users usually control a whole /64, so it counts as one."""
    ip = client_ip(request)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return ip


# ---------- accounts ----------

def current_user(request: Request):
    return db.user_for_session(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def require_same_origin(request: Request) -> None:
    """Refuse account changes started by another website (cross-site request forgery)."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Request came from another site.")


def start_session(request: Request, response: Response, user_id: int) -> None:
    response.set_cookie(SESSION_COOKIE, db.create_session(user_id), max_age=db.SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/")


def account_json(user) -> dict:
    return {"email": user["email"], "settings": db.get_settings(user), "has_password": db.has_password(user),
            "google": user["google_sub"] is not None}


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Settings(BaseModel):
    theme: Literal["system", "light", "dark"] = "system"
    same_tab: bool = False


class EmailOnly(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class TokenPassword(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=128)


def may_email(address: str) -> bool:
    """True (and counted) if another account email to this address is allowed within the hour."""
    key = address.strip().lower()
    if email_limiter.blocked(key, 3):
        return False
    email_limiter.record(key)
    return True


CHECK_EMAIL = {"status": "check_email"}


class Confirm(BaseModel):
    password: str = Field(min_length=1, max_length=254)   # an email address for accounts without a password


@app.post("/api/signup")
async def signup(body: Credentials, request: Request, response: Response) -> dict:
    require_same_origin(request)
    signup_limiter.check(client_key(request), 5, "Too many new accounts from your network. Try again later.")
    email = body.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if len(body.password) < 10:
        raise HTTPException(400, "Use a password of at least 10 characters.")
    db.purge_unverified()
    # The reply is the same whether or not the address is registered, so sign-up can't be used to
    # find out who has an account. Only the inbox owner learns which case it was.
    existing = db.user_by_email(email)
    if existing is None:
        try:
            user_id = await asyncio.to_thread(db.create_user, email, body.password)
            if may_email(email):
                mail.send_verification(email, db.create_email_token(user_id, "verify"))
            return CHECK_EMAIL
        except db.EmailTaken:            # registered a moment ago by a parallel request
            existing = db.user_by_email(email)
    await asyncio.to_thread(db.hash_password, body.password)   # same work as a new account: timing reveals nothing
    if existing is not None and may_email(email):
        if existing["email_verified"]:
            mail.send_already_registered(existing["email"])
        else:
            # Keep the password already set. Whoever owns the inbox must enter it to confirm, or use
            # "Forgot password", so nobody can pre-register someone else's address with their own password.
            mail.send_verification(existing["email"], db.create_email_token(existing["id"], "verify"))
    return CHECK_EMAIL


@app.post("/api/login")
async def login(body: Credentials, request: Request, response: Response) -> dict:
    require_same_origin(request)
    auth_limiter.check(client_key(request), 10, "Too many attempts. Try again in a few minutes.")
    account_key = body.email.strip().lower()
    if failed_login_limiter.blocked(account_key, 10):
        raise HTTPException(429, "Too many wrong passwords for this account. Try again in an hour.")
    user = await asyncio.to_thread(db.authenticate, body.email.strip(), body.password)
    if user is None:
        failed_login_limiter.record(account_key)
        raise HTTPException(401, "Email or password is incorrect.")
    if not user["email_verified"]:
        if may_email(user["email"]):
            mail.send_verification(user["email"], db.create_email_token(user["id"], "verify"))
        raise HTTPException(403, f"Confirm your email first. We've sent a new link to {user['email']}.")
    start_session(request, response, user["id"])
    return account_json(user)


@app.post("/api/verify")
async def verify_email(body: TokenPassword, request: Request, response: Response) -> dict:
    """Confirm an address from the emailed link. The password proves the person clicking chose it."""
    require_same_origin(request)
    auth_limiter.check(client_key(request), 10, "Too many attempts. Try again in a few minutes.")
    user = db.user_for_email_token(body.token, "verify")
    if user is None:
        raise HTTPException(400, "This link has expired or was already used. Log in to get a new one.")
    account_key = user["email"].lower()
    if failed_login_limiter.blocked(account_key, 10):
        raise HTTPException(429, "Too many wrong passwords for this account. Try again in an hour.")
    if not await asyncio.to_thread(db.verify_password, body.password, user["password_hash"]):
        failed_login_limiter.record(account_key)
        raise HTTPException(401, "That isn't the password this account was created with. "
                                 "If you didn't choose it, use Forgot password to set your own.")
    db.mark_verified(user["id"])
    db.use_email_tokens(user["id"], "verify")
    start_session(request, response, user["id"])
    return account_json(db.get_user(user["id"]))


@app.post("/api/password/forgot")
async def forgot_password(body: EmailOnly, request: Request) -> dict:
    require_same_origin(request)
    reset_limiter.check(client_key(request), 5, "Too many reset requests. Try again later.")
    email = body.email.strip()
    if EMAIL_RE.match(email):
        user = db.user_by_email(email)
        if user is not None and may_email(email):
            mail.send_reset(user["email"], db.create_email_token(user["id"], "reset"))
    return CHECK_EMAIL   # same reply either way, so this can't reveal who has an account


@app.post("/api/password/reset")
async def reset_password(body: TokenPassword, request: Request, response: Response) -> dict:
    require_same_origin(request)
    auth_limiter.check(client_key(request), 10, "Too many attempts. Try again in a few minutes.")
    if len(body.password) < 10:
        raise HTTPException(400, "Use a password of at least 10 characters.")
    user = db.consume_email_token(body.token, "reset")
    if user is None:
        raise HTTPException(400, "This reset link has expired or was already used. Ask for a new one.")
    await asyncio.to_thread(db.set_password, user["id"], body.password)
    db.mark_verified(user["id"])              # the link reached their inbox, which proves the address
    db.use_email_tokens(user["id"], "verify")
    db.end_all_sessions(user["id"])           # sign out everywhere, including anyone who knew the old password
    failed_login_limiter.forget(user["email"].lower())
    mail.send_password_changed(user["email"])
    start_session(request, response, user["id"])
    return account_json(db.get_user(user["id"]))


@app.post("/api/logout")
async def logout(request: Request, response: Response) -> dict:
    require_same_origin(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.end_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request) -> dict:
    user = current_user(request)
    return {"account": account_json(user) if user else None, "google_signin": google_auth.ENABLED}


# ---------- Google sign-in ----------

@app.get("/api/auth/google")
async def google_start(request: Request) -> RedirectResponse:
    if not google_auth.ENABLED:
        raise HTTPException(404, "Google sign-in isn't set up on this server.")
    auth_limiter.check(client_key(request), 10, "Too many attempts. Try again in a few minutes.")
    state, url = google_auth.start()
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(OAUTH_COOKIE, state, max_age=google_auth.STATE_SECONDS, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/api/auth/google")
    return response


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    """Where Google sends the browser back. Always redirects to the home page; `?signin=` says how it went."""
    if not google_auth.ENABLED:
        raise HTTPException(404, "Google sign-in isn't set up on this server.")

    def back(outcome: str | None) -> RedirectResponse:
        response = RedirectResponse(f"/?signin={outcome}" if outcome else "/", status_code=303)
        response.delete_cookie(OAUTH_COOKIE, path="/api/auth/google")
        return response

    if error:
        return back(None)   # the person cancelled on Google's screen
    auth_limiter.check(client_key(request), 10, "Too many attempts. Try again in a few minutes.")
    cookie = request.cookies.get(OAUTH_COOKIE, "")
    # The state must match the cookie set when this browser started, so nobody can finish a sign-in
    # they started for someone else (which would sign the victim into the attacker's account).
    if not state or not code or len(code) > 2048 or not hmac.compare_digest(state.encode(), cookie.encode()):
        return back("failed")
    try:
        google_id, email = await google_auth.finish(state, code)
    except google_auth.GoogleError as exc:
        log.warning("Google sign-in failed: %s", exc)
        return back("failed")
    result = db.google_user(google_id, email)
    if result is None:
        log.warning("Google sign-in refused: the email's account is linked to a different Google account")
        return back("failed")
    user_id, created = result
    response = back("new" if created else "ok")
    start_session(request, response, user_id)
    return response


@app.put("/api/settings")
async def put_settings(body: Settings, request: Request) -> dict:
    require_same_origin(request)
    user = require_user(request)
    db.save_settings(user["id"], body.model_dump())
    return body.model_dump()


@app.get("/api/history")
async def get_history(request: Request) -> dict:
    return {"scans": db.history(require_user(request)["id"])}


@app.delete("/api/history")
async def delete_history(request: Request) -> dict:
    require_same_origin(request)
    db.clear_history(require_user(request)["id"])
    return {"ok": True}


@app.post("/api/account/delete")
async def delete_account(body: Confirm, request: Request, response: Response) -> dict:
    require_same_origin(request)
    user = require_user(request)
    auth_limiter.check(client_key(request), 10, "Too many attempts. Try again in a few minutes.")
    if db.has_password(user):
        if not await asyncio.to_thread(db.verify_password, body.password, user["password_hash"]):
            raise HTTPException(401, "Password is incorrect.")
    else:
        # Google-only account: no password to ask for, so require a sign-in from the last few minutes
        # (someone at a computer left signed in can't do it) and the email typed out.
        if time.time() - user["signed_in_at"] > RECENT_SIGNIN_SECONDS:
            raise HTTPException(403, "For your security, log out and sign in with Google again, then delete your account.")
        if body.password.strip().lower() != user["email"].lower():
            raise HTTPException(401, "That isn't your account's email address.")
    db.delete_user(user["id"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------- scanning ----------

class ScanRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=2048)   # a domain or a full link


class ScanJobRequest(BaseModel):
    target: str = Field(min_length=1, max_length=2048)   # a domain, a full link or a UPI payment link


def limit_scans(request: Request, user) -> None:
    if user:
        # Per account, and per network so several accounts on one connection can't multiply the limit.
        scan_limiter.check(f"user:{user['id']}", 30, "Too many scans. Try again in a minute.")
        scan_limiter.check(f"net:{client_key(request)}", 60, "Too many scans from your network. Try again in a minute.")
    else:
        scan_limiter.check(client_key(request), 10, "Too many scans. Try again in a minute, or sign in for a higher limit.")


def check_upi(raw: str, user) -> dict:
    """A UPI link is read from the link itself (nothing is fetched), so it's answered straight away."""
    try:
        report = upi_report(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if user:
        record_history(user["id"], raw.strip(), report)
    return report


async def submit_scan(raw: str, user) -> tuple[str, bool]:
    """Queue a website scan, or find a recent result for it. Returns (job id, was cached)."""
    try:
        host, path = normalize_domain(raw), requested_path(raw)
    except ScanError as exc:
        raise HTTPException(400, str(exc))
    r = store.async_client()
    try:
        job_id, cached = await jobs.submit(r, raw.strip(), jobs.cache_key(host, path), user["id"] if user else None)
    except jobs.QueueFull:
        raise HTTPException(503, "Artemis is busy right now. Try again in a moment.")
    if cached and user:
        state = await jobs.state(r, job_id)
        await asyncio.to_thread(record_history, user["id"], raw.strip(), state["report"])
    if not cached and INLINE_SCANS:
        task = asyncio.create_task(run_inline(r))
        app.state.inline_jobs.add(task)
        task.add_done_callback(app.state.inline_jobs.discard)
    return job_id, cached


async def run_inline(r) -> None:
    """Inline mode: take the next job from the queue and run it in this process, as a worker would."""
    claimed = await jobs.claim(r, "inline", block_ms=None)
    if claimed is not None:
        entry_id, fields = claimed
        try:
            await run_job(r, fields["job"], fields)
        finally:
            await jobs.ack(r, entry_id)


async def job_state(job_id: str) -> dict:
    state = await jobs.state(store.async_client(), job_id) if JOB_ID.match(job_id) else None
    if state is None:
        raise HTTPException(404, "No such scan, or it has expired.")
    return state


def final_event(state: dict | None) -> dict:
    if state is not None and state["status"] == "done":
        return {"type": "done", "report": state["report"]}
    if state is not None and state["status"] == "error":
        return {"type": "error", "message": state["error"], "code": state["code"]}
    return {"type": "error", "message": "The scan result has expired.", "code": 410}


@app.post("/api/scans")
async def start_scan(body: ScanJobRequest, request: Request) -> JSONResponse:
    user = current_user(request)
    limit_scans(request, user)
    if is_upi(body.target):
        return JSONResponse({"id": None, "status": "done", "report": check_upi(body.target, user)})
    job_id, cached = await submit_scan(body.target, user)
    return JSONResponse({"id": job_id, "status": "done" if cached else "queued"}, status_code=200 if cached else 202)


@app.get("/api/scans/{job_id}")
async def get_scan(job_id: str) -> dict:
    return await job_state(job_id)


@app.get("/api/scans/{job_id}/events")
async def scan_events(job_id: str) -> StreamingResponse:
    """Live progress as server-sent events, ending with the report or an error."""
    state = await job_state(job_id)
    r = store.async_client()

    async def stream():
        if state["status"] in ("done", "error"):   # finished already: replay its steps, then the result
            for event in await jobs.past_events(r, job_id):
                if event["type"] == "step":
                    yield f"data: {json.dumps(event)}\n\n"
            yield f"data: {json.dumps(final_event(state))}\n\n"
            return
        async for event in jobs.events(r, job_id):
            if event["type"] in ("done", "error"):
                event = final_event(await jobs.state(r, job_id))
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/api/scans/{job_id}/share")
async def share_scan(job_id: str, request: Request) -> dict:
    share_limiter.check(client_key(request), 30, "Too many shared results from your network. Try again later.")
    state = await job_state(job_id)
    if state["status"] != "done":
        raise HTTPException(404, "Only a finished scan can be shared.")
    await asyncio.to_thread(db.share_result, job_id, state["report"])
    return {"url": f"/r/{job_id}"}


@app.get("/api/shared/{job_id}")
async def get_shared(job_id: str) -> dict:
    report = await asyncio.to_thread(db.shared_result, job_id) if JOB_ID.match(job_id) else None
    if report is None:
        raise HTTPException(404, "This shared result doesn't exist or has expired.")
    return report


@app.post("/api/scan")
async def run_scan(body: ScanRequest, request: Request) -> dict:
    """The original endpoint: queues the scan and waits for it, so the current page works unchanged."""
    user = current_user(request)
    limit_scans(request, user)
    if is_upi(body.domain):
        return check_upi(body.domain, user)
    job_id, _ = await submit_scan(body.domain, user)
    r = store.async_client()
    deadline = time.monotonic() + WAIT_FOR_SCAN
    while time.monotonic() < deadline:
        state = await jobs.state(r, job_id)
        if state and state["status"] == "done":
            return state["report"]
        if state and state["status"] == "error":
            raise HTTPException(state["code"], state["error"])
        await asyncio.sleep(0.25)
    raise HTTPException(504, "The scan timed out.")


# ---------- site reports ----------

class ReportRequest(BaseModel):
    target: str = Field(min_length=1, max_length=2048)   # the scanned domain, link or UPI ID
    category: Literal["phishing", "malware", "payment", "other"]
    details: str = Field(default="", max_length=1000)


@app.post("/api/report")
async def report_site(body: ReportRequest, request: Request) -> dict:
    """Save a report for the team to review. Reports never change a site's result by themselves."""
    require_same_origin(request)
    target = CONTROL_CHARS.sub("", body.target).strip()
    if is_upi(target):
        upi_id = parse_upi(target)[1].get("pa", "")
        if not UPI_ID.match(upi_id):
            raise HTTPException(400, "This UPI link has no valid UPI ID (the pa= part).")
        site = upi_id.lower()
    else:
        try:
            site = normalize_domain(target)
        except ScanError as exc:
            raise HTTPException(400, str(exc))
    key = client_key(request)
    report_limiter.check(key, 10, "Too many reports from your network. Try again later.")
    if repeat_report_limiter.blocked(f"{key}|{site}", 1):
        return {"ok": True}   # already reported today from here: thank them, but count it once
    repeat_report_limiter.record(f"{key}|{site}")
    user = current_user(request)
    db.add_report(target, site, body.category, CONTROL_CHARS.sub("", body.details).strip(),
                  user["id"] if user else None)
    return {"ok": True}


# ---------- browser extension ----------

class CheckRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=253)


@app.post("/api/check")
async def quick_check(body: CheckRequest, request: Request) -> dict:
    """Domain-only impersonation verdict for the browser extension: no page is loaded, results are cached."""
    check_limiter.check(client_key(request), 60, "Too many checks. Try again in a minute.")
    try:
        host = normalize_domain(body.domain)
    except ScanError as exc:
        raise HTTPException(400, str(exc))
    r = store.async_client()
    cached = await r.get(f"check:{host}")   # shared by every API process
    if cached:
        return json.loads(cached)
    if check_slots.locked():
        raise HTTPException(503, "Artemis is busy right now. Try again in a moment.")
    try:
        async with check_slots:
            imp = await asyncio.wait_for(check_impersonation(host), CHECK_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(504, "The check timed out.")
    result = {
        "domain": host,
        "level": imp["level"],
        "verdict": imp["verdict"],
        "summary": imp["summary"],
        "warnings": [s["text"] for s in imp["signals"] if s["tone"] in ("red", "amber")][:5],
    }
    await r.set(f"check:{host}", json.dumps(result), ex=CHECK_CACHE_SECONDS)
    return result


# ---------- pages and files ----------

WEB = ROOT / "web" / "dist"   # the React app, built by `npm run build` in web/

# Paths the app handles itself; each gets the app's index.html. (/verify and /reset are email links:
# the token is after "#", so it never reaches the server.)
APP_PAGES = ["/", "/verify", "/reset", "/history", "/messages", "/qr", "/watch", "/developers"]
FILES = {
    "/theme.js": WEB / "theme.js",
    "/favicon.svg": WEB / "favicon.svg",
    "/privacy": ROOT / "privacy.html",
    "/terms": ROOT / "terms.html",
    "/legal.css": ROOT / "legal.css",
}


def _serve(path: Path):
    # Tell browsers not to reuse a stored copy without checking, so visitors never run an outdated page.
    # (FileResponse sends the full file each time; pages are small, so that's fine.)
    return lambda: FileResponse(path, headers={"Cache-Control": "no-cache"})


# Windows reads these from the registry, which may lack or mislabel them; set them explicitly.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")

for route in APP_PAGES:
    app.add_api_route(route, _serve(WEB / "index.html"), methods=["GET"], include_in_schema=False)
for route, path in FILES.items():
    app.add_api_route(route, _serve(path), methods=["GET"], include_in_schema=False)


@app.get("/scan/{job_id}", include_in_schema=False)
async def result_page(job_id: str) -> FileResponse:
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


# The app's scripts, styles and fonts. Their names contain a hash of their content, so they can be cached for good.
app.mount("/assets", StaticFiles(directory=WEB / "assets", check_dir=False), name="assets")
app.mount("/fonts", StaticFiles(directory=ROOT / "fonts"), name="fonts")   # used by the privacy and terms pages


@app.get("/r/{job_id}", include_in_schema=False)
async def shared_page(job_id: str) -> FileResponse:
    # A shared result. The page loads the result itself from /api/shared/<id>.
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
async def healthz(request: Request) -> JSONResponse:
    """200 when the database, Redis, a scan worker (or, inline, this process's browser) and email settings
    work; 503 otherwise. The reason is in the server log, not here: this endpoint is public."""
    try:
        r = store.async_client()
        await r.ping()
        scanning = not request.app.state.renderer_error if INLINE_SCANS else await jobs.healthy_workers(r) > 0
        database = await asyncio.to_thread(db.ping)
    except Exception:
        log.exception("Health check failed")
        scanning = database = False
    healthy = scanning and database and not request.app.state.mail_error
    return JSONResponse({"status": "ok" if healthy else "degraded"}, status_code=200 if healthy else 503)
