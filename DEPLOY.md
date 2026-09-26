# Deploying Artemis

Artemis runs as two containers: the app (FastAPI plus a sandboxed headless Chromium) and Caddy, which
serves HTTPS for your domain and renews certificates automatically. Only Caddy is reachable from the
internet.

## What you need

- A Linux server (Ubuntu 22.04/24.04 or Debian 12) with at least 2 GB of RAM.
- Docker Engine with the Compose plugin (`docker compose version` should work).
- Ports 80 and 443 open to the internet.
- Your domain's DNS **A record** (and **AAAA**, if the server has IPv6) pointing at the server.

## First deployment

1. Copy the project folder to the server, for example to `/opt/artemis`.

2. Create the settings file and fill in `DOMAIN` and `ACME_EMAIL`:

   ```bash
   cd /opt/artemis
   cp .env.example .env
   nano .env
   ```

   Account emails need an SMTP provider (for example Resend, Postmark, Brevo, Mailgun or Amazon SES).
   Put its SMTP details in `SMTP_*`, and set `MAIL_FROM` to an address on your domain. Add the SPF and
   DKIM DNS records your provider gives you, or the emails will land in spam. Without `SMTP_HOST` the
   deployment refuses to start, since nobody could confirm an account.

3. Build and start:

   ```bash
   docker compose up -d --build
   ```

   The first build downloads the Playwright base image (about 2 GB).

4. Block the app from reaching private networks (run as root):

   ```bash
   sudo sh deploy/egress-firewall.sh
   ```

   To reapply it after every reboot, install it as a service (adjust the path if the project isn't in
   `/opt/artemis`):

   ```bash
   sudo tee /etc/systemd/system/artemis-firewall.service >/dev/null <<'EOF'
   [Unit]
   Description=Artemis egress firewall
   After=docker.service
   Requires=docker.service

   [Service]
   Type=oneshot
   ExecStart=/bin/sh /opt/artemis/deploy/egress-firewall.sh

   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl enable --now artemis-firewall.service
   ```

## Check it works

```bash
docker compose ps                          # app should show "healthy"
curl https://YOUR-DOMAIN/healthz           # {"status":"ok"}
docker compose logs app | grep self-test   # "Headless browser self-test passed"
```

Then open `https://YOUR-DOMAIN`, scan a site, and scan a link to confirm the page check runs.
Sign up with your own address to check the confirmation email arrives and its link works; then try
"Forgot password" the same way.

To confirm the firewall, this must fail (time out or be refused):

```bash
docker compose exec app python -c "import urllib.request; urllib.request.urlopen('http://169.254.169.254/', timeout=3)"
```

## Updating

Copy the new files over the old ones, then:

```bash
docker compose up -d --build
```

The certificates live in the `caddy_data` volume and the accounts database in `artemis_data`. Both survive
rebuilds. Don't delete them.

## Backups

`artemis_data` holds user accounts, settings and scan history. Back it up regularly, for example daily:

```bash
docker compose exec app python -c "import sqlite3; sqlite3.connect('/app/data/artemis.db').backup(sqlite3.connect('/app/data/backup.db'))"
docker compose cp app:/app/data/backup.db ./artemis-backup-$(date +%F).db
```

The backup contains email addresses and password hashes: store it somewhere private.

## Logs

Visitor IP addresses are written in exactly one place: Caddy's access log, in the `caddy_logs` volume.
It rolls over daily and old files are deleted automatically, so no entry is kept longer than 14 days,
the period stated in the privacy policy. Caddy's healthcheck passes through it every 10 minutes, which
keeps the daily rotation running even when nobody visits. The app itself logs no requests.

To read it:

```bash
docker compose exec caddy sh -c 'tail -n 20 /logs/access.log'
```

If you change the retention period, change `roll_keep_for` in `deploy/Caddyfile` (the comment there
explains the arithmetic) and the privacy policy together.

## Troubleshooting

**`/healthz` returns 503 (`degraded`), or Caddy never starts.** Caddy waits for the app to be
healthy, and the app is unhealthy when its browser self-test fails. Read the error in the app's log:

```bash
docker compose logs app | grep self-test
```

A sandbox error usually means the host kernel refuses the user namespaces Chromium's sandbox uses.
Ubuntu 23.10 and later restrict them by default. In order of preference:

1. Check `docker-compose.yml` still has the `seccomp=deploy/seccomp_profile.json` line.
2. Allow unprivileged user namespaces on the host: `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0`
   (make it permanent in `/etc/sysctl.d/`). This affects the whole host, so weigh it.
3. Last resort: set `ARTEMIS_CHROMIUM_SANDBOX=0` in `.env` and run `docker compose up -d`. Chromium then
   runs without its own sandbox and the container becomes the only boundary. Keep the firewall step.

**Every visitor hits the rate limit together.** The app isn't seeing real client IPs. Make sure you
reach it through Caddy and that `FORWARDED_ALLOW_IPS` is still set in `docker-compose.yml`.

**Certificate errors.** Check the DNS record points at this server and ports 80/443 are open, then
`docker compose logs caddy`.
