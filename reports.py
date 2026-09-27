"""Review site reports sent from the Artemis website.

    python reports.py              reports not yet reviewed, newest first
    python reports.py --all        every report kept (reports are deleted after a year)
    python reports.py done SITE    mark every report for SITE (a domain or UPI ID) as reviewed

In the Docker deployment, run these inside the app container, e.g.
    docker compose exec app python reports.py
"""
import re
import sys
from datetime import datetime

import db

UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f-\x9f]")   # reports come from the public: never let them drive the terminal


def clean(text: str) -> str:
    return UNPRINTABLE.sub(" ", text)


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "done":
        changed = db.mark_reports_reviewed(argv[1].strip().lower())
        print(f"Marked {changed} report(s) for {clean(argv[1])} as reviewed.")
        return 0
    if argv not in ([], ["--all"]):
        print(__doc__)
        return 2
    rows = db.reports(include_reviewed=argv == ["--all"])
    if not rows:
        print("No reports to review.")
        return 0
    for row in rows:
        when = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M")
        status = "  (reviewed)" if row["reviewed"] else ""
        print(f"#{row['id']}  {when}  {row['category']:<9} {clean(row['host'])}  "
              f"[{row['reports_for_site']} report(s) for this site]{status}")
        if row["target"] != row["host"]:
            print(f"      {clean(row['target'])}")
        if row["details"]:
            print(f"      Note: {clean(row['details'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
