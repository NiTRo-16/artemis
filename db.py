"""Postgres storage for optional accounts (users, login sessions, scan history), site reports and shared
scan results.

Passwords are stored as scrypt hashes; session tokens only as SHA-256 hashes, so a copy of the
database can't be used to sign in. The schema lives in migrations/ and init() applies it in order.
"""
from __future__ import annotations

import atexit
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://artemis:artemis@127.0.0.1:5432/artemis")
MIGRATIONS = Path(__file__).parent / "migrations"
POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "10"))
MIGRATION_LOCK = 7310              # any constant: makes processes that start together apply migrations one at a time
SESSION_SECONDS = 30 * 24 * 3600
HISTORY_LIMIT = 200          # scans kept per account; older ones are deleted
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
DEFAULT_SETTINGS = {"theme": "system", "same_tab": False}
VERIFY_SECONDS = 24 * 3600         # email confirmation links
RESET_SECONDS = 3600               # password reset links
UNVERIFIED_SECONDS = 7 * 24 * 3600  # unconfirmed accounts are deleted after this
REPORT_SECONDS = 365 * 24 * 3600   # site reports are deleted after a year
SHARE_SECONDS = 30 * 24 * 3600     # shared scan results are deleted after 30 days
REPORT_CATEGORIES = ("phishing", "malware", "payment", "other")
NO_PASSWORD = "none"   # password_hash of an account that signs in only with Google; matches no password

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            # connect_timeout: without it, an address that accepts but never answers (on Windows, "localhost"
            # through Docker Desktop's IPv6 relay) hangs the pool instead of failing.
            _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=POOL_SIZE, open=True,
                                   kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 5})
            atexit.register(_pool.close)   # otherwise exit waits for the pool's threads and warns
        return _pool


