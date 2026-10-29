"""Copy accounts, sign-in sessions, scan history, email links and site reports from the old SQLite database
into Postgres. Run it once, when moving to Postgres:

    python tools/migrate_sqlite.py /app/data/artemis.db

It refuses to run if Postgres already has accounts, so nothing can be copied twice.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

# Parents before children, so foreign keys are satisfied as rows arrive.
TABLES = {
    "users": ["id", "email", "password_hash", "settings", "created_at", "email_verified", "google_sub"],
    "sessions": ["token_hash", "user_id", "expires_at"],
    "scans": ["id", "user_id", "target", "risk_score", "risk_label", "verdict", "scanned_at"],
    "email_tokens": ["token_hash", "user_id", "purpose", "expires_at"],
    "reports": ["id", "target", "host", "category", "details", "user_id", "created_at", "reviewed"],
}


def main(path: str) -> None:
    if not Path(path).exists():
        sys.exit(f"No SQLite database at {path}")
    db.init()
    if db._one("SELECT COUNT(*) AS n FROM users")["n"]:
        sys.exit("Postgres already has accounts, so nothing was copied.")
    source = sqlite3.connect(path)
    with db.pool().connection() as c, c.transaction():
        for table, columns in TABLES.items():
            present = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
            if not present:   # databases from before a feature existed lack its table
                print(f"{table}: not in this database, skipped")
                continue
            cols = [col for col in columns if col in present]   # and older ones lack some columns
            rows = source.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            if rows:
                with c.cursor() as cur:
                    cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                                    rows)
            print(f"{table}: {len(rows)} rows copied")
        for table in ("users", "scans", "reports"):   # new rows continue numbering after the copied ids
            c.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 0) + 1, false) FROM {table}")
    source.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
