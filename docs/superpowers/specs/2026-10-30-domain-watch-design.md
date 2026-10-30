# Domain watch

Read public certificate logs, spot new domains whose names copy a known brand, check them before anyone
asks, and use what we learn in scan results. No domain is ever published in a list.

## Goal

Today Artemis only learns about a fake site when someone scans it. A phishing site usually needs a
certificate before it goes live, and every certificate browsers trust is logged publicly, so the logs can
show a lookalike name early, sometimes before any blocklist has it.

First version, as chosen:

- A private watcher stores suspect new domains.
- Each is scanned once in the sealed browser, a little later, at a capped rate.
- A scan of a watched domain shows when its certificate first appeared.
- `/watch` shows honest counts per brand, and no domain names.

Out of scope for now: a public list of domains, brand alerts by email, the public API, reading every log,
scanning a domain more than once, and Hindi.

## Measurements (30 October 2026)

Taken from the live logs on this date, and the reason for the choices below.

| What | Measured |
|---|---|
| All 43 usable logs together | about 2,800 entries a second, 240 million a day, including one certificate logged several times |
| Let's Encrypt logs (Sycamore, Willow) | about 400 entries a second |
| Size of one entry | about 1.8 KB without compression |
| Let's Encrypt logs at that size | about 0.7 MB/s, about 60 GB a day, before compression |
| Existing `brand_lookalike` | about 1.6 ms a name, far too slow: about 90% of a core at Let's Encrypt's rate |

Reading everything would be about 430 GB a day, and much of it repeats. Let's Encrypt's old-format logs are
gone, so the newer tile format is required in any case.

## Coverage, stated plainly

The first version reads only the Let's Encrypt logs, which are in the tile format. They also hold
certificates from some other issuers, but not all. Sites whose certificates aren't logged there can be
missed, and `/watch` must say which logs are read. More tile-format logs (Google's, for example) are one
line of config each, added only after measuring CPU and bandwidth on the server. Old-format logs aren't read.

## How it works

```
log tiles -> watcher -> matcher -> watch_domains (Postgres) -> capped scans (existing queue) -> outcome saved
                                         |                                                         |
                                         +-------> scan result signal         /watch counts <------+
```

### `ct_logs.py`: reading

- Reads the log's public checkpoint, then the complete 256-entry data tiles after our position.
- Parses each entry with a small DER reader that pulls out only the names (SAN extension). It never trusts
  a length field, and a malformed entry is counted and skipped, never fatal. Log contents are untrusted input.
- Sends a User-Agent with a contact address, as log operators ask, and backs off on 429 and 5xx.
- The log list is a fixed setting in the code, with each half-year shard written out. Shards rotate, so a
  test fails once no configured shard covers the current date.

### `watch_match.py`: matching

- Compiled once from `BRANDS`: one regex over all keywords, plus a set of one-typo spellings of keywords of
  5 or more letters. Target: under 50 microseconds a name, checked by a test.
- Only names that pass go through the existing `brand_lookalike`, so the wording and rules stay in one place.
  Accepted limit: typos beyond one edit, which `brand_lookalike` would catch, are missed by the watcher.
- A brand's own domains are skipped using `official_brand`.
- **Loose keywords need a second clue.** Short ones ("sbi", "visa", "amex") and everyday words ("ledger",
  "outlook", "icloud") count only as a whole word in the registered part of the name, alongside a word like
  login, kyc, verify, secure, bank, pay, update or reward, or a TLD in `RISKY_TLDS`. Other keywords count on their
  own, as do the short but distinctive "hdfc", "icici", "paytm" and "npci".
- A brand's real address at the start of someone else's (`support.zoom.us.tokovpn.com`) always counts.
- Tested against real names from the logs, since the false-match rate decides whether the counts mean anything.
  On 76,800 real entries on 30 October 2026, these rules gave about 90 matches, or roughly 40,000 a day before
  repeats. Many look suspicious and some are innocent.

### `watcher.py`: the service

- A new Compose service, with one process limited to 1 CPU, so it can't starve scans. It uses the existing
  image, Postgres and Redis.
- Position per log is kept in Postgres and saved after each batch, so a restart loses nothing.
- First run starts at the current end of the log. There's no backfill.
- If it falls more than 1 hour behind, it jumps to the end and records the gap. `/watch` shows that time as a
  gap, rather than pretending coverage was continuous.

### Data

`watch_domains`: registrable domain (primary key), brand, reason, first host seen, first seen time, log, scan
outcome, scan time. Kept 90 days, then deleted.

`watch_logs`: log name, position, last read time, entries read, gaps.

Certificate logs are public and no user data is involved. Each domain is stored once, however many
certificates it gets.

### Capped scans

- A small loop in the watcher queues unscanned domains that are at least 10 minutes old, since a certificate
  often comes before the site.
- **Indian brands first, then newest.** Far more names match than can be scanned, mostly global brands, so
  otherwise almost no scan would go on the names Artemis exists to protect.
- Starts at **1,000 a day**. The limit isn't the queue but the outside services each scan calls (crt.sh, RDAP,
  Safe Browsing). It also pauses while the queue is busy, so people's scans always come first.
