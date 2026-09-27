"""SQLite storage for optional accounts (users, login sessions, scan history) and site reports.

Passwords are stored as scrypt hashes; session tokens only as SHA-256 hashes, so a copy of the
database can't be used to sign in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("ARTEMIS_DB", Path(__file__).parent / "data" / "artemis.db"))
SESSION_SECONDS = 30 * 24 * 3600
HISTORY_LIMIT = 200          # scans kept per account; older ones are deleted
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
DEFAULT_SETTINGS = {"theme": "system", "same_tab": False}
VERIFY_SECONDS = 24 * 3600         # email confirmation links
RESET_SECONDS = 3600               # password reset links
UNVERIFIED_SECONDS = 7 * 24 * 3600  # unconfirmed accounts are deleted after this
REPORT_SECONDS = 365 * 24 * 3600   # site reports are deleted after a year
REPORT_CATEGORIES = ("phishing", "malware", "payment", "other")
NO_PASSWORD = "none"   # password_hash of an account that signs in only with Google; matches no password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target TEXT NOT NULL,
    risk_score INTEGER,
    risk_label TEXT,
    verdict TEXT NOT NULL,
    scanned_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS scans_by_user ON scans(user_id, scanned_at DESC);
CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify', 'reset')),
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,
    host TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('phishing', 'malware', 'payment', 'other')),
    details TEXT NOT NULL DEFAULT '',
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS reports_by_host ON reports(host, created_at DESC);
"""

_lock = threading.RLock()   # re-entrant: conn() may be first called from inside a locked helper
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    """The shared connection. Call only while holding _lock (the helpers below do)."""
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute("PRAGMA journal_mode = WAL")
        _conn.executescript(SCHEMA)
        # Databases created before email verification or Google sign-in existed: add the columns.
        columns = {row["name"] for row in _conn.execute("PRAGMA table_info(users)")}
        if "email_verified" not in columns:
            _conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        if "google_sub" not in columns:
            _conn.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        _conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_by_google ON users(google_sub) "
                      "WHERE google_sub IS NOT NULL")
    return _conn


def init() -> None:
    """Create the database file and tables (called once at startup)."""
    with _lock:
        conn()


# One shared connection, so every statement runs *and its rows are read* while holding the lock.
# (Reading rows after releasing it let concurrent requests receive each other's results.)

def _exec(sql: str, params: tuple = ()) -> int:
    """Run a write; returns the new row id."""
    with _lock:
        return conn().execute(sql, params).lastrowid


def _one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return conn().execute(sql, params).fetchone()


def _all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, params).fetchall()


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
    _exec("DELETE FROM sessions WHERE expires_at < ?", (now,))
    _exec("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
         (_token_hash(token), user_id, now + SESSION_SECONDS))
    return token


