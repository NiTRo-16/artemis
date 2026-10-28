"""Collect new phishing links, scan what hasn't been scanned yet, and refresh the report.

Meant to run every few hours, because phishing sites go offline fast. On the server, cron runs it inside a
container built from the app's image, so the scans use the same sandboxed browser and egress firewall as
the live site (see evaluation/README.md). Output goes to evaluation/data/scheduled.log.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "evaluation" / "data" / "scheduled.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SCANS_PER_RUN = os.environ.get("SCANS_PER_RUN", "150")   # small enough to finish well within one interval
WORKERS = os.environ.get("SCAN_WORKERS", "2")            # gentle on a small server that also serves the site
STEPS = [
    ["evaluation/collect.py", "phishing"],
    ["evaluation/run.py", "--limit", SCANS_PER_RUN, "--workers", WORKERS],
    ["evaluation/report.py"],
]


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"=== {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        log.flush()
        for step in STEPS:
            result = subprocess.run([sys.executable, *step], cwd=ROOT, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            if step[0].endswith("report.py"):
                lines = ["report updated: evaluation/data/report.md"]
            else:   # the summary lines and the final count, not every progress line or the browser's noise
                out = [l for l in result.stdout.splitlines() if l.strip()]
                progress = [l for l in out if l.endswith(" scanned")]
                lines = [l for l in out if not l.endswith(" scanned")] + progress[-1:]
            if result.returncode != 0:
                lines.append(f"{step[0]} exited with code {result.returncode}: {result.stderr.strip()[-500:]}")
            log.write("\n".join(lines) + "\n")
            log.flush()


if __name__ == "__main__":
    sys.exit(main())
