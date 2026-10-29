# Scalable Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move scans out of the web request into a Redis-backed job queue run by separate worker processes, move accounts from SQLite to Postgres and shared state (rate limits, caches) to Redis, so Artemis can run many API and worker processes side by side.

**Architecture:** The API (FastAPI, several uvicorn workers) validates a scan, adds it to a Redis stream and returns a job id. Worker processes take jobs through a consumer group, run the existing scanner with its sandboxed browser, and stream progress events to Redis, which the API relays to the browser with Server-Sent Events. Postgres holds accounts, history, reports and shared results; Redis holds the queue, progress, results for 24 hours, a 15-minute result cache and rate limits.

**Tech Stack:** Python 3.12, FastAPI, redis-py (sync and asyncio), Redis 7 Streams, psycopg 3 with psycopg_pool, Postgres 17, fakeredis for tests, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-29-scalable-backend-design.md`

## Global Constraints

- Keep every existing endpoint and its behaviour working: `POST /api/scan`, `POST /api/check`, accounts, history, reports, Google sign-in. The current page and the browser extension must not change.
- Same rate-limit numbers and messages as today (`main.py:188-196`).
- Redis runs with `--save "" --appendonly no`; rate-limit keys are HMACs, never raw IP addresses or emails.
- Results are kept 24 hours in Redis; only results someone shares are kept longer (30 days, Postgres).
- Scan timeout 45 s inside a job; a job unacknowledged for 90 s is retried by another worker, at most 2 attempts in total.
- Queue cap: 200 waiting or running jobs; beyond that the API answers 503 "Artemis is busy right now. Try again in a moment."
- Result cache: 15 minutes per normalised target (host plus path).
- Tests are plain scripts in `tests/` (the project's existing style: an `ok(label, cond)` helper, a pass count at the end), run from the project root with `PYTHONPATH=.`.
- Pin every new dependency to an exact version in `requirements.txt`, as the file already does.
- Copy rules for any user-facing text: plain language, no em dashes.
- Development runs Redis and Postgres from `docker-compose.dev.yml` on Docker Desktop (Task 1).

## File map

| File | Responsibility |
|---|---|
| `docker-compose.dev.yml`, `deploy/dev-initdb.sql` | Local Redis and Postgres (with an `artemis_test` database) for development and tests |
| `store.py` | Redis connections: one sync client, one asyncio client per event loop; `fake://` for tests |
| `migrations/001_initial.sql` | Postgres schema |
| `db.py` | Same functions as today, on Postgres; plus `ping`, `reset_for_tests`, `share_result`, `shared_result` |
| `tools/migrate_sqlite.py` | One-off copy of the live SQLite data into Postgres |
| `ratelimit.py` | `RateLimiter` on Redis (moved out of `main.py`) |
| `scanner.py` | `scan(raw, progress=None)`: reports each check as it finishes |
| `jobs.py` | Queue, job state, progress events, result cache, worker heartbeats |
| `worker.py` | `run_job` (shared with the API's inline mode) and the worker loop |
| `main.py` | New `/api/scans` endpoints, SSE, sharing; `/api/scan` and `/api/check` rebuilt on the queue and Redis |
| `tests/testenv.py` | Test settings shared by all suites |
| `docker-compose.yml`, `Dockerfile`, `.env.example`, `deploy/local.env`, `DEPLOY.md`, `privacy.html` | Deployment |
| `loadtest/run.py`, `docker-compose.loadtest.yml`, `docs/load-test.md` | Load test and results |

---

### Task 1: Local Redis and Postgres, new dependencies, Redis connections

**Files:**
- Create: `docker-compose.dev.yml`, `deploy/dev-initdb.sql`, `requirements-dev.txt`, `store.py`, `tests/test_store.py`
- Modify: `requirements.txt` (append)

**Interfaces:**
- Produces: `store.sync_client() -> redis.Redis`, `store.async_client() -> redis.asyncio.Redis` (both `decode_responses=True`), env `REDIS_URL` (default `redis://localhost:6379/0`; `fake://` = in-memory fakeredis shared by both clients).

- [ ] **Step 1: Write `docker-compose.dev.yml`**

```yaml
# Redis and Postgres for development and tests, reachable only from this computer.
#   docker compose -f docker-compose.dev.yml up -d
services:
  redis:
    image: redis:7
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    ports: ["127.0.0.1:6379:6379"]
  postgres:
    image: postgres:17
    environment:
      POSTGRES_USER: artemis
      POSTGRES_PASSWORD: artemis
      POSTGRES_DB: artemis
    ports: ["127.0.0.1:5432:5432"]
    volumes:
      - ./deploy/dev-initdb.sql:/docker-entrypoint-initdb.d/dev-initdb.sql:ro
      - dev_pg:/var/lib/postgresql/data
volumes:
  dev_pg:
```

- [ ] **Step 2: Write `deploy/dev-initdb.sql`**

```sql
-- Development only: a second database the test suites may empty freely.
CREATE DATABASE artemis_test OWNER artemis;
```

- [ ] **Step 3: Start the services and check them**

Run: `docker compose -f docker-compose.dev.yml up -d && docker compose -f docker-compose.dev.yml exec postgres psql -U artemis -c "\l" && docker compose -f docker-compose.dev.yml exec redis redis-cli ping`
Expected: the database list includes `artemis` and `artemis_test`; Redis prints `PONG`.

- [ ] **Step 4: Install the libraries and pin them**

Run: `.venv/Scripts/python -m pip install redis "psycopg[binary]" psycopg-pool fakeredis && .venv/Scripts/python -m pip show redis psycopg psycopg-binary psycopg-pool fakeredis | grep -E "^(Name|Version)"`

Append to `requirements.txt`, using the versions printed (format `name==version`):

```
# Redis (job queue, progress, caches, rate limits) and Postgres (accounts, history, reports)
redis==<version printed>
psycopg==<version printed>
psycopg-binary==<version printed>
psycopg-pool==<version printed>
```

Create `requirements-dev.txt`:

```
# Tests only
-r requirements.txt
fakeredis==<version printed>
```

- [ ] **Step 5: Write the failing test `tests/test_store.py`**

```python
"""Redis connection helpers, against the in-memory fake."""
import asyncio
import os

os.environ["REDIS_URL"] = "fake://"
import store  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


store.sync_client().set("k", "v")
ok("sync client works", store.sync_client().get("k") == "v")


async def read():
    return await store.async_client().get("k")

ok("async client sees the same data", asyncio.run(read()) == "v")


async def same_twice():
    return store.async_client() is store.async_client()

ok("one async client per event loop", asyncio.run(same_twice()))
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 6: Run it to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_store.py`
Expected: `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 7: Write `store.py`**

```python
"""Shared Redis connections: one synchronous client (rate limits) and one asyncio client per event loop
(job queue, live progress, caches).

REDIS_URL=fake:// uses an in-memory fake (fakeredis), for tests that don't need a real Redis.
"""
from __future__ import annotations

import asyncio
import os
import weakref

import redis
import redis.asyncio

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_sync: redis.Redis | None = None
_async: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.asyncio.Redis]" = weakref.WeakKeyDictionary()
_fake_server = None


def _fake_server_instance():
    global _fake_server
    import fakeredis
    if _fake_server is None:
        _fake_server = fakeredis.FakeServer()
    return _fake_server


def sync_client() -> redis.Redis:
    global _sync
    if _sync is None:
        if REDIS_URL.startswith("fake://"):
            import fakeredis
            _sync = fakeredis.FakeRedis(server=_fake_server_instance(), decode_responses=True)
        else:
            _sync = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    return _sync


def async_client() -> redis.asyncio.Redis:
    """The asyncio client for the running event loop (one client can't be shared between loops)."""
    loop = asyncio.get_running_loop()
    client = _async.get(loop)
    if client is None:
        if REDIS_URL.startswith("fake://"):
            import fakeredis
            client = fakeredis.FakeAsyncRedis(server=_fake_server_instance(), decode_responses=True)
        else:
            # Longer than the longest blocking read (5 s), so a quiet queue isn't taken for a dead connection.
            client = redis.asyncio.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=10,
                                                  socket_connect_timeout=2)
        _async[loop] = client
    return client
```

- [ ] **Step 8: Run the test to see it pass**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_store.py`
Expected: `3/3 passed`

- [ ] **Step 9: Commit**

```bash
git add docker-compose.dev.yml deploy/dev-initdb.sql requirements.txt requirements-dev.txt store.py tests/test_store.py
git commit -m "Add local Redis and Postgres for development, and shared Redis connections"
```

---

### Task 2: Postgres database layer

**Files:**
- Create: `migrations/001_initial.sql`, `tests/testenv.py`
- Modify: `db.py` (rewrite), `tests/regress.py:1-15`, `tests/test_email.py:1-15`, `tests/test_features.py:1-18`, `tests/test_features.py:252,255,260`, `tests/test_email.py:141,163`

**Interfaces:**
- Consumes: env `DATABASE_URL` (default `postgresql://artemis:artemis@127.0.0.1:5432/artemis`).
- Produces: every existing `db` function with the same name, parameters and return shape (rows are `dict`s); new `db.ping() -> bool`, `db.reset_for_tests() -> None`, `db.share_result(result_id: str, report: dict) -> None`, `db.shared_result(result_id: str) -> dict | None`, `db.pool() -> ConnectionPool`, `db.SHARE_SECONDS`. SQL placeholders are `%s`.

