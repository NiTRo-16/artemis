# Phase 1: scalable backend

Status: proposed, 29 October 2026

## Goal

Let Artemis serve many visitors at once and grow by adding machines rather than rewriting code. Build
for one server now (4 OCPU, 24 GB, Oracle Always Free); design so that more scan capacity is a matter of
starting more worker containers, on this server or another one.

Success means:

- Scans no longer run inside the web request. A visitor gets a job id at once and watches the checks
  finish live, which the new UI (Phase 2) is built around.
- Several API processes and scan workers run side by side, sharing state through Redis and Postgres.
- The same site scanned twice within 15 minutes returns the saved result immediately.
- A load test gives real numbers for the report: scans per minute, and how long a scan waits in the queue.
- The current web page and the browser extension keep working throughout.

## Today

| Concern | Now | Why it blocks scaling |
|---|---|---|
| Running a scan | Inside `POST /api/scan`, at most 8 at once (`main.py:497`) | A request holds a connection for 10 to 40 s; one process caps the total |
| Rate limits | `RateLimiter` in process memory (`main.py:154`) | A second process would have its own counts |
| Extension cache | `_check_cache` in process memory (`main.py:568`) | Not shared |
| Data | SQLite file with one connection and a lock (`db.py`) | One writer, one machine |
| Browser | One Chromium per process, 2 renders at once (`render.py`) | Tied to the web process |

## Approaches considered

1. **Arq job queue on Redis, Postgres for data** (recommended). Arq is a small job queue built on asyncio,
   so the existing async scanner runs in it unchanged. Redis also holds rate limits, caches and live
   progress. Postgres replaces SQLite.
2. **Celery with RabbitMQ.** The standard choice in Python, but built around synchronous code, with
   another service to run. More moving parts for no gain here.
3. **Keep SQLite and an in-process queue, add uvicorn workers.** Least work, but state stays per process
   and the design can't spread across machines. It doesn't meet the goal.

## Design

```
Browser / extension ──> Caddy ──> api (FastAPI, 3 uvicorn workers, no browser)
                                    │ enqueue, read progress and results
                                    ▼
                                  Redis  (in memory only, nothing written to disk)
                                    │ jobs, progress streams, rate limits, result cache
                                    ▼
                                  worker (Arq) x N  ── each: scanner + its own Chromium
                                    │
                                    ▼
                                  Postgres  (accounts, history, reports, shared results)
```

### Services (docker-compose)

| Service | Image | Networks | Notes |
|---|---|---|---|
| `caddy` | unchanged | front, public | |
| `api` | app image | front, egress, data | `uvicorn --workers 3`; never launches Chromium; still runs the quick extension check, which needs no browser |
| `worker` | app image | egress, data | `arq worker.WorkerSettings`; Chromium sandbox, seccomp profile and memory limit move here from today's `app`; `docker compose up --scale worker=N` |
| `redis` | `redis:7` | data | `--save "" --appendonly no`: keeps rate-limit keys (which contain IP addresses) in memory only, as the privacy policy promises |
| `postgres` | `postgres:17` | data | Volume `pg_data`; reachable only on the internal `data` network |

`data` is an internal network with no internet access. The egress firewall rules stay as they are and
cover the worker, which is the container that loads untrusted pages.

### Scan flow

1. `POST /api/scans` with `{target}`. The API applies rate limits (Redis), handles UPI links inline (they
   need no fetching), then:
   - if `result:<normalised target>` is in Redis (15-minute cache), it returns `{id, status: "done"}`;
   - if the queue already holds 200 waiting jobs, it returns 503 "busy, try again shortly";
   - otherwise it creates a random 128-bit job id, enqueues the scan and returns `202 {id}`.
2. The worker runs `scanner.scan(target, progress=...)`. The scanner calls `progress(step, status,
   detail)` as each check finishes (certificate, headers, email records, lookalike name, domain age,
   certificate history, each blocklist, the page render, the URL model). Events go to the Redis stream
   `scan:<id>`, which expires after an hour.
3. `GET /api/scans/<id>/events` streams those events to the browser with Server-Sent Events, ending with
   the full report. `GET /api/scans/<id>` returns the current state or result, for clients that poll.
4. Results stay in Redis for 24 hours. History for signed-in users is written to Postgres, as today.
5. **Sharing** (`POST /api/scans/<id>/share`) copies the result to Postgres and returns `/r/<id>`, kept
   for 30 days. Only results someone chooses to share are kept longer than a day. The privacy policy
   gains a sentence saying so.

`POST /api/scan` (today's endpoint) stays: it enqueues a job and waits for the result, so the current
page works unchanged until the Phase 2 UI replaces it.

### Changes to existing code

- `scanner.scan`: an optional `progress` callback. No change to what is checked.
- `render.py`: unchanged, but only workers import and run it; the API's startup self-test moves to the
  worker, and the worker reports its health to Redis every 15 seconds. `/healthz` checks Redis, Postgres
  and that at least one worker reported in the last minute.
- `main.py`: the in-memory `RateLimiter` becomes a Redis sliding window with the same rules and messages.
  Keys hold an HMAC of the IP address rather than the address itself. `_check_cache` moves to Redis.
- `db.py`: the same functions, rewritten on Postgres with `psycopg` and a connection pool, so `main.py`
  barely changes. Schema in `migrations/001_initial.sql`, applied at startup.
- New `worker.py` (Arq settings and the scan job) and `jobs.py` (enqueue, progress, result cache, used by
  the API).
- `tools/migrate_sqlite.py`: copies users, sessions, history, tokens and reports from the live SQLite
  file into Postgres once, at deploy time.

### Failure handling

- Scan timeout of 45 s inside the job; on timeout or error the stream gets an `error` event and the
  visitor sees the same messages as today.
- A worker that dies mid-scan: Arq retries the job once on another worker; a second failure is reported
  as an error.
- Redis down: the API returns 503 for scans (it can't queue them) and `/healthz` reports degraded. Pages,
  sign-in and history (Postgres) keep working.
- Postgres down: sign-in and history fail with 503; anonymous scans continue.

### Testing

- Unit tests with `fakeredis` for the rate limiter, cache, job state and progress stream.
- The existing suites (`tests/regress.py`, `test_email.py`, `test_features.py`) run against Postgres.
- An end-to-end test: enqueue a scan of a local test page, follow its events to the final report.
- Load test (k6): (a) API and queue capacity with a stub scanner, so no real sites are hit; (b) real
  scan throughput for 1, 2 and 3 workers, scanning a fixed list of 50 popular sites slowly. The numbers go
  in `docs/load-test.md`.

### Out of scope here

The React UI (Phase 2), the page model and Domain watch (Phases 3 and 4), the public API with keys and
metrics dashboards (Phase 5), and a second server. The design allows each of them later without changes
to the queue.

## Open question

Docker isn't installed on the development laptop, and Redis and Postgres are run most simply in Docker.
Options: install Docker Desktop locally (recommended); or develop against a separate test copy on the
server, on its own ports.
