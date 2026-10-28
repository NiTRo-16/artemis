# Evaluation

Measures how well Artemis separates phishing sites from genuine ones, so changes (and a future machine
learning model) can be judged by numbers rather than impressions.

```bash
python evaluation/collect.py genuine --count 500     # genuine sites from the Tranco popular-sites list
python evaluation/collect.py phishing                # current links from the OpenPhish public feed
python evaluation/run.py                             # scan everything not scanned yet
python evaluation/report.py                          # detection and false-alarm rates
```

The OpenPhish public feed holds only about 300 current links. Run `collect.py phishing` and then
`run.py` every few hours to build up a larger set; phishing sites go offline quickly, so scan new links
soon after collecting them. Other phishing lists can be added with `collect.py phishing --file list.txt`.

Because the phishing links come from OpenPhish, which Artemis also checks, `report.py` gives two views:
**with blocklists** (Artemis as users get it) and **without blocklists** (only Artemis's own checks:
lookalike names, domain age, certificate age, page forms and payment signals). The second is the honest
measure of what Artemis adds. Every rate comes with a 95% confidence interval.

## Collecting on the server

`scheduled.py` runs the three steps (collect new phishing links, scan up to 100 of them, refresh the
report). On the server, cron runs it every 4 hours in a container built from the app's image, so scans use
the same sandboxed browser, seccomp profile and egress firewall as the live site:

```bash
sudo mkdir -p /opt/artemis/evaluation/data && sudo chown 1001:1001 /opt/artemis/evaluation/data
sudo tee /etc/cron.d/artemis-evaluation >/dev/null <<'EOF'
0 */4 * * * root cd /opt/artemis && flock -n /run/artemis-eval.lock docker compose run --rm --no-deps -T -e SCANS_PER_RUN=100 -v /opt/artemis/evaluation:/app/evaluation app python evaluation/scheduled.py >/dev/null 2>&1
EOF
```

Progress is in `evaluation/data/scheduled.log`. `flock` skips a run if the previous one is still going.

Data and results are written to `evaluation/data/`, which is not committed: the phishing links are live
malicious addresses, and the results are specific to when they were scanned.

**Safety:** `run.py` loads live phishing pages in Artemis's sandboxed browser. Run it on a server or a
virtual machine rather than a personal computer where possible.

**Licences:** OpenPhish and Tranco data are used here for research. Check each source's terms before
using the data to train a model for a commercial product.