- [ ] **Step 1: Write `migrations/001_initial.sql`**

```sql
-- Accounts, sign-in sessions, scan history, email links, site reports and shared scan results.
-- Times are Unix seconds, as in the SQLite version. Booleans stay 0/1 integers so the code is unchanged.
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    email CITEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    created_at BIGINT NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    google_sub TEXT UNIQUE
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at BIGINT NOT NULL
);
CREATE INDEX sessions_by_user ON sessions(user_id);

CREATE TABLE scans (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target TEXT NOT NULL,
    risk_score INTEGER,
    risk_label TEXT,
    verdict TEXT NOT NULL,
    scanned_at BIGINT NOT NULL
);
CREATE INDEX scans_by_user ON scans(user_id, scanned_at DESC);

CREATE TABLE email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify', 'reset')),
    expires_at BIGINT NOT NULL
);

CREATE TABLE reports (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    target TEXT NOT NULL,
    host TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('phishing', 'malware', 'payment', 'other')),
    details TEXT NOT NULL DEFAULT '',
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at BIGINT NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX reports_by_host ON reports(host, created_at DESC);

CREATE TABLE shared_results (
    id TEXT PRIMARY KEY,
    report JSONB NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL
);
CREATE INDEX shared_results_by_expiry ON shared_results(expires_at);
```

- [ ] **Step 2: Write `tests/testenv.py`**

```python
"""Settings shared by the test suites: a throwaway Postgres database, emptied before each suite.

Import it first in every suite. Needs docker-compose.dev.yml running.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://artemis:artemis@127.0.0.1:5432/artemis_test")

import db  # noqa: E402

db.init()
db.reset_for_tests()
```

- [ ] **Step 3: Point the three suites at it**

In `tests/regress.py`, `tests/test_email.py` and `tests/test_features.py`, delete the SQLite reset loop:

```python
for suffix in ("", "-wal", "-shm"):
    pathlib.Path(os.environ["ARTEMIS_DB"] + suffix).unlink(missing_ok=True)
```

and put this as the first import after the module docstring (before any other project import, and in `test_features.py` after its `os.environ[...] = ...` lines):

```python
import testenv  # noqa: F401  (test database; must come before importing the app)
```

Remove `import pathlib` where nothing else uses it. Then change the SQL placeholders in the direct database calls from `?` to `%s`:
- `tests/test_features.py:252`, `:255`, `:260`: `... WHERE user_id = %s"`
- `tests/test_email.py:141`: `"UPDATE email_tokens SET expires_at = %s WHERE purpose = 'reset'"`
- `tests/test_email.py:163`: `"UPDATE users SET created_at = %s WHERE email = %s"`

- [ ] **Step 4: Run a suite to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_email.py`
Expected: fails at `db.reset_for_tests()` with `AttributeError: module 'db' has no attribute 'reset_for_tests'`.

- [ ] **Step 5: Rewrite `db.py`**

```python
"""Postgres storage for optional accounts (users, login sessions, scan history), site reports and shared
scan results.

Passwords are stored as scrypt hashes; session tokens only as SHA-256 hashes, so a copy of the
database can't be used to sign in. The schema lives in migrations/ and init() applies it in order.
"""
from __future__ import annotations

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

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://artemis:artemis@localhost:5432/artemis")
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
            _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=POOL_SIZE, open=True,
                                   kwargs={"row_factory": dict_row, "autocommit": True})
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
```

- [ ] **Step 6: Run the three suites**

Run: `for t in regress test_email test_features; do PYTHONPATH=. .venv/Scripts/python tests/$t.py | tail -1; done`
Expected: `test_email` 32/32, `test_features` 70/70; `regress` 24/25 (the one failure is "scan while signed in", which scans the real example.com and failed before this change too).

- [ ] **Step 7: Check `reports.py` (the review tool) still works**

Run: `PYTHONPATH=. DATABASE_URL=postgresql://artemis:artemis@127.0.0.1:5432/artemis_test .venv/Scripts/python reports.py --all`
Expected: prints the report list (or "No reports") without an error.

- [ ] **Step 8: Commit**

```bash
git add migrations/001_initial.sql db.py tests/testenv.py tests/regress.py tests/test_email.py tests/test_features.py
git commit -m "Move accounts, history and reports from SQLite to Postgres"
```

---

### Task 3: Copying the live SQLite data into Postgres

**Files:**
- Create: `tools/migrate_sqlite.py`, `tests/test_migrate.py`

**Interfaces:**
- Consumes: `db.init()`, `db.pool()`, `db._one`, `db.authenticate`, `db.history`, `db.create_user`, `db.reset_for_tests`.
- Produces: `python tools/migrate_sqlite.py <path to artemis.db>`; `tools.migrate_sqlite.main(path: str) -> None`.

- [ ] **Step 1: Write the failing test `tests/test_migrate.py`**

```python
"""Copying an old SQLite database into Postgres."""
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import testenv  # noqa: F401
import db  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import migrate_sqlite  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


OLD_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
                    settings TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL, email_verified INTEGER NOT NULL DEFAULT 0,
                    google_sub TEXT);
CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE scans (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, target TEXT NOT NULL, risk_score INTEGER,
                    risk_label TEXT, verdict TEXT NOT NULL, scanned_at INTEGER NOT NULL);
CREATE TABLE email_tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, purpose TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE reports (id INTEGER PRIMARY KEY, target TEXT NOT NULL, host TEXT NOT NULL, category TEXT NOT NULL,
                      details TEXT NOT NULL DEFAULT '', user_id INTEGER, created_at INTEGER NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0);
"""
now = int(time.time())
path = Path(tempfile.mkdtemp()) / "old.db"
old = sqlite3.connect(path)
old.executescript(OLD_SCHEMA)
old.execute("INSERT INTO users VALUES (7, 'asha@example.com', ?, '{}', ?, 1, NULL)", (db.hash_password("a-long-password-1"), now))
old.execute("INSERT INTO sessions VALUES ('abc', 7, ?)", (now + 3600,))
old.execute("INSERT INTO scans VALUES (3, 7, 'github.com', 5, 'Low', 'Official GitHub domain', ?)", (now,))
old.execute("INSERT INTO reports VALUES (4, 'bad.example', 'bad.example', 'phishing', '', 7, ?, 0)", (now,))
old.commit()
old.close()

migrate_sqlite.main(str(path))
ok("password still works after copying", db.authenticate("asha@example.com", "a-long-password-1") is not None)
ok("history copied", [s["target"] for s in db.history(7)] == ["github.com"])
ok("report copied", db._one("SELECT COUNT(*) AS n FROM reports")["n"] == 1)
ok("new accounts get ids after the copied ones", db.create_user("new@example.com", "a-long-password-2") > 7)
try:
    migrate_sqlite.main(str(path))
    ok("refuses to copy twice", False)
except SystemExit:
    ok("refuses to copy twice", True)
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_migrate.py`
Expected: `ModuleNotFoundError: No module named 'migrate_sqlite'`

- [ ] **Step 3: Write `tools/migrate_sqlite.py`**

```python
"""Copy accounts, sign-in sessions, scan history, email links and site reports from the old SQLite database
into Postgres. Run it once, when moving to Postgres:

    python tools/migrate_sqlite.py /app/data/artemis.db

It refuses to run if Postgres already has accounts, so nothing can be copied twice.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

# Parents before children, so foreign keys are satisfied as rows arrive.
TABLES = {
    "users": ["id", "email", "password_hash", "settings", "created_at", "email_verified", "google_sub"],
    "sessions": ["token_hash", "user_id", "expires_at"],
    "scans": ["id", "user_id", "target", "risk_score", "risk_label", "verdict", "scanned_at"],
    "email_tokens": ["token_hash", "user_id", "purpose", "expires_at"],
    "reports": ["id", "target", "host", "category", "details", "user_id", "created_at", "reviewed"],
}


def main(path: str) -> None:
    if not Path(path).exists():
        sys.exit(f"No SQLite database at {path}")
    db.init()
    if db._one("SELECT COUNT(*) AS n FROM users")["n"]:
        sys.exit("Postgres already has accounts, so nothing was copied.")
    source = sqlite3.connect(path)
    with db.pool().connection() as c, c.transaction():
        for table, columns in TABLES.items():
            present = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
            cols = [col for col in columns if col in present]   # older databases lack some columns
            rows = source.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            if rows:
                with c.cursor() as cur:
                    cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                                    rows)
            print(f"{table}: {len(rows)} rows copied")
        for table in ("users", "scans", "reports"):   # new rows continue numbering after the copied ids
            c.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 0) + 1, false) FROM {table}")
    source.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_migrate.py`
Expected: `5/5 passed`

- [ ] **Step 5: Commit**

```bash
git add tools/migrate_sqlite.py tests/test_migrate.py
git commit -m "Add a one-off tool to copy the SQLite data into Postgres"
```

---

### Task 4: Rate limits in Redis

**Files:**
- Create: `ratelimit.py`, `tests/test_ratelimit.py`
- Modify: `main.py:10` (imports), `main.py:154-196` (limiter class and instances), `tests/testenv.py`, `tests/regress.py`, `tests/test_email.py:27-29`, `tests/test_features.py` (every `.hits.clear()`)

