#!/bin/sh
# Load test on the server: starts a throwaway copy of Artemis (docker-compose.loadtest.yml), runs
# loadtest/run.py against it with 1, 2 and 3 workers, then deletes the copy. Run from /opt/artemis as root:
#   sudo sh loadtest/server-run.sh
set -e
cd "$(dirname "$0")/.."
DC="docker compose -p artemis-loadtest -f docker-compose.yml -f docker-compose.loadtest.yml"
OUT="loadtest/results-$(date +%Y-%m-%d-%H%M).txt"
{ echo "server: $(nproc) CPUs, $(free -g | awk '/Mem:/ {print $2}') GB memory"; } | tee "$OUT"

$DC up -d --build app worker
for i in $(seq 1 60); do
  $DC ps app --format '{{.Status}}' | grep -q '(healthy)' && break
  sleep 5
done

for workers in 1 2 3; do
  $DC up -d --scale worker=$workers worker
  sleep 15   # let new workers start and report in
  echo "== workers=$workers (each runs 4 scans at once; a fake scan takes 1.8 s)" | tee -a "$OUT"
  $DC run --rm --no-deps -T -v "$PWD/loadtest:/app/loadtest:ro" app \
    python loadtest/run.py --base-url http://artemis-loadtest-app-1:8000 --users 50 --seconds 60 | tee -a "$OUT"
done

$DC down -v
echo "done; results in $OUT" | tee -a "$OUT"
