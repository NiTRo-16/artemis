# Artemis

Artemis checks a website's security and whether it's impersonating a known brand. Enter a domain or
paste a link, and it reports on the site's certificate, security headers, cookies and email records,
flags lookalike domains, fake login pages and payment scams, and says whether it's safe to continue.
It also checks UPI payment links.

All checks are passive: Artemis reads what an ordinary visitor's browser would receive. It never logs
in, probes for hidden pages or tests for vulnerabilities.

## What it checks

**Security**
- TLS certificate validity and expiry, TLS 1.3 support, HTTP to HTTPS redirect
- Security headers: HSTS, Content-Security-Policy, clickjacking protection, and others
- Cookie flags: `Secure`, `HttpOnly`, `SameSite`
- Email authentication records: SPF, DMARC, CAA
- Version numbers leaked in response headers

Each category gets a grade, and the site gets an overall risk score of Low, Medium or High.

**Impersonation**
- Lookalike domain names for about 70 commonly impersonated brands and payment providers: typos, swapped letters, characters
  from other alphabets, brand names in subdomains
- Domain age from registration records, and certificate history from public logs
- Phishing and malware lists: OpenPhish, plus Google Safe Browsing and URLhaus if you add API keys
- Fake login pages: password or card forms on a page presenting itself as a brand, forms that send data
  to another site, a brand's favicon or images copied. Pages are also opened in a sandboxed headless
  browser, so forms built by JavaScript are found too.

**Payments**
- UPI links (`upi://pay?...`) and UPI IDs: refund, prize or KYC bait, bank or police names in the payee,
  unusual link types. Read from the link alone; nothing is fetched.
- Payment pages on Razorpay, PayU, Cashfree, Stripe, PayPal and other providers: confirms the provider is
  real and checks the page for borrowed brand names and bait.
- Any page asking for a UPI PIN or ATM PIN, or card details on a new site, without HTTPS, or sent to
  another site. Card fields inside a provider's secure frame are recognised as the provider's.

**Reports**
Sites and UPI IDs showing warning signs get a "Report" button. Reports are stored for the team to review
with `reports.py` and never change a result by themselves. The dialog also links to Google Safe Browsing,
India's cybercrime portal and the 1930 helpline.

**Accounts (optional)**
Scanning works without an account. Signing up adds scan history, settings synced across devices and a
higher scan limit. Accounts use email confirmation and password reset, or "Continue with Google". The last
5 searches appear under the search bar for everyone, stored only in the browser.

**Chrome extension**
[`extension/`](extension/) warns before you open a site that's reported as phishing or likely
impersonating a brand. It sends only the domain, and only after the user turns warnings on. See
[extension/README.md](extension/README.md).

## Run it locally

Requires Python 3.12 or later.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn main:app --port 8000
```

Open http://localhost:8000. Locally, account emails (confirmation and reset links) are printed to the
server log instead of being sent, so sign-up works without an email provider.

## Configuration

Set these as environment variables. All are optional for local use.

| Variable | Purpose |
|---|---|
| `APP_URL` | Public address used in email links, e.g. `https://your-domain`. Defaults to `http://localhost:8000` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Email provider for account emails. `SMTP_SECURITY` is `starttls` (port 587) or `ssl` (port 465) |
| `MAIL_FROM` | Sender, e.g. `Artemis <no-reply@your-domain>` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Enables "Continue with Google". See DEPLOY.md |
| `SAFE_BROWSING_API_KEY` | Enables Google Safe Browsing lookups |
| `URLHAUS_AUTH_KEY` | Enables abuse.ch URLhaus lookups |
| `ARTEMIS_DB` | Path to the SQLite accounts database. Defaults to `data/artemis.db` |
| `ARTEMIS_CHROMIUM_SANDBOX` | Leave at `1`. See DEPLOY.md before changing it |

On a public domain the server refuses to report healthy without `SMTP_HOST`, since nobody could confirm
an account.

## Deploying

[DEPLOY.md](DEPLOY.md) covers the Docker setup: the app behind Caddy with automatic HTTPS, a host
firewall that stops the headless browser reaching private networks, log retention, backups and
troubleshooting. Copy [.env.example](.env.example) to `.env` to start.

## Project layout

| Path | What it does |
|---|---|
| `main.py` | Web server: pages, scan API, accounts, rate limits, security headers |
| `scanner.py` | Security checks and the risk score |
| `impersonation.py`, `brands.py` | Lookalike names, registration and certificate records, phishing lists |
| `clone.py` | Fake login page detection |
| `payments.py` | UPI link and payment page checks |
| `render.py` | Sandboxed headless browser for pages built by JavaScript |
| `netsafety.py` | The rule for which addresses Artemis may connect to (public only) |
| `db.py`, `mail.py` | Accounts database and account emails |
| `google_auth.py` | Google sign-in |
| `reports.py` | Command-line tool for reviewing site reports |
| `index.html`, `app.js`, `theme.js` | The website |
| `privacy.html`, `terms.html` | Privacy policy and terms |
| `extension/` | Chrome extension |
| `deploy/`, `Dockerfile`, `docker-compose.yml` | Deployment |

## Security

Everything Artemis fetches on a user's behalf is restricted to public internet addresses, checked at
every redirect and pinned to the checked address, so it can't be used to reach private networks. The
headless browser runs with Chromium's sandbox, a fresh profile per scan, and limits on requests, size
and time. To report a security problem, email artemis_secure@gmail.com.

## License

Artemis is released under the [MIT License](LICENSE). The third-party material below keeps its own
license.

## Third-party material

- Space Grotesk and IBM Plex Mono fonts, SIL Open Font License 1.1 (see `fonts/*-OFL.txt`)
- Chromium seccomp profile in `deploy/seccomp_profile.json`, from the Playwright project (Apache 2.0)
- Settings icon from Feather Icons (MIT)
- Google "G" logo on the sign-in button, a trademark of Google LLC, used as Google's sign-in branding
  guidelines require. It isn't covered by the MIT License.