- Saves one outcome: `offline`, `no_form`, `login_or_card_form` or `flagged` (the risk result, no page content).
  Domains not scanned within 48 hours are marked `not_checked`.
- These scans need no account and appear in nobody's history.
- Scans are the existing passive visits. The sealed browser and its firewall aren't changed. Attacker sites may
  see our server's address and hide from it, so `no_form` never means safe.

### In scan results

When a scanned domain is in `watch_domains`, the impersonation card shows an information line: "A certificate
for this name first appeared in public logs on <date>." It **adds no risk points**: the name is already scored
by the lookalike check, and counting it twice would inflate risk for innocent businesses.

The benefit is a dependable first-seen date when crt.sh is slow or down. It isn't a new detection on its own, and it mustn't be described as one.

### `/watch` page and `GET /api/watch/summary`

- Replaces the "Coming soon" page. Cached for 5 minutes.
- Shows matches in the last 7 days per brand, how many had a login or card form when checked, the logs read, the
  time of the last read, and any gaps.
- Says plainly that a match is a name that resembles a brand, and many are innocent.
- Numbers are always real. A brand with none shows 0, and until the watcher has run a day the page says it has
  just started instead of showing partial totals as a week.
- If the watcher has stopped reading for over 1 hour, the page says so and when reading stopped.
- A box on the page leads to the normal scan. There's no lookup of whether a domain is on the list.
- Organisation brand watching stays described as planned, not available.

## Privacy and terms

The privacy policy gets a short note: Artemis reads public certificate logs and visits domains whose names
resemble known brands. No visitor data is involved. A wrongly matched owner sees only an automated visit, since
domains aren't published. Contact details stay as they are.

## Errors

| Failure | What happens |
|---|---|
| Log unreachable or rate limited | Back off and retry; position is kept. Over 1 hour shows on `/watch` |
| Malformed entry | Counted and skipped |
| Falls behind by over 1 hour | Jumps ahead and records the gap |
| Postgres down | Watcher waits and retries; nothing in the scan path depends on it |
| Matcher floods (a brand over 20,000 a day; the busiest measured about 8,000) | Logged and scanning for that brand paused for the day, as it points to a bad rule |
| Watch lookup fails during a scan | The line is left out; the scan is unaffected |

## Testing

- Reader: real tile fixtures saved from the log, plus truncated and corrupted entries.
- Matcher: real names from the logs, official domains never matched, short-keyword rules, one-typo and lookalike
  character cases, and the speed target.
- Watcher: resume after restart, the catch-up jump, the daily scan cap, and pausing while the queue is busy.
- API and page: real counts, zero and just-started states, stopped-reading notice, no domain name in any response.
- Scan result: the line appears for a watched domain and the risk score doesn't change.
- On the server, one week of measured CPU, bandwidth, matches a day and a hand review of a sample of matches
  before adding any log or raising the cap.

## Rollout

1. Deploy watcher with scans off and page still "coming soon"; measure a day.
2. Review a sample of matches by hand and tighten rules if needed.
3. Turn on capped scans at 1,000 a day.
4. After a day of data, open the `/watch` page and the result line.
