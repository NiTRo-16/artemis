# Phase 2: new front end

Status: proposed

## Goal

Replace today's single page (`index.html` + `app.js`, about 1,400 lines) with the design from
`mockup/index.html`: the portfolio-style frame, Geist fonts, tools in the header right after the logo,
10px-radius buttons, live scan progress and a full result page. Built with React and TypeScript.
Nothing that works today may be lost, and nothing shown may be fake.

## Decisions already made

- React + TypeScript, built with Vite.
- Tools without a backend yet (Message check, QR and UPI upload, Domain watch, API) appear in the header
  and open a "coming soon" page that says what the tool will do. No sample data on them.
- "Continue with Google" uses the existing backend (`/api/auth/google`); it shows when
  `/api/me` reports `google_signin: true`, which needs a Google OAuth client configured on the server.

## What has to keep working (today's features)

| Area | Features |
|---|---|
| Scan | Domain, link or UPI input; last 5 searches under the box (browser only, keyboard navigable); busy state; errors |
| Result | Risk score and level; security categories with grades and notes; findings with severity, location and fix; impersonation verdict, signals and facts; payment check for UPI and payment pages; visit decision with its criteria and a "Continue to site" link (same tab or new tab, from settings) |
| Risky sites | "Continue anyway" dialog listing every risk factor |
| Reporting | "Report this site" dialog (categories, details), plus the Google Safe Browsing report link |
| Accounts | Log in, sign up with the terms consent, forgot password, email sent screens, confirming an email and resetting a password from the emailed links (`/verify#token`, `/reset#token`), Continue with Google |
| Settings | Theme (system, light, dark), open sites in same tab, signed-in email, sign out, delete account (with the recent-sign-in rule for Google accounts) |
| History | Signed-in history list, clear history |
| Pages | Privacy and terms stay as they are (`privacy.html`, `terms.html`) |

## New

- Live progress: `POST /api/scans`, then the browser follows `/api/scans/<id>/events` (server-sent
  events) and fills the checklist and the risk ring as each check finishes.
- Result page at `/scan/<id>`, reloadable while the result is kept (24 hours).
- Share: "Share result" calls `/api/scans/<id>/share` and copies the `/r/<id>` link. `/r/<id>` shows the
  shared result read-only.
- Coming-soon pages: `/messages`, `/qr`, `/watch`, `/developers`.

The mock's screenshot, "looks like" comparison, redirect chain and model-explanation bars are left out:
the backend doesn't produce that data yet (Phases 3 and 4). The result page shows the model's reasons
where they already appear, as impersonation signals.

## Structure

```
web/                          Vite + React + TypeScript; `npm run build` writes web/dist
  index.html
  public/theme.js             sets the theme before the page draws (no flash); same as today
  src/
    main.tsx, App.tsx         router and the frame (header, footer)
    api.ts                    typed calls to the backend, one function per endpoint
    types.ts                  the report shape returned by the scanner
    styles/                   tokens.css (colours, fonts, both themes), base.css
    components/               Header, Button, StatusTag, RiskRing, Dialog, AuthDialog, SettingsDialog,
                              RiskDialog, ReportDialog, RecentSearches
    pages/                    ScanPage, ResultPage, SharedPage, HistoryPage, ComingSoonPage,
                              VerifyPage, ResetPage, NotFoundPage
    hooks/                    useAccount (session, settings), useScanEvents (the SSE stream)
```

- Routing with `react-router`. FastAPI serves `web/dist/index.html` for `/`, `/scan/*`, `/r/*`,
  `/messages`, `/qr`, `/watch`, `/developers`, `/history`, `/verify`, `/reset`, and `web/dist/assets`.
- Fonts self-hosted from npm packages (Geist, Geist Mono), never from Google Fonts: the privacy policy
  says the browser contacts no other service.
- The existing Content-Security-Policy (`script-src 'self'`) stays; the build emits no inline scripts.
- Docker: a Node build stage produces `web/dist`; the Python image copies it in.
- Development: `npm run dev` (Vite on port 5173) forwards `/api` to the backend on port 8000.

## Testing

- `npm run typecheck` and `npm run build` must pass.
- Vitest with Testing Library: the API client, recent searches, the SSE hook (with a fake EventSource),
  the result page rendering a real saved report (high-risk, official, UPI and unreachable examples
  captured from real scans), and the auth dialog's sign-up consent.
- A backend test that every client route returns the app and `/api/*` still returns JSON.
- Browser checks at desktop and phone width, both themes: scan, result, report, sign up, settings,
  history, share link.

## Out of scope

Backends for the coming-soon tools, Hindi, and restyling the privacy and terms pages.
