# Stage 1: build the front end (web/) into static files.
FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Stage 2: the app. Playwright's image ships Chromium and its system libraries, built for playwright==1.63.0.
# Keep this tag and the playwright pin in requirements.txt on the same version.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py db.py mail.py google_auth.py netsafety.py scanner.py impersonation.py clone.py render.py brands.py \
     payments.py reports.py store.py ratelimit.py jobs.py worker.py messages.py ./
COPY privacy.html terms.html legal.css ./
COPY fonts ./fonts
COPY migrations ./migrations
COPY tools/migrate_sqlite.py ./tools/
COPY ml/__init__.py ml/url_features.py ml/url_model.py ./ml/
COPY ml/models/url_model.txt ml/models/url_model.json ./ml/models/
COPY --from=web /web/dist ./web/dist

# The old SQLite database, read once by tools/migrate_sqlite.py. docker-compose.yml mounts a volume here.
ENV ARTEMIS_DB=/app/data/artemis.db
RUN mkdir -p /app/data && chown pwuser:pwuser /app/data

# The image's unprivileged user. Chromium's sandbox also needs the seccomp profile set in docker-compose.yml.
USER pwuser
EXPOSE 8000

# /healthz returns 503 unless the database, Redis and at least one scan worker with a working browser are up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# The API. Several uvicorn workers can share the load because rate limits, caches and the job queue live
# in Redis. The scan worker uses this same image with the command `python worker.py` (docker-compose.yml).
# No access log here: Caddy's access log (deploy/Caddyfile) is the single, time-limited record of visitor IPs.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "3", "--no-server-header", "--no-access-log"]