**Interfaces:**
- Consumes: `store.sync_client()`; env `RATE_LIMIT_SECRET`, `RATE_LIMIT_MULTIPLIER` (default 1, load tests only).
- Produces: `ratelimit.RateLimiter(name: str, window: float)` with `.blocked(key, limit) -> bool`, `.record(key) -> None`, `.check(key, limit, message) -> None` (raises `HTTPException(429, message)`), `.reset() -> None`. `main.py` keeps the names `scan_limiter`, `auth_limiter`, ... and gains `share_limiter`.

- [ ] **Step 1: Write the failing test `tests/test_ratelimit.py`**

```python
"""Rate limits shared through Redis (the in-memory fake here)."""
import os
import time

os.environ["REDIS_URL"] = "fake://"
os.environ["RATE_LIMIT_SECRET"] = "test-secret"
from fastapi import HTTPException  # noqa: E402

import store  # noqa: E402
from ratelimit import RateLimiter  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def refused(limiter, key, limit):
    try:
        limiter.check(key, limit, "slow down")
        return False
    except HTTPException as exc:
        return exc.status_code == 429 and exc.detail == "slow down"


rl = RateLimiter("test", 60.0)
for _ in range(3):
    rl.check("203.0.113.5", 3, "slow down")
ok("fourth hit within the window is refused", refused(rl, "203.0.113.5", 3))
ok("another visitor has their own count", not refused(rl, "198.51.100.7", 3))
ok("Redis never holds the address itself", not any("203.0.113.5" in k for k in store.sync_client().keys("*")))
ok("keys expire on their own", all(0 < store.sync_client().ttl(k) <= 60 for k in store.sync_client().keys("rl:test:*")))
rl.reset()
ok("reset clears every key", not refused(rl, "203.0.113.5", 3))

short = RateLimiter("short", 0.3)
short.check("k", 1, "x")
ok("blocked inside the window", short.blocked("k", 1))
time.sleep(0.4)
ok("allowed again once the window passes", not short.blocked("k", 1))

second = RateLimiter("test", 60.0)   # what another API process would create
rl.check("shared", 1, "x")
ok("another process sees the same count", second.blocked("shared", 1))
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_ratelimit.py`
Expected: `ModuleNotFoundError: No module named 'ratelimit'`

- [ ] **Step 3: Write `ratelimit.py`**

```python
"""Rate limits shared by every API process, kept in Redis.

Keys are HMACs of what's being limited (a network address, an account, an email address), so Redis never
holds the address itself, and each key expires once it has been idle for its window. Redis runs without
writing to disk, which keeps the privacy policy's promise that IP addresses stay in memory.

The sync client is used on purpose: each check is two short round trips to Redis on the same machine,
and keeping it synchronous leaves every call site in main.py unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets
import time

from fastapi import HTTPException

import store

SECRET = os.environ.get("RATE_LIMIT_SECRET", "development-only-secret").encode()
MULTIPLIER = int(os.environ.get("RATE_LIMIT_MULTIPLIER", "1"))   # raised only by docker-compose.loadtest.yml


class RateLimiter:
    """At most `limit` hits per key within `window` seconds (a sliding window)."""

    def __init__(self, name: str, window: float) -> None:
        self.name = name
        self.window = window

    def _key(self, key: str) -> str:
        return f"rl:{self.name}:" + hmac.new(SECRET, key.encode(), hashlib.sha256).hexdigest()[:32]

    def blocked(self, key: str, limit: int) -> bool:
        k, now = self._key(key), time.time()
        pipe = store.sync_client().pipeline()
        pipe.zremrangebyscore(k, 0, now - self.window)
        pipe.zcard(k)
        return pipe.execute()[1] >= limit * MULTIPLIER

    def record(self, key: str) -> None:
        k, now = self._key(key), time.time()
        pipe = store.sync_client().pipeline()
        pipe.zadd(k, {f"{now}:{secrets.token_hex(4)}": now})
        pipe.expire(k, math.ceil(self.window))
        pipe.execute()

    def check(self, key: str, limit: int, message: str) -> None:
        """Count a hit, or refuse with 429 if the key is already at its limit."""
        if self.blocked(key, limit):
            raise HTTPException(429, message)
        self.record(key)

    def reset(self) -> None:
        """Forget every key of this limiter (used by tests)."""
        client = store.sync_client()
        for k in client.scan_iter(f"rl:{self.name}:*"):
            client.delete(k)
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_ratelimit.py`
Expected: `8/8 passed`

- [ ] **Step 5: Use it in `main.py`**

Delete the `class RateLimiter` block (`main.py:156-185`) and replace the limiter instances with:

```python
from ratelimit import RateLimiter

scan_limiter = RateLimiter("scan", 60.0)            # 10 scans a minute per visitor; 30 per account (60 per network)
auth_limiter = RateLimiter("auth", 600.0)           # 10 login or account-deletion attempts per 10 minutes per network
signup_limiter = RateLimiter("signup", 3600.0)      # 5 new accounts an hour per network
failed_login_limiter = RateLimiter("failed_login", 3600.0)   # 10 wrong passwords an hour per account, from anywhere
check_limiter = RateLimiter("check", 60.0)          # extension checks: 60 a minute per network
reset_limiter = RateLimiter("reset", 3600.0)        # 5 password-reset requests an hour per network
email_limiter = RateLimiter("email", 3600.0)        # 3 account emails an hour to any one address, so nobody gets flooded
report_limiter = RateLimiter("report", 3600.0)      # 10 site reports an hour per network
repeat_report_limiter = RateLimiter("repeat_report", 86400.0)   # one report a day per site per network
share_limiter = RateLimiter("share", 3600.0)        # 30 shared results an hour per network
```

Move the `from ratelimit import RateLimiter` line up to the other project imports. In the `from collections import ...` line, drop `defaultdict` and `deque` (no longer used).

- [ ] **Step 6: Update the test suites**

In `tests/testenv.py`, add before `import db`:

```python
os.environ.setdefault("REDIS_URL", "fake://")
os.environ.setdefault("RATE_LIMIT_SECRET", "test-secret")
```

Replace every `.hits.clear()` with `.reset()` in `tests/regress.py`, `tests/test_email.py` and `tests/test_features.py`.

In `tests/regress.py`, replace the block under `# --- fix: rate limiter sweeps idle keys only periodically ---` (the `rl = main.RateLimiter(60.0)` loop and its `ok(...)`) with:

```python
# --- rate limits are shared through Redis and hold no raw addresses ---
import store  # noqa: E402
main.scan_limiter.reset()
main.scan_limiter.check("203.0.113.9", 10, "x")
ok("limiter keys hold no raw addresses", not any("203.0.113.9" in k for k in store.sync_client().keys("rl:*")))
```

- [ ] **Step 7: Run every suite**

Run: `for t in test_ratelimit regress test_email test_features; do PYTHONPATH=. .venv/Scripts/python tests/$t.py | tail -1; done`
Expected: 8/8, regress 24/25 (example.com only), 32/32, 70/70.

- [ ] **Step 8: Commit**

```bash
git add ratelimit.py tests/test_ratelimit.py main.py tests/testenv.py tests/regress.py tests/test_email.py tests/test_features.py
git commit -m "Keep rate limits in Redis so every API process shares them"
```

---

### Task 5: Live progress from the scanner

**Files:**
- Modify: `scanner.py` (imports, new helpers above `scan`, `scan` itself at `scanner.py:473`)
- Create: `tests/test_progress.py`

**Interfaces:**
- Produces: `scanner.scan(raw_domain: str, progress: Progress | None = None) -> dict` where `Progress = Callable[[str, str], Awaitable[None]]`. Steps reported: `resolve`, `certificate`, `email`, `records`, `page`, `impersonation`. Statuses: `ok`, `warn`, `bad`, `done`, `skipped`. The report itself is unchanged.

- [ ] **Step 1: Write the failing test `tests/test_progress.py`**

```python
"""The scanner reports each check as it finishes. Network calls are replaced, so this runs offline."""
import asyncio
import os

os.environ.setdefault("REDIS_URL", "fake://")
import scanner  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def collect(target):
    events = []

    async def progress(step, status):
        events.append((step, status))
    report = await scanner.scan(target, progress=progress)
    return report, events


async def unresolvable(host):
    raise scanner.Unresolvable("no address")


async def records(host, link=None):
    return {"registration": None, "certificate": None, "lists": []}

import impersonation  # noqa: E402

scanner.resolve_public = unresolvable
impersonation.lookup_records = records   # check_impersonation (used for unreachable sites) calls this

report, events = asyncio.run(collect("offline-site.example"))
ok("an unreachable site reports resolve as bad", ("resolve", "bad") in events)
ok("and still reports the impersonation check", any(step == "impersonation" for step, _ in events))
ok("the report itself is unchanged", report["resolves"] is False)


async def public(host):
    return ["203.0.113.5"]


async def tls(host, ip):
    return scanner.Category("tls", "Certificate", score=100)


async def email(host):
    return scanner.Category("email", "Email", score=40)


async def no_page(*args):
    return None

scanner.resolve_public = public
scanner.check_tls = tls
scanner.check_email = email
scanner.try_fetch = no_page
scanner.render_page = no_page
scanner.lookup_records = records

report, events = asyncio.run(collect("reachable-site.example"))
steps = dict(events)
ok("resolve ok", steps.get("resolve") == "ok")
ok("a good certificate is ok", steps.get("certificate") == "ok")
ok("weak email records are bad", steps.get("email") == "bad")
ok("records done", steps.get("records") == "done")
ok("a page that didn't load is skipped", steps.get("page") == "skipped")
ok("impersonation reported last", events[-1][0] == "impersonation")


async def broken(step, status):
    raise RuntimeError("Redis went away")

ok("a failing progress callback doesn't fail the scan",
   asyncio.run(scanner.scan("reachable-site.example", progress=broken))["domain"] == "reachable-site.example")
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_progress.py`
Expected: `TypeError: scan() got an unexpected keyword argument 'progress'`

