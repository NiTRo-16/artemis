# Playwright's image ships Chromium and its system libraries, built for playwright==1.63.0.
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
     payments.py reports.py ./
COPY index.html app.js theme.js privacy.html terms.html legal.css favicon.svg ./
COPY fonts ./fonts

# Accounts database. docker-compose.yml mounts a volume here so it survives rebuilds.
ENV ARTEMIS_DB=/app/data/artemis.db
RUN mkdir -p /app/data && chown pwuser:pwuser /app/data

# The image's unprivileged user. Chromium's sandbox also needs the seccomp profile set in docker-compose.yml.
USER pwuser
EXPOSE 8000

# /healthz returns 503 if the sandboxed browser failed its startup self-test, which marks the container unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# One worker: the rate limiter and the browser pool live in process memory.
# No access log here: Caddy's access log (deploy/Caddyfile) is the single, time-limited record of visitor IPs.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header", "--no-access-log"]
