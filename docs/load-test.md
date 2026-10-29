# Load test results

Measured on the live server (Oracle Cloud Always Free, VM.Standard.A1.Flex: 4 Arm CPUs, 24 GB memory)
on 29 October 2026, against a throwaway copy of Artemis running beside the live site
(`loadtest/server-run.sh`, `docker-compose.loadtest.yml`). The copy had its own Redis and Postgres, no
internet access, and nothing published outside the server; it was deleted afterwards.

## 1. The API and the job queue

50 simulated visitors started scans as fast as they could for 60 seconds, each waiting for its result
before starting the next. Every scan was a new domain, so no result came from the 15-minute cache. The
workers faked each scan (six steps of 0.3 s, so 1.8 s a scan) to measure Artemis's own overhead without
contacting any site. Each worker runs 4 scans at once.

| Workers | Scans finished per minute | Most a worker can do (4 × 60 / 1.8) | Time to start a scan (median, 95th percentile) | Time to result (median, 95th percentile) | Refused |
|---|---|---|---|---|---|
| 1 | 128 | 133 | 46 ms, 195 ms | 22.1 s, 23.8 s | none |
| 2 | 256 | 267 | 46 ms, 171 ms | 10.9 s, 12.5 s | none |
| 3 | 384 | 400 | 46 ms, 131 ms | 7.5 s, 8.7 s | none |

The per-minute counts exclude the 50 scans still running when the minute ended (the first version of
`loadtest/run.py` counted them; it now reports only scans finished within the time).

What this shows:

- **Capacity grows in step with workers**: 128, 256, 384 scans a minute, each within 4% of the most the
  workers could do. The queue, Redis and the API add almost nothing.
- **Starting a scan stays fast under load**: a median of 46 ms with 50 visitors at once, whatever the
  number of workers. Visitors get their job id at once and wait in the queue, rather than the server
  slowing down or refusing them.
- **Waiting time is queueing**: with 50 visitors and 4 scans at a time, a scan waits behind about 12
  others (22 s). Each added worker shortens the wait in proportion.
- **No errors and no refusals** in 768 scans.

## 2. Real scans

From 606 real scans made by the evaluation pipeline on the same server between 28 and 29 October 2026,
each in the sandboxed browser with the egress firewall (303 phishing links from OpenPhish, 303 popular
sites from Tranco):

| Sites | Scans | Median time | 95th percentile |
|---|---|---|---|
| Online | 506 | 2.5 s | 9.9 s |
| Offline or unreachable | 98 | 1.1 s | |

A real scan takes longer than the fake one above and loads a page in Chromium (each worker renders at
most 2 pages at once), so real capacity is lower. With a median real scan of 2.5 s, one worker can finish
at most about 4 × 60 / 2.5 ≈ 96 scans a minute; slow sites and the browser limit lower that in practice.
More capacity comes from more workers (`docker compose up -d --scale worker=N`), on this server or another
one pointed at the same Redis and Postgres.

## How to repeat it

On the server, from `/opt/artemis`:

```bash
sudo sh loadtest/server-run.sh
```

It prints the results and saves them to `loadtest/results-<date>.txt`.