- [ ] **Step 3: Add the helpers to `scanner.py`**

Add to the imports: `from collections.abc import Awaitable, Callable`. Add above `async def scan`:

```python
Progress = Callable[[str, str], Awaitable[None]]
IMPERSONATION_STATUS = {"official": "ok", "clear": "ok", "suspicious": "warn", "likely": "bad", "reported": "bad"}


def _status(score: int) -> str:
    return "ok" if score >= 80 else "warn" if score >= 50 else "bad"


async def _emit(progress: Progress | None, step: str, status: str) -> None:
    if progress is None:
        return
    try:
        await progress(step, status)
    except Exception:   # a lost progress message must never fail the scan itself
        pass


async def _step(progress: Progress | None, step: str, coro: Awaitable, status: Callable[[object], str]):
    """Await one check and report it as soon as it finishes."""
    result = await coro
    await _emit(progress, step, status(result))
    return result
```

- [ ] **Step 4: Report from `scan`**

Change the signature to `async def scan(raw_domain: str, progress: Progress | None = None) -> dict:` and make these edits inside it:

In the `except Unresolvable:` branch, before `impersonation = await check_impersonation(host, link)`:

```python
        await _emit(progress, "resolve", "bad")
```

and right after that line:

```python
        await _emit(progress, "impersonation", IMPERSONATION_STATUS[impersonation["level"]])
```

After `ip = next(...)`:

```python
    await _emit(progress, "resolve", "ok")
```

Replace `render_task = asyncio.create_task(render_page(target))` with:

```python
    render_task = asyncio.create_task(_step(progress, "page", render_page(target),
                                            lambda page: "done" if page is not None else "skipped"))
```

Replace the `asyncio.gather(...)` call with:

```python
            tls, https_page, http_page, email, records = await asyncio.gather(
                _step(progress, "certificate", check_tls(host, ip), lambda c: _status(c.score)),
                try_fetch(client, f"https://{host}/"),
                try_fetch(client, f"http://{host}/"),
                _step(progress, "email", check_email(host), lambda c: _status(c.score)),
                _step(progress, "records", lookup_records(host, link),
                      lambda rec: "bad" if any(e["status"] == "listed" for e in rec["lists"]) else "done"),
            )
```

After `impersonation = assess(host, records, page_signals, page_facts)`:

```python
    await _emit(progress, "impersonation", IMPERSONATION_STATUS[impersonation["level"]])
```

- [ ] **Step 5: Run the test to see it pass**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_progress.py`
Expected: `10/10 passed`

- [ ] **Step 6: Check the evaluation pipeline still runs a real scan**

Run: `PYTHONPATH=. .venv/Scripts/python -c "import asyncio, scanner, render; r = asyncio.run(scanner.scan('github.com')); print(r['impersonation']['level']); asyncio.run(render.shutdown())"`
Expected: `official`

- [ ] **Step 7: Commit**

```bash
git add scanner.py tests/test_progress.py
git commit -m "Report each scan check as it finishes, for live progress"
```

---

### Task 6: The job queue

**Files:**
- Create: `jobs.py`, `tests/test_jobs.py`

**Interfaces:**
- Consumes: a `redis.asyncio.Redis` client (`store.async_client()`).
- Produces (all `async`, first argument `r`): `ensure_group(r)`, `submit(r, target: str, cache_key: str, user_id: int | None) -> tuple[str, bool]` (raises `QueueFull`), `claim(r, consumer: str, block_ms: int | None = 5000) -> tuple[str, dict] | None` (entry id, fields `job`, `target`, `cache_key`, `user_id`), `ack(r, entry_id)`, `start(r, job_id) -> int`, `publish(r, job_id, event: dict)`, `finish(r, job_id, report: dict, cache_key: str)`, `fail(r, job_id, message: str, code: int)`, `state(r, job_id) -> dict | None`, `events(r, job_id, timeout: float = 120.0)` (async iterator of dicts), `heartbeat(r, worker_id: str, renderer_error: str | None)`, `healthy_workers(r) -> int`. Sync: `cache_key(host: str, path: str | None) -> str`. Constants `MAX_QUEUED`, `STALE_MS`, `MAX_ATTEMPTS`, `CACHE_SECONDS`. Event shapes: `{"type": "step", "step": str, "status": str}`, `{"type": "done"}`, `{"type": "error", "message": str, "code": int}`.

- [ ] **Step 1: Write the failing test `tests/test_jobs.py`**

```python
"""The scan queue, job state, progress events and result cache (in-memory Redis)."""
import asyncio
import os

os.environ.setdefault("REDIS_URL", "fake://")   # or a real Redis database the test may empty
import jobs  # noqa: E402
import store  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def main():
    r = store.async_client()
    await r.flushall()
    await jobs.ensure_group(r)
    await jobs.ensure_group(r)   # safe to call again
    key = jobs.cache_key("example.com", None)
    job_id, cached = await jobs.submit(r, "example.com", key, None)
    ok("a new target is queued", not cached and (await jobs.state(r, job_id))["status"] == "queued")

    entry_id, fields = await jobs.claim(r, "w1", block_ms=None)
    ok("a worker claims it with its fields", fields["job"] == job_id and fields["target"] == "example.com")
    ok("nothing else to claim", await jobs.claim(r, "w1", block_ms=None) is None)
    ok("first attempt", await jobs.start(r, job_id) == 1)
    await jobs.publish(r, job_id, {"type": "step", "step": "certificate", "status": "ok"})
    await jobs.finish(r, job_id, {"domain": "example.com"}, key)
    await jobs.ack(r, entry_id)
    events = [e async for e in jobs.events(r, job_id, timeout=2)]
    ok("events replay in order and end with done", [e["type"] for e in events] == ["step", "done"])
    ok("state holds the report", (await jobs.state(r, job_id))["report"] == {"domain": "example.com"})
    ok("acknowledged jobs leave the queue", await r.xlen(jobs.QUEUE) == 0)

    again, cached = await jobs.submit(r, "example.com", key, None)
    ok("the same target within 15 minutes returns the saved result", cached and again == job_id)

    failing, _ = await jobs.submit(r, "broken.example", jobs.cache_key("broken.example", None), None)
    entry_id, _ = await jobs.claim(r, "w1", block_ms=None)
    await jobs.fail(r, failing, "The scan timed out.", 504)
    await jobs.ack(r, entry_id)
    state = await jobs.state(r, failing)
    ok("a failed job keeps its message and code", state["status"] == "error" and state["code"] == 504)

    jobs.STALE_MS = 0   # treat any unacknowledged job as abandoned
    orphan, _ = await jobs.submit(r, "orphan.example", jobs.cache_key("orphan.example", None), None)
    await jobs.claim(r, "dead-worker", block_ms=None)
    reclaimed = await jobs.claim(r, "w2", block_ms=None)
    ok("a job a dead worker left behind is claimed by another", reclaimed and reclaimed[1]["job"] == orphan)

    jobs.MAX_QUEUED = 1
    try:
        await jobs.submit(r, "one-more.example", jobs.cache_key("one-more.example", None), None)
        ok("a full queue refuses new jobs", False)
    except jobs.QueueFull:
        ok("a full queue refuses new jobs", True)

    ok("an unknown job has no state", await jobs.state(r, "no-such-job") is None)
    await jobs.heartbeat(r, "w1", None)
    await jobs.heartbeat(r, "w2", "browser failed")
    ok("only workers with a working browser count as healthy", await jobs.healthy_workers(r) == 1)

asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_jobs.py`
Expected: `ModuleNotFoundError: No module named 'jobs'`

- [ ] **Step 3: Write `jobs.py`**

```python
"""The scan job queue, live progress and result cache, all in Redis.

A scan is a job: the API adds it to the stream QUEUE; a worker takes it through the consumer group GROUP,
streams progress events to scan:<id>:events, stores the report and acknowledges the job. A job a worker
took but never acknowledged (because the worker died) is claimed by another worker after STALE_MS.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator

from redis.exceptions import ResponseError

QUEUE = "scans:queue"
GROUP = "workers"
MAX_QUEUED = 200            # waiting or running; beyond this the API answers "busy"
STALE_MS = 90_000           # unacknowledged this long: retried by another worker (a scan takes at most 45 s)
MAX_ATTEMPTS = 2
RESULT_SECONDS = 24 * 3600  # job state and results
EVENTS_SECONDS = 3600       # progress streams
CACHE_SECONDS = 15 * 60     # the same target scanned again within this gets the saved result
HEARTBEAT_SECONDS = 60      # a worker silent for this long counts as gone


class QueueFull(Exception):
    pass


def _job(job_id: str) -> str:
    return f"scan:{job_id}"


def _events(job_id: str) -> str:
    return f"scan:{job_id}:events"


def _result(job_id: str) -> str:
    return f"scan:{job_id}:result"


def cache_key(host: str, path: str | None) -> str:
    return hashlib.sha256(f"{host}{path or ''}".encode()).hexdigest()


async def ensure_group(r) -> None:
    try:
        await r.xgroup_create(QUEUE, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):   # already exists: fine
            raise


async def submit(r, target: str, cache_key: str, user_id: int | None) -> tuple[str, bool]:
    """Queue a scan, or return a recent result for the same target. Returns (job id, was cached)."""
    cached = await r.get(f"cache:{cache_key}")
    if cached and await r.exists(_result(cached)):
        return cached, True
    if await r.xlen(QUEUE) >= MAX_QUEUED:
        raise QueueFull
    job_id = secrets.token_urlsafe(16)
    await r.hset(_job(job_id), mapping={"status": "queued", "target": target, "attempts": 0,
                                        "created": int(time.time())})
    await r.expire(_job(job_id), RESULT_SECONDS)
    await r.xadd(QUEUE, {"job": job_id, "target": target, "cache_key": cache_key, "user_id": str(user_id or "")})
    return job_id, False


async def claim(r, consumer: str, block_ms: int | None = 5000) -> tuple[str, dict] | None:
    """The next job for this worker: first one a dead worker left behind, else a new one.
    block_ms=None returns at once when there's nothing to do."""
    reply = await r.xautoclaim(QUEUE, GROUP, consumer, min_idle_time=STALE_MS, start_id="0-0", count=1)
    entries = [e for e in reply[1] if e and e[1]]   # skip entries deleted meanwhile
    if not entries:
        found = await r.xreadgroup(GROUP, consumer, {QUEUE: ">"}, count=1, block=block_ms)
        entries = found[0][1] if found else []
    if not entries:
        return None
    entry_id, fields = entries[0]
    return entry_id, fields


async def ack(r, entry_id: str) -> None:
    await r.xack(QUEUE, GROUP, entry_id)
    await r.xdel(QUEUE, entry_id)


async def start(r, job_id: str) -> int:
    """Mark a job running; returns which attempt this is."""
    attempts = await r.hincrby(_job(job_id), "attempts", 1)
    await r.hset(_job(job_id), "status", "running")
    return attempts


async def publish(r, job_id: str, event: dict) -> None:
    await r.xadd(_events(job_id), {"data": json.dumps(event)})
    await r.expire(_events(job_id), EVENTS_SECONDS)


async def finish(r, job_id: str, report: dict, cache_key: str) -> None:
    await r.set(_result(job_id), json.dumps(report), ex=RESULT_SECONDS)
    await r.hset(_job(job_id), "status", "done")
    await r.set(f"cache:{cache_key}", job_id, ex=CACHE_SECONDS)
    await publish(r, job_id, {"type": "done"})


async def fail(r, job_id: str, message: str, code: int) -> None:
    await r.hset(_job(job_id), mapping={"status": "error", "error": message, "code": code})
    await publish(r, job_id, {"type": "error", "message": message, "code": code})


async def state(r, job_id: str) -> dict | None:
    """{"id", "status": queued, running, done or error, "report" when done, "error" and "code" when failed}."""
    job = await r.hgetall(_job(job_id))
    if not job:
        return None
    out = {"id": job_id, "status": job["status"]}
    if job["status"] == "done":
        raw = await r.get(_result(job_id))
        if raw is None:
            return None
        out["report"] = json.loads(raw)
    elif job["status"] == "error":
        out["error"] = job.get("error", "The scan failed. Try again.")
        out["code"] = int(job.get("code", 500))
    return out


async def events(r, job_id: str, timeout: float = 120.0) -> AsyncIterator[dict]:
    """A job's progress events from the first, ending with "done" or "error" (or at the timeout)."""
    last, deadline = "0", time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = await r.xread({_events(job_id): last}, count=100, block=1000)
        if not reply:
            await asyncio.sleep(0.05)   # the in-memory Redis used in tests returns at once instead of waiting
            continue
        for entry_id, fields in reply[0][1]:
            last = entry_id
            event = json.loads(fields["data"])
            yield event
            if event["type"] in ("done", "error"):
                return


async def heartbeat(r, worker_id: str, renderer_error: str | None) -> None:
    await r.set(f"workers:{worker_id}", json.dumps({"renderer_error": renderer_error}), ex=HEARTBEAT_SECONDS)


async def healthy_workers(r) -> int:
    """Workers that reported recently and whose sandboxed browser passed its self-test."""
    count = 0
    async for key in r.scan_iter("workers:*"):
        raw = await r.get(key)
        if raw and not json.loads(raw)["renderer_error"]:
            count += 1
    return count
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_jobs.py`
Expected: `13/13 passed`. If `xautoclaim` is missing from the installed fakeredis, upgrade fakeredis (`pip install -U fakeredis`) and re-pin it in `requirements-dev.txt`.

- [ ] **Step 5: Run the same test against the real Redis**

Run: `REDIS_URL=redis://127.0.0.1:6379/15 PYTHONPATH=. .venv/Scripts/python tests/test_jobs.py`
Expected: `13/13 passed` (database 15 is flushed by the test, so the development data in database 0 is untouched).

- [ ] **Step 6: Commit**

```bash
git add jobs.py tests/test_jobs.py
git commit -m "Add the scan job queue on Redis Streams, with progress events and a result cache"
```

---

### Task 7: The scan worker

**Files:**
- Create: `worker.py`, `tests/test_worker.py`