def init() -> None:
    """Apply the migrations not applied yet. Called at startup; safe when several processes start at once."""
    with pool().connection() as c:
        c.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at BIGINT NOT NULL)")
            done = {row["name"] for row in c.execute("SELECT name FROM schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name not in done:
                    with c.transaction():
                        c.execute(path.read_text(encoding="utf-8"))
                        c.execute("INSERT INTO schema_migrations (name, applied_at) VALUES (%s, %s)",
                                  (path.name, int(time.time())))
        finally:
            c.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def ping() -> bool:
    return _one("SELECT 1 AS ok") is not None


def reset_for_tests() -> None:
    """Empty every table. Refuses unless the database name ends in _test, so it can't touch real data."""
    with pool().connection() as c:
        name = c.execute("SELECT current_database() AS name").fetchone()["name"]
        if not name.endswith("_test"):
            raise RuntimeError(f"reset_for_tests refused: {name!r} isn't a test database")
        c.execute("TRUNCATE users, sessions, scans, email_tokens, reports, shared_results RESTART IDENTITY CASCADE")


def _exec(sql: str, params: tuple = ()) -> int:
    """Run a write. Returns the new row's id for INSERT ... RETURNING id, otherwise the rows changed."""
    with pool().connection() as c:
        cur = c.execute(sql, params)
        return cur.fetchone()["id"] if cur.description else cur.rowcount


def _one(sql: str, params: tuple = ()) -> dict | None:
    with pool().connection() as c:
        return c.execute(sql, params).fetchone()


def _all(sql: str, params: tuple = ()) -> list[dict]:
    with pool().connection() as c:
        return c.execute(sql, params).fetchall()


# ---------- passwords and sessions ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# Compared against when an email isn't registered, so a login takes the same time either way.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    _exec("DELETE FROM sessions WHERE expires_at < %s", (now,))
    _exec("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
          (_token_hash(token), user_id, now + SESSION_SECONDS))
    return token


def end_all_sessions(user_id: int) -> None:
    _exec("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def end_session(token: str) -> None:
    _exec("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))


def user_for_session(token: str | None) -> dict | None:
    if not token:
        return None
    return _one("""SELECT users.*, sessions.expires_at - %s AS signed_in_at
                   FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE token_hash = %s AND expires_at > %s""", (SESSION_SECONDS, _token_hash(token), int(time.time())))


# ---------- users ----------

class EmailTaken(Exception):
    pass


def create_user(email: str, password: str) -> int:
    try:
        return _exec("INSERT INTO users (email, password_hash, settings, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
                     (email, hash_password(password), json.dumps(DEFAULT_SETTINGS), int(time.time())))
    except psycopg.errors.UniqueViolation:
        raise EmailTaken


def user_by_email(email: str) -> dict | None:
    return _one("SELECT * FROM users WHERE email = %s", (email,))


def has_password(user: dict) -> bool:
    return user["password_hash"] != NO_PASSWORD


# ---------- Google sign-in ----------

def user_by_google(sub: str) -> dict | None:
    return _one("SELECT * FROM users WHERE google_sub = %s", (sub,))


def google_user(sub: str, email: str) -> tuple[int, bool] | None:
    """The account for a Google identity whose email Google has verified: (user id, newly created).

    Signs in the account already linked to this Google ID, or links the account with this email,
    or creates one. None if the email belongs to an account linked to a *different* Google ID.
    An unconfirmed account holding the email is replaced: whoever created it never proved they own
    the inbox, and Google just proved this person does (so a pre-registered password can't linger).
    """
    with pool().connection() as c, c.transaction():
        # One sign-in at a time per address, so two parallel callbacks can't both create the account.
        c.execute("SELECT pg_advisory_xact_lock(hashtext(lower(%s)))", (email,))
        linked = c.execute("SELECT * FROM users WHERE google_sub = %s", (sub,)).fetchone()
        if linked is not None:
            return linked["id"], False
        existing = c.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
        if existing is not None and existing["email_verified"]:
            if existing["google_sub"] is not None:
                return None
            c.execute("UPDATE users SET google_sub = %s WHERE id = %s", (sub, existing["id"]))
            return existing["id"], False
        if existing is not None:
            c.execute("DELETE FROM users WHERE id = %s", (existing["id"],))
        row = c.execute("""INSERT INTO users (email, password_hash, settings, created_at, email_verified, google_sub)
                           VALUES (%s, %s, %s, %s, 1, %s) RETURNING id""",
                        (email, NO_PASSWORD, json.dumps(DEFAULT_SETTINGS), int(time.time()), sub)).fetchone()
        return row["id"], True


def set_password(user_id: int, password: str) -> None:
    _exec("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), user_id))


def mark_verified(user_id: int) -> None:
    _exec("UPDATE users SET email_verified = 1 WHERE id = %s", (user_id,))


def purge_unverified() -> None:
    """Delete accounts whose email was never confirmed, so nobody can hold someone else's address."""
    _exec("DELETE FROM users WHERE email_verified = 0 AND created_at < %s", (int(time.time()) - UNVERIFIED_SECONDS,))


def get_user(user_id: int) -> dict | None:
    return _one("SELECT * FROM users WHERE id = %s", (user_id,))


def authenticate(email: str, password: str) -> dict | None:
    user = _one("SELECT * FROM users WHERE email = %s", (email,))
    if user is None or not has_password(user):
        verify_password(password, _DUMMY_HASH)   # same time taken whether or not the account exists
        return None
    return user if verify_password(password, user["password_hash"]) else None


def delete_user(user_id: int) -> None:
    _exec("DELETE FROM users WHERE id = %s", (user_id,))   # sessions and scans go with it (ON DELETE CASCADE)


def get_settings(user: dict) -> dict:
    try:
        stored = json.loads(user["settings"])
    except ValueError:
        stored = {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def save_settings(user_id: int, settings: dict) -> None:
    _exec("UPDATE users SET settings = %s WHERE id = %s", (json.dumps(settings), user_id))


# ---------- email links (confirm address, reset password) ----------

def create_email_token(user_id: int, purpose: str) -> str:
    """A single-use link token. Older unused tokens for the same purpose stop working."""
    token = secrets.token_urlsafe(32)
    ttl = VERIFY_SECONDS if purpose == "verify" else RESET_SECONDS
    now = int(time.time())
    _exec("DELETE FROM email_tokens WHERE expires_at < %s OR (user_id = %s AND purpose = %s)", (now, user_id, purpose))
    _exec("INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) VALUES (%s, %s, %s, %s)",
          (_token_hash(token), user_id, purpose, now + ttl))
    return token


def user_for_email_token(token: str, purpose: str) -> dict | None:
    """The account a valid, unexpired token belongs to (the token isn't used up by this)."""
    return _one("""SELECT users.* FROM email_tokens JOIN users ON users.id = email_tokens.user_id
                   WHERE token_hash = %s AND purpose = %s AND expires_at > %s""",
                (_token_hash(token), purpose, int(time.time())))


def consume_email_token(token: str, purpose: str) -> dict | None:
    """Use up a valid token and return its account, atomically, so a link can't be redeemed twice at once."""
    with pool().connection() as c, c.transaction():
        # FOR UPDATE makes a second, simultaneous redemption wait, then find the token gone.
        user = c.execute("""SELECT users.* FROM email_tokens JOIN users ON users.id = email_tokens.user_id
                            WHERE token_hash = %s AND purpose = %s AND expires_at > %s
                            FOR UPDATE OF email_tokens""",
                         (_token_hash(token), purpose, int(time.time()))).fetchone()
        if user is not None:
            c.execute("DELETE FROM email_tokens WHERE user_id = %s AND purpose = %s", (user["id"], purpose))
        return user


def use_email_tokens(user_id: int, purpose: str) -> None:
    """Invalidate every link of this kind for the account (called once one has been used)."""
    _exec("DELETE FROM email_tokens WHERE user_id = %s AND purpose = %s", (user_id, purpose))


# ---------- scan history ----------

def add_scan(user_id: int, target: str, risk_score: int | None, risk_label: str | None, verdict: str) -> None:
    _exec("INSERT INTO scans (user_id, target, risk_score, risk_label, verdict, scanned_at) VALUES (%s, %s, %s, %s, %s, %s)",
          (user_id, target[:2048], risk_score, risk_label, verdict[:200], int(time.time())))
    _exec("""DELETE FROM scans WHERE user_id = %s AND id NOT IN
             (SELECT id FROM scans WHERE user_id = %s ORDER BY scanned_at DESC, id DESC LIMIT %s)""",
          (user_id, user_id, HISTORY_LIMIT))


def history(user_id: int) -> list[dict]:
    return _all("""SELECT target, risk_score, risk_label, verdict, scanned_at FROM scans
                   WHERE user_id = %s ORDER BY scanned_at DESC, id DESC""", (user_id,))


def clear_history(user_id: int) -> None:
    _exec("DELETE FROM scans WHERE user_id = %s", (user_id,))


# ---------- site reports ----------

def add_report(target: str, host: str, category: str, details: str, user_id: int | None) -> None:
    now = int(time.time())
    _exec("DELETE FROM reports WHERE created_at < %s", (now - REPORT_SECONDS,))
    _exec("INSERT INTO reports (target, host, category, details, user_id, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
          (target[:2048], host[:320], category, details[:1000], user_id, now))


def reports(include_reviewed: bool = False, limit: int = 100) -> list[dict]:
    """Newest first, with how many reports the same site has had in total."""
    return _all(f"""SELECT r.id, r.target, r.host, r.category, r.details, r.created_at, r.reviewed,
                           (SELECT COUNT(*) FROM reports o WHERE o.host = r.host) AS reports_for_site
                    FROM reports r {'' if include_reviewed else 'WHERE r.reviewed = 0'}
                    ORDER BY r.created_at DESC, r.id DESC LIMIT %s""", (limit,))


def mark_reports_reviewed(host: str) -> int:
    """Mark every report for a site reviewed; returns how many changed."""
    return _exec("UPDATE reports SET reviewed = 1 WHERE host = %s AND reviewed = 0", (host,))


# ---------- shared scan results ----------

def share_result(result_id: str, report: dict) -> None:
    """Keep a scan result someone chose to share, for SHARE_SECONDS. Sharing it again changes nothing."""
    now = int(time.time())
    _exec("DELETE FROM shared_results WHERE expires_at < %s", (now,))
    _exec("""INSERT INTO shared_results (id, report, created_at, expires_at) VALUES (%s, %s, %s, %s)
             ON CONFLICT (id) DO NOTHING""", (result_id, Jsonb(report), now, now + SHARE_SECONDS))


def shared_result(result_id: str) -> dict | None:
    row = _one("SELECT report FROM shared_results WHERE id = %s AND expires_at > %s", (result_id, int(time.time())))
    return row and row["report"]