def end_all_sessions(user_id: int) -> None:
    _exec("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def end_session(token: str) -> None:
    _exec("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_for_session(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    return _one("""SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE token_hash = ? AND expires_at > ?""", (_token_hash(token), int(time.time())))


# ---------- users ----------

class EmailTaken(Exception):
    pass


def create_user(email: str, password: str) -> int:
    try:
        return _exec("INSERT INTO users (email, password_hash, settings, created_at) VALUES (?, ?, ?, ?)",
                     (email, hash_password(password), json.dumps(DEFAULT_SETTINGS), int(time.time())))
    except sqlite3.IntegrityError:
        raise EmailTaken


def user_by_email(email: str) -> sqlite3.Row | None:
    return _one("SELECT * FROM users WHERE email = ?", (email,))


def has_password(user: sqlite3.Row) -> bool:
    return user["password_hash"] != NO_PASSWORD


# ---------- Google sign-in ----------

def user_by_google(sub: str) -> sqlite3.Row | None:
    return _one("SELECT * FROM users WHERE google_sub = ?", (sub,))


def google_user(sub: str, email: str) -> tuple[int, bool] | None:
    """The account for a Google identity whose email Google has verified: (user id, newly created).

    Signs in the account already linked to this Google ID, or links the account with this email,
    or creates one. None if the email belongs to an account linked to a *different* Google ID.
    An unconfirmed account holding the email is replaced: whoever created it never proved they own
    the inbox, and Google just proved this person does (so a pre-registered password can't linger).
    """
    with _lock:
        linked = user_by_google(sub)
        if linked is not None:
            return linked["id"], False
        existing = user_by_email(email)
        if existing is not None and existing["email_verified"]:
            if existing["google_sub"] is not None:
                return None
            _exec("UPDATE users SET google_sub = ? WHERE id = ?", (sub, existing["id"]))
            return existing["id"], False
        if existing is not None:
            delete_user(existing["id"])
        user_id = _exec("""INSERT INTO users (email, password_hash, settings, created_at, email_verified, google_sub)
                           VALUES (?, ?, ?, ?, 1, ?)""",
                        (email, NO_PASSWORD, json.dumps(DEFAULT_SETTINGS), int(time.time()), sub))
        return user_id, True


def set_password(user_id: int, password: str) -> None:
    _exec("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))


def mark_verified(user_id: int) -> None:
    _exec("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))


def purge_unverified() -> None:
    """Delete accounts whose email was never confirmed, so nobody can hold someone else's address."""
    _exec("DELETE FROM users WHERE email_verified = 0 AND created_at < ?", (int(time.time()) - UNVERIFIED_SECONDS,))


def get_user(user_id: int) -> sqlite3.Row | None:
    return _one("SELECT * FROM users WHERE id = ?", (user_id,))


def authenticate(email: str, password: str) -> sqlite3.Row | None:
    user = _one("SELECT * FROM users WHERE email = ?", (email,))
    if user is None or not has_password(user):
        verify_password(password, _DUMMY_HASH)   # same time taken whether or not the account exists
        return None
    return user if verify_password(password, user["password_hash"]) else None


def delete_user(user_id: int) -> None:
    _exec("DELETE FROM users WHERE id = ?", (user_id,))   # sessions and scans go with it (ON DELETE CASCADE)


def get_settings(user: sqlite3.Row) -> dict:
    try:
        stored = json.loads(user["settings"])
    except ValueError:
        stored = {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def save_settings(user_id: int, settings: dict) -> None:
    _exec("UPDATE users SET settings = ? WHERE id = ?", (json.dumps(settings), user_id))


# ---------- email links (confirm address, reset password) ----------

def create_email_token(user_id: int, purpose: str) -> str:
    """A single-use link token. Older unused tokens for the same purpose stop working."""
    token = secrets.token_urlsafe(32)
    ttl = VERIFY_SECONDS if purpose == "verify" else RESET_SECONDS
    now = int(time.time())
    _exec("DELETE FROM email_tokens WHERE expires_at < ? OR (user_id = ? AND purpose = ?)", (now, user_id, purpose))
    _exec("INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
          (_token_hash(token), user_id, purpose, now + ttl))
    return token


def user_for_email_token(token: str, purpose: str) -> sqlite3.Row | None:
    """The account a valid, unexpired token belongs to (the token isn't used up by this)."""
    return _one("""SELECT users.* FROM email_tokens JOIN users ON users.id = email_tokens.user_id
                   WHERE token_hash = ? AND purpose = ? AND expires_at > ?""",
                (_token_hash(token), purpose, int(time.time())))


def consume_email_token(token: str, purpose: str) -> sqlite3.Row | None:
    """Use up a valid token and return its account, atomically, so a link can't be redeemed twice at once."""
    with _lock:
        user = user_for_email_token(token, purpose)
        if user is not None:
            use_email_tokens(user["id"], purpose)
        return user


def use_email_tokens(user_id: int, purpose: str) -> None:
    """Invalidate every link of this kind for the account (called once one has been used)."""
    _exec("DELETE FROM email_tokens WHERE user_id = ? AND purpose = ?", (user_id, purpose))


# ---------- scan history ----------

def add_scan(user_id: int, target: str, risk_score: int | None, risk_label: str | None, verdict: str) -> None:
    _exec("INSERT INTO scans (user_id, target, risk_score, risk_label, verdict, scanned_at) VALUES (?, ?, ?, ?, ?, ?)",
         (user_id, target[:2048], risk_score, risk_label, verdict[:200], int(time.time())))
    _exec("""DELETE FROM scans WHERE user_id = ? AND id NOT IN
            (SELECT id FROM scans WHERE user_id = ? ORDER BY scanned_at DESC, id DESC LIMIT ?)""",
         (user_id, user_id, HISTORY_LIMIT))


def history(user_id: int) -> list[dict]:
    rows = _all("""SELECT target, risk_score, risk_label, verdict, scanned_at FROM scans
                   WHERE user_id = ? ORDER BY scanned_at DESC, id DESC""", (user_id,))
    return [dict(row) for row in rows]


def clear_history(user_id: int) -> None:
    _exec("DELETE FROM scans WHERE user_id = ?", (user_id,))


# ---------- site reports ----------

def add_report(target: str, host: str, category: str, details: str, user_id: int | None) -> None:
    now = int(time.time())
    _exec("DELETE FROM reports WHERE created_at < ?", (now - REPORT_SECONDS,))
    _exec("INSERT INTO reports (target, host, category, details, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
          (target[:2048], host[:320], category, details[:1000], user_id, now))


def reports(include_reviewed: bool = False, limit: int = 100) -> list[dict]:
    """Newest first, with how many reports the same site has had in total."""
    rows = _all(f"""SELECT r.id, r.target, r.host, r.category, r.details, r.created_at, r.reviewed,
                           (SELECT COUNT(*) FROM reports o WHERE o.host = r.host) AS reports_for_site
                    FROM reports r {'' if include_reviewed else 'WHERE r.reviewed = 0'}
                    ORDER BY r.created_at DESC, r.id DESC LIMIT ?""", (limit,))
    return [dict(row) for row in rows]


def mark_reports_reviewed(host: str) -> int:
    """Mark every report for a site reviewed; returns how many changed."""
    with _lock:
        return conn().execute("UPDATE reports SET reviewed = 1 WHERE host = ? AND reviewed = 0", (host,)).rowcount