**Interfaces:**
- Consumes: `jobs.*` (Task 6), `scanner.scan(raw, progress=...)` (Task 5), `render.self_test()`, `render.shutdown()`, `db.add_scan`.
- Produces: `worker.run_job(r, job_id: str, fields: dict) -> None` (used by the API's inline mode), `worker.record_history(user_id: int, target: str, report: dict) -> None`, `worker.serve(stop: asyncio.Event | None = None) -> None`, `python worker.py`. Env: `WORKER_CONCURRENCY` (default 4), `ARTEMIS_STUB_SCANS=1` (load tests only).

- [ ] **Step 1: Write the failing test `tests/test_worker.py`**

```python
"""The worker loop: takes jobs, streams progress, stores results, gives up after two attempts."""
import asyncio
import os

os.environ["REDIS_URL"] = "fake://"
import jobs  # noqa: E402
import render  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402
from scanner import ScanError  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def fake_scan(target, progress=None):
    if target == "bad input":
        raise ScanError("Enter a public domain or link, like example.com.")
    await progress("certificate", "ok")
    return {"domain": target, "risk": {"score": 5, "label": "Low"},
            "impersonation": {"verdict": "No impersonation signs"}, "payment": None}


async def no_browser():
    return None

worker.scan = fake_scan
render.self_test = no_browser
render.shutdown = no_browser


async def wait_for(r, job_id, status, seconds=5):
    for _ in range(seconds * 20):
        state = await jobs.state(r, job_id)
        if state and state["status"] == status:
            return state
        await asyncio.sleep(0.05)
    return await jobs.state(r, job_id)


async def main():
    r = store.async_client()
    await r.flushall()
    stop = asyncio.Event()
    loop = asyncio.create_task(worker.serve(stop))
    job_id, _ = await jobs.submit(r, "site.example", jobs.cache_key("site.example", None), None)
    state = await wait_for(r, job_id, "done")
    ok("the worker finishes a queued scan", state["status"] == "done" and state["report"]["domain"] == "site.example")
    events = [e async for e in jobs.events(r, job_id, timeout=2)]
    ok("its progress was streamed", {"type": "step", "step": "certificate", "status": "ok"} in events)
    ok("the job left the queue", await r.xlen(jobs.QUEUE) == 0)
    ok("the worker reported in as healthy", await jobs.healthy_workers(r) == 1)

    bad, _ = await jobs.submit(r, "bad input", "k-bad", None)
    state = await wait_for(r, bad, "error")
    ok("a rejected target ends with the scanner's message and 400",
       state["code"] == 400 and state["error"].startswith("Enter a public domain"))

    stop.set()
    await asyncio.wait_for(loop, 10)
    ok("the worker stops cleanly and removes its heartbeat", await jobs.healthy_workers(r) == 0)

    tired, _ = await jobs.submit(r, "site2.example", "k-tired", None)
    await r.hset(f"scan:{tired}", "attempts", jobs.MAX_ATTEMPTS)
    entry_id, fields = await jobs.claim(r, "w", block_ms=None)
    await worker.run_job(r, fields["job"], fields)
    ok("a job past its attempts fails instead of running again", (await jobs.state(r, tired))["status"] == "error")

asyncio.run(main())
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_worker.py`
Expected: `ModuleNotFoundError: No module named 'worker'`

- [ ] **Step 3: Write `worker.py`**

```python
"""Scan worker: takes scan jobs from Redis, runs them with the sandboxed browser and streams progress.

    python worker.py

Run as many as needed (docker compose up --scale worker=N); each runs WORKER_CONCURRENCY scans at once.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket

import db
import jobs
import render
import store
from scanner import ScanError, scan

log = logging.getLogger("artemis.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "4"))
SCAN_TIMEOUT = 45.0
STUB_SCANS = os.environ.get("ARTEMIS_STUB_SCANS") == "1"   # load tests only: no real site is contacted


async def stub_scan(target: str, progress=None) -> dict:
    """Stands in for a real scan during load tests: similar timing, no network."""
    for step in ("resolve", "certificate", "email", "records", "page", "impersonation"):
        await asyncio.sleep(0.3)
        if progress is not None:
            await progress(step, "ok")
    return {"domain": target, "resolves": True, "risk": {"score": 10, "label": "Low"},
            "impersonation": {"verdict": "Load test"}, "payment": None}


def record_history(user_id: int, target: str, report: dict) -> None:
    risk = report["risk"]
    verdict = (report.get("impersonation") or report["payment"])["verdict"]
    db.add_scan(user_id, target, risk and risk["score"], risk and risk["label"], verdict)


async def run_job(r, job_id: str, fields: dict) -> None:
    """Run one scan job and record how it ended. Shared by the worker and the API's inline mode."""
    if await jobs.start(r, job_id) > jobs.MAX_ATTEMPTS:
        await jobs.fail(r, job_id, "The scan failed. Try again.", 500)
        return

    async def progress(step: str, status: str) -> None:
        await jobs.publish(r, job_id, {"type": "step", "step": step, "status": status})

    run = stub_scan if STUB_SCANS else scan
    try:
        report = await asyncio.wait_for(run(fields["target"], progress=progress), SCAN_TIMEOUT)
    except ScanError as exc:
        await jobs.fail(r, job_id, str(exc), 400)
        return
    except asyncio.TimeoutError:
        await jobs.fail(r, job_id, "The scan timed out.", 504)
        return
    except Exception:
        log.exception("Scan %s failed", job_id)
        await jobs.fail(r, job_id, "The scan failed. Try again.", 500)
        return
    await jobs.finish(r, job_id, report, fields["cache_key"])
    if fields.get("user_id"):
        await asyncio.to_thread(record_history, int(fields["user_id"]), fields["target"], report)


async def serve(stop: asyncio.Event | None = None) -> None:
    r = store.async_client()
    await jobs.ensure_group(r)
    stop = stop or asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):   # Windows, or not the main thread
            pass
    renderer_error = None if STUB_SCANS else await render.self_test()
    if renderer_error:
        log.error("Headless browser self-test failed: %s", renderer_error)
    slots = asyncio.Semaphore(CONCURRENCY)
    running: set[asyncio.Task] = set()

    async def heartbeat() -> None:
        while True:
            await jobs.heartbeat(r, WORKER_ID, renderer_error)
            await asyncio.sleep(15)

    async def handle(entry_id: str, fields: dict) -> None:
        try:
            await run_job(r, fields["job"], fields)
        finally:
            await jobs.ack(r, entry_id)
            slots.release()

    beat = asyncio.create_task(heartbeat())
    log.info("Worker %s ready, %d scans at once", WORKER_ID, CONCURRENCY)
    try:
        while not stop.is_set():
            await slots.acquire()
            claimed = await jobs.claim(r, WORKER_ID, block_ms=1000)
            if claimed is None:
                slots.release()
                await asyncio.sleep(0.05)   # the in-memory Redis used in tests returns at once instead of waiting
                continue
            task = asyncio.create_task(handle(*claimed))
            running.add(task)
            task.add_done_callback(running.discard)
        await asyncio.gather(*running)   # finish the scans already started
    finally:
        beat.cancel()
        await r.delete(f"workers:{WORKER_ID}")
        await render.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db.init()
    asyncio.run(serve())
```

- [ ] **Step 4: Run the test to see it pass**

Run: `PYTHONPATH=. .venv/Scripts/python tests/test_worker.py`
Expected: `7/7 passed`

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "Add the scan worker"
```

---

### Task 8: API endpoints on the queue

**Files:**
- Modify: `main.py` (imports, constants at `main.py:30-38`, `lifespan` at `main.py:64-80`, the scan section at `main.py:493-533`, the extension section at `main.py:560-602`, `PAGES` and `healthz` at `main.py:605-639`), `tests/testenv.py`, `tests/regress.py` (the "global scan concurrency" block)
- Create: `tests/test_scans_api.py`

**Interfaces:**
- Consumes: `jobs.*`, `worker.run_job`, `worker.record_history`, `store.async_client`, `db.share_result`, `db.shared_result`, `db.ping`, `scanner.normalize_domain`, `scanner.requested_path`, env `ARTEMIS_INLINE_SCANS=1`.
- Produces endpoints:
  - `POST /api/scans` body `{"target": str}`: `202 {"id", "status": "queued"}`, or `200 {"id", "status": "done"}` when cached, or for UPI targets `200 {"id": null, "status": "done", "report": {...}}`; 400 invalid, 429 rate limit, 503 queue full.
  - `GET /api/scans/{id}`: the `jobs.state` dict; 404 unknown.
  - `GET /api/scans/{id}/events`: `text/event-stream` of `data: <json>` lines: step events, then `{"type": "done", "report": {...}}` or `{"type": "error", "message", "code"}`.
  - `POST /api/scans/{id}/share`: `{"url": "/r/<id>"}`; 404 unless finished.
  - `GET /api/shared/{id}`: the report; 404 unknown or expired.
  - `GET /r/{id}`: `index.html` (the Phase 2 UI will render shared results there).
  - `POST /api/scan` and `POST /api/check`: unchanged requests and responses.

- [ ] **Step 1: Write the failing test `tests/test_scans_api.py`**

```python
"""The queue-based scan API, run with the job executed inside the API process (inline mode)."""
import json

import testenv  # noqa: F401
from fastapi.testclient import TestClient  # noqa: E402

import jobs  # noqa: E402
import main  # noqa: E402
import worker  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def fake_scan(target, progress=None):
    await progress("certificate", "ok")
    await progress("impersonation", "ok")
    return {"domain": target, "risk": {"score": 5, "label": "Low"},
            "impersonation": {"verdict": "No impersonation signs"}, "payment": None}

worker.scan = fake_scan


def read_events(client, job_id):
    events = []
    with client.stream("GET", f"/api/scans/{job_id}/events") as resp:
        ok("events are a server-sent event stream", resp.headers["content-type"].startswith("text/event-stream"))
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


with TestClient(main.app, base_url="http://testserver") as c:
    main.scan_limiter.reset()
    r = c.post("/api/scans", json={"target": "site-one.example"})
    ok("a new scan is accepted with 202 and a job id", r.status_code == 202 and r.json()["status"] == "queued")
    job_id = r.json()["id"]
    events = read_events(c, job_id)
    ok("progress events arrive in order", [e.get("step") for e in events if e["type"] == "step"] == ["certificate", "impersonation"])
    ok("the stream ends with the full report", events[-1]["type"] == "done" and events[-1]["report"]["domain"] == "site-one.example")
    ok("the job can also be read directly", c.get(f"/api/scans/{job_id}").json()["status"] == "done")
    ok("events for a finished job replay at once", read_events(c, job_id)[-1]["type"] == "done")

    again = c.post("/api/scans", json={"target": "site-one.example"})
    ok("the same target again returns the saved result", again.status_code == 200 and again.json() == {"id": job_id, "status": "done"})

    ok("an invalid target is refused", c.post("/api/scans", json={"target": "not a domain"}).status_code == 400)
    upi = c.post("/api/scans", json={"target": "upi://pay?pa=shop.name@okaxis&pn=Shop"})
    ok("a UPI link is checked straight away", upi.status_code == 200 and upi.json()["report"]["payment"] is not None)
    ok("an unknown job is 404", c.get("/api/scans/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404)
    ok("a malformed job id is 404", c.get("/api/scans/..%2Fetc").status_code == 404)

    shared = c.post(f"/api/scans/{job_id}/share")
    ok("a finished scan can be shared", shared.status_code == 200 and shared.json() == {"url": f"/r/{job_id}"})
    ok("the shared result can be read back", c.get(f"/api/shared/{job_id}").json()["domain"] == "site-one.example")
    ok("the share page loads", c.get(f"/r/{job_id}").status_code == 200)
    ok("an unknown shared result is 404", c.get("/api/shared/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404)

    old = c.post("/api/scan", json={"domain": "site-two.example"})
    ok("the old endpoint still returns the report directly", old.status_code == 200 and old.json()["domain"] == "site-two.example")

    jobs.MAX_QUEUED = 0
    ok("a full queue answers 503", c.post("/api/scans", json={"target": "site-three.example"}).status_code == 503)
    jobs.MAX_QUEUED = 200
    ok("healthz is ok", c.get("/healthz").json() == {"status": "ok"})
print(f"\n{sum(results)}/{len(results)} passed")
```

- [ ] **Step 2: Run it to see it fail**

Add `os.environ.setdefault("ARTEMIS_INLINE_SCANS", "1")` to `tests/testenv.py` (next to the other `setdefault` lines), then run:
Run: `PYTHONPATH=. .venv/Scripts/python tests/test_scans_api.py`
Expected: `FAIL a new scan is accepted with 202 and a job id` (the endpoint doesn't exist yet, 404/405), then an error.

- [ ] **Step 3: Imports and constants in `main.py`**

Add `import os` to the standard-library imports. Add to the FastAPI imports: `StreamingResponse` (`from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse`). Add to the project imports:

```python
import jobs
import store
from scanner import ScanError, normalize_domain, requested_path, scan
from worker import record_history, run_job
```

(replacing the existing `from scanner import ...` line). Delete the `from collections import OrderedDict` line (nothing else uses it). Replace `SCAN_TIMEOUT = 30.0` and `MAX_CONCURRENT_SCANS = 8 ...` with:

```python
WAIT_FOR_SCAN = 50.0              # POST /api/scan waits this long for its job (the job itself stops at 45 s)
INLINE_SCANS = os.environ.get("ARTEMIS_INLINE_SCANS") == "1"   # run jobs in this process (tests, local dev without a worker)
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
```

Delete `CHECK_CACHE_SIZE` and the line `scan_slots = asyncio.Semaphore(MAX_CONCURRENT_SCANS)`.

- [ ] **Step 4: Startup in `main.py`**

Replace the body of `lifespan` with:

```python
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
        log.error("Headless browser self-test failed: %s", app.state.renderer_error)
    app.state.inline_jobs = set()
    yield
    if INLINE_SCANS:
        await render.shutdown()
```

- [ ] **Step 5: The scan endpoints in `main.py`**

Replace everything from `class ScanRequest(BaseModel):` to the end of `run_scan` with:

```python
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
        if state["status"] in ("done", "error"):
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
```

- [ ] **Step 6: The extension check's cache in `main.py`**

Delete `_check_cache: OrderedDict[...] = OrderedDict()`. In `quick_check`, replace

```python
    cached = _check_cache.get(host)
    if cached and time.monotonic() - cached[0] < CHECK_CACHE_SECONDS:
        return cached[1]
```

with

```python
    r = store.async_client()
    cached = await r.get(f"check:{host}")
    if cached:
        return json.loads(cached)
```

and replace the five lines from `_check_cache[host] = (time.monotonic(), result)` to `_check_cache.popitem(last=False)` with

```python
    await r.set(f"check:{host}", json.dumps(result), ex=CHECK_CACHE_SECONDS)
```

- [ ] **Step 7: The share page route and health check in `main.py`**

After the `for route, filename in PAGES.items():` loop, add:

```python
@app.get("/r/{job_id}", include_in_schema=False)
async def shared_page(job_id: str) -> FileResponse:
    return FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})
```

Replace the body of `healthz` with:

```python
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
```

- [ ] **Step 8: Update the queue-full test in `tests/regress.py`**

Replace the block from `# --- fix: global scan concurrency ---` through `c.portal.call(drain)` with:

```python
    # --- a full queue refuses new scans ---
    import jobs  # noqa: E402
    main.scan_limiter.reset()
    jobs.MAX_QUEUED = 0
    ok("scans refused with 503 when the queue is full", c.post("/api/scan", json={"domain": "example.org"}).status_code == 503)
    jobs.MAX_QUEUED = 200
```

- [ ] **Step 9: Run every suite**

Run: `for t in test_store test_ratelimit test_progress test_jobs test_worker test_migrate test_scans_api regress test_email test_features; do echo "== $t"; PYTHONPATH=. .venv/Scripts/python tests/$t.py | tail -1; done`
Expected: all pass, except regress 24/25 ("scan while signed in" on the real example.com, as before).

- [ ] **Step 10: Try it in the browser**

Start the local services (`docker compose -f docker-compose.dev.yml up -d`), then in one terminal `.venv/Scripts/python worker.py` and in another `ARTEMIS_INLINE_SCANS= .venv/Scripts/python -m uvicorn main:app --port 8000`. Open http://localhost:8000, scan `github.com`.
Expected: the current page shows the result as before; the worker's log shows the job.

- [ ] **Step 11: Commit**

```bash
git add main.py tests/test_scans_api.py tests/testenv.py tests/regress.py
git commit -m "Run scans as queued jobs with live progress, result caching and shareable results"
```

---

### Task 9: Containers, deployment docs and privacy policy

**Files:**
- Modify: `docker-compose.yml`, `Dockerfile`, `.env.example`, `DEPLOY.md`, `privacy.html:26-44`, `.dockerignore`
- Create: `deploy/local.env`

**Interfaces:**
- Consumes: everything above.
- Produces: services `app` (API), `worker`, `redis`, `postgres`, `caddy`; env `POSTGRES_PASSWORD`, `RATE_LIMIT_SECRET`.

- [ ] **Step 1: `Dockerfile`**

Replace the two `COPY main.py ...` lines' first line with:

```dockerfile
COPY main.py db.py mail.py google_auth.py netsafety.py scanner.py impersonation.py clone.py render.py brands.py \
     payments.py reports.py store.py ratelimit.py jobs.py worker.py ./
COPY migrations ./migrations
COPY tools/migrate_sqlite.py ./tools/
```

Replace the last three lines (the comment `# One worker: ...`, `# No access log ...` and `CMD [...]`) with:

```dockerfile
# The API. Several uvicorn workers can share the load because rate limits, caches and the job queue live
# in Redis. The scan worker uses this same image with the command `python worker.py` (docker-compose.yml).
# No access log here: Caddy's access log (deploy/Caddyfile) is the single, time-limited record of visitor IPs.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "3", "--no-server-header", "--no-access-log"]
```

- [ ] **Step 2: `docker-compose.yml`**

In the `app` service: add to `environment`:

```yaml
      DATABASE_URL: postgresql://artemis:${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}@postgres:5432/artemis
      REDIS_URL: redis://redis:6379/0
      RATE_LIMIT_SECRET: ${RATE_LIMIT_SECRET:?Set RATE_LIMIT_SECRET in .env}
```

add `- data` to its `networks`, and add:

```yaml
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

Keep its `security_opt`, `shm_size` and `artemis_data` volume: the evaluation cron job runs scans in this service, and the old SQLite file is read from that volume once by the migration.

Add these services after `app`:

```yaml
  worker:
    build: .
    command: ["python", "worker.py"]
    restart: unless-stopped
    init: true                     # reaps Chromium's child processes
    shm_size: "1gb"
    mem_limit: 2g
    pids_limit: 512
    cap_drop: [ALL]
    security_opt:
      - seccomp=deploy/seccomp_profile.json
      - no-new-privileges:true
    environment:
      DATABASE_URL: postgresql://artemis:${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}@postgres:5432/artemis
      REDIS_URL: redis://redis:6379/0
      SAFE_BROWSING_API_KEY: ${SAFE_BROWSING_API_KEY:-}
      URLHAUS_AUTH_KEY: ${URLHAUS_AUTH_KEY:-}
      ARTEMIS_CHROMIUM_SANDBOX: ${ARTEMIS_CHROMIUM_SANDBOX:-1}
      WORKER_CONCURRENCY: ${WORKER_CONCURRENCY:-4}
    healthcheck:
      disable: true                # the API's /healthz reports whether any worker is alive
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - egress
      - data
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }

  redis:
    image: redis:7
    # Memory only, never written to disk: rate-limit keys stand for visitors' networks.
    command: ["redis-server", "--save", "", "--appendonly", "no", "--maxmemory", "512mb", "--maxmemory-policy", "volatile-lru"]
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    networks:
      - data

  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_USER: artemis
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: artemis
    volumes:
      - pg_data:/var/lib/postgresql/data   # accounts, history and reports; back this up
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "artemis"]
      interval: 10s
      timeout: 3s
      retries: 5
    networks:
      - data
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
```

Under `networks:` add:

```yaml
  data:
    internal: true                   # app, worker, Redis and Postgres only; no internet access
```

Under `volumes:` add `pg_data:`.

- [ ] **Step 3: `.env.example`**

Append:

```
# Database password and the key that keeps rate-limit entries anonymous. Generate each with:
#   openssl rand -hex 32
POSTGRES_PASSWORD=
RATE_LIMIT_SECRET=

# Scans each worker runs at once. Add workers with: docker compose up -d --scale worker=2
WORKER_CONCURRENCY=4
```

- [ ] **Step 4: `deploy/local.env` (a local copy of the stack on Docker Desktop)**

```
# Settings for running the full stack locally (not for a server):
#   docker compose --env-file deploy/local.env up -d --build app worker
DOMAIN=localhost
ACME_EMAIL=dev@example.com
SMTP_HOST=localhost
MAIL_FROM=Artemis <dev@localhost>
POSTGRES_PASSWORD=local-only
RATE_LIMIT_SECRET=local-only
ARTEMIS_CHROMIUM_SANDBOX=1
```

Add a `docker-compose.local.yml` override that publishes the API on this computer only:

```yaml
# Local only: reach the API at http://localhost:8000 without Caddy.
services:
  app:
    ports: ["127.0.0.1:8000:8000"]
    environment:
      APP_URL: http://localhost:8000
```

- [ ] **Step 5: Run the stack locally and scan through it**

Run: `docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file deploy/local.env up -d --build app worker && sleep 30 && curl -s localhost:8000/healthz && curl -s -X POST localhost:8000/api/scans -H "Content-Type: application/json" -d '{"target": "github.com"}'`
Expected: `{"status":"ok"}`, then `{"id":"...","status":"queued"}`. Then `curl -sN localhost:8000/api/scans/<id>/events` prints step events and ends with a `done` event carrying the report. If healthz is `degraded`, check `docker compose logs worker | grep self-test`; on Docker Desktop the Chromium sandbox may be refused, in which case set `ARTEMIS_CHROMIUM_SANDBOX=0` in `deploy/local.env` only.

Then scale: `docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file deploy/local.env up -d --scale worker=2 worker` and confirm both workers log `ready`.

Stop with `docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file deploy/local.env down` (volumes kept).

- [ ] **Step 6: `privacy.html`**

Replace the sentence in the IP address item `We hold it in server memory, not on disk, to limit how many scans and sign-in attempts each visitor can make, and discard it once it's no longer needed for that.` with:

```
To limit how many scans and sign-in attempts each visitor can make, we keep a one-way code made from it (not the address itself) in server memory, never on disk, and discard it once it's no longer needed for that.
```

Replace `<li>We don't save scans made while signed out. Each result is sent to your browser and not stored on our server.</li>` with:

```
<li>Each scan result is kept in server memory for up to 24 hours, so the page can show it as the checks finish and a repeat scan of the same site is quick, and then deleted. It isn't linked to you unless you're signed in, when it's also added to your history. If you choose to share a result, that result alone is stored for 30 days so the link works, and anyone with the link can see it.</li>
```

- [ ] **Step 7: `DEPLOY.md`**

In "First deployment" step 2, after the SMTP paragraph, add:

```markdown
   Also set `POSTGRES_PASSWORD` and `RATE_LIMIT_SECRET` to two different random values
   (`openssl rand -hex 32` makes one).
```

Add a section before "## Updating":

```markdown
## Moving an existing installation from SQLite to Postgres

Versions before the job queue kept accounts in SQLite. To move them, once:

    sudo git pull
    # add POSTGRES_PASSWORD and RATE_LIMIT_SECRET to .env (see .env.example)
    sudo docker compose build
    sudo docker compose up -d postgres redis
    sudo docker compose run --rm --no-deps app python tools/migrate_sqlite.py /app/data/artemis.db
    sudo docker compose up -d

The copy refuses to run twice. The old SQLite file stays in the `artemis_data` volume as a backup.

## Adding scan capacity

Each worker runs `WORKER_CONCURRENCY` scans at once (4 by default). Add workers with:

    sudo docker compose up -d --scale worker=2
```

Replace the "## Backups" commands with:

```markdown
`pg_data` holds user accounts, settings, scan history, site reports and shared results. Back it up
regularly, for example daily:

    sudo docker compose exec -T postgres pg_dump -U artemis artemis | gzip > artemis-backup-$(date +%F).sql.gz
```

Under "## Check it works", add `docker compose ps` should list `app`, `worker`, `redis` and `postgres`, and `docker compose logs worker | grep ready` shows each worker's start.

- [ ] **Step 8: Run all suites once more and commit**

Run: the loop from Task 8 Step 9. Expected: the same results.

```bash
git add Dockerfile docker-compose.yml docker-compose.local.yml .env.example deploy/local.env DEPLOY.md privacy.html
git commit -m "Run the API, scan workers, Redis and Postgres as separate containers"
```

---

### Task 10: Load test and results

**Files:**
- Create: `loadtest/run.py`, `docker-compose.loadtest.yml`, `docs/load-test.md`

**Interfaces:**
- Consumes: `POST /api/scans`, `GET /api/scans/{id}`.
- Produces: `python loadtest/run.py --base-url URL --users N --seconds S [--targets FILE]` printing throughput and timings.

- [ ] **Step 1: `docker-compose.loadtest.yml`**

```yaml
# Load tests only, never on the live site: workers fake their scans (no site is contacted) and
# rate limits are raised so one machine can stand in for many visitors.
services:
  app:
    environment:
      RATE_LIMIT_MULTIPLIER: "1000"
  worker:
    environment:
      ARTEMIS_STUB_SCANS: "1"
```

- [ ] **Step 2: `loadtest/run.py`**

```python
"""Load test: many simulated visitors start scans and wait for their results.

    python loadtest/run.py --base-url http://localhost:8000 --users 50 --seconds 60
    python loadtest/run.py --base-url http://localhost:8000 --users 4 --seconds 120 --targets loadtest/sites.txt

Without --targets every scan is a new made-up domain, for use with docker-compose.loadtest.yml (stub
scans). With --targets it scans real sites from the file, one per line; keep --users small, since every
scan contacts that site.
"""
import argparse
import asyncio
import itertools
import statistics
import time

import httpx


async def visitor(client, targets, deadline, stats):
    while time.monotonic() < deadline:
        target = next(targets)
        started = time.monotonic()
        resp = await client.post("/api/scans", json={"target": target})
        stats["submit"].append(time.monotonic() - started)
        if resp.status_code not in (200, 202):
            stats["refused"][resp.status_code] = stats["refused"].get(resp.status_code, 0) + 1
            await asyncio.sleep(1)
            continue
        job_id = resp.json()["id"]
        while True:
            state = (await client.get(f"/api/scans/{job_id}")).json()
            if state["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.5)
        stats["total"].append(time.monotonic() - started)
        stats["outcomes"][state["status"]] = stats["outcomes"].get(state["status"], 0) + 1


def pct(values, p):
    return sorted(values)[min(len(values) - 1, int(len(values) * p))] if values else 0.0


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--targets", help="file of real sites, one per line")
    args = ap.parse_args()
    if args.targets:
        sites = [l.strip() for l in open(args.targets, encoding="utf-8") if l.strip()]
        targets = itertools.cycle(sites)
    else:
        targets = (f"load-{n}.example" for n in itertools.count())
    stats = {"submit": [], "total": [], "refused": {}, "outcomes": {}}
    deadline = time.monotonic() + args.seconds
    async with httpx.AsyncClient(base_url=args.base_url, timeout=60) as client:
        await asyncio.gather(*(visitor(client, targets, deadline, stats) for _ in range(args.users)))
    done = len(stats["total"])
    print(f"{args.users} visitors for {args.seconds} s")
    print(f"scans finished: {done} ({done / args.seconds * 60:.0f} a minute); outcomes {stats['outcomes']}")
    print(f"refused: {stats['refused'] or 'none'}")
    print(f"start request: median {statistics.median(stats['submit']) * 1000:.0f} ms, "
          f"95th percentile {pct(stats['submit'], 0.95) * 1000:.0f} ms")
    if done:
        print(f"time to result: median {statistics.median(stats['total']):.1f} s, "
              f"95th percentile {pct(stats['total'], 0.95):.1f} s")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Measure API and queue capacity (stub scans)**

Run: `docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.loadtest.yml --env-file deploy/local.env up -d --build app worker`, then for 1, 2 and 3 workers (`--scale worker=N worker`): `.venv/Scripts/python loadtest/run.py --base-url http://localhost:8000 --users 50 --seconds 60`
Expected: no 5xx except 503 once the queue is full; record each run's output.

- [ ] **Step 4: Measure real scan throughput**

Create `loadtest/sites.txt` with 50 lines from the evaluation's genuine list (`ml/data/artemis/dataset.jsonl`, label `genuine`, domain only). Restart without the load-test override (`up -d app worker` with only `docker-compose.local.yml`), set `RATE_LIMIT_MULTIPLIER=1000` by exporting it for the app (add it temporarily to `deploy/local.env`), and run for 1, 2 and 3 workers:
`.venv/Scripts/python loadtest/run.py --base-url http://localhost:8000 --users 4 --seconds 120 --targets loadtest/sites.txt`
Remove `RATE_LIMIT_MULTIPLIER` from `deploy/local.env` afterwards.

- [ ] **Step 5: Write `docs/load-test.md`**

A short page with: the machine (CPU and memory of the laptop under Docker Desktop), the commands, a table per test (workers, scans a minute, median and 95th percentile time to result, refusals), and two or three sentences on what limits throughput (expected: the renderer, 2 pages at once per worker). Use only the numbers measured in Steps 3 and 4.

- [ ] **Step 6: Commit**

```bash
git add loadtest/run.py docker-compose.loadtest.yml docs/load-test.md
git commit -m "Add a load test and record scan throughput for 1 to 3 workers"
```

---

### Task 11: Roll out to the server

**Files:** none (server operations). The user runs these commands on the server (deploys and cron changes are theirs to run).

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: On the server, add the two new settings**

```bash
cd /opt/artemis
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)" | sudo tee -a .env >/dev/null
echo "RATE_LIMIT_SECRET=$(openssl rand -hex 32)" | sudo tee -a .env >/dev/null
```

- [ ] **Step 3: Build, copy the accounts, start everything**

```bash
sudo git -c safe.directory=/opt/artemis pull
sudo docker compose build
sudo docker compose up -d postgres redis
sudo docker compose run --rm --no-deps app python tools/migrate_sqlite.py /app/data/artemis.db
sudo docker compose up -d
```

Expected: the migration prints the row count for each table; `sudo docker compose ps` lists app, worker, redis, postgres and caddy, all running (app healthy).

- [ ] **Step 4: Verify from outside**

Check: `curl -s https://artemissecure.co.in/healthz` is `{"status":"ok"}`; a scan from the website works; an existing account can sign in and sees its history; `POST /api/scans` then `GET /api/scans/<id>/events` streams to a `done` event; the egress firewall still blocks `169.254.169.254` from the worker (`sudo docker compose exec worker python -c "import urllib.request; urllib.request.urlopen('http://169.254.169.254/', timeout=3)"` times out); the evaluation cron's next run succeeds (`tail evaluation/data/scheduled.log`).

- [ ] **Step 5: Record the rollout**

Update the memory note and `DEPLOY.md` if anything differed from the plan.
