"""Copying an old SQLite database into Postgres."""
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import testenv  # noqa: F401
import db  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import migrate_sqlite  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


OLD_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
                    settings TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL, email_verified INTEGER NOT NULL DEFAULT 0,
                    google_sub TEXT);
CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE scans (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, target TEXT NOT NULL, risk_score INTEGER,
                    risk_label TEXT, verdict TEXT NOT NULL, scanned_at INTEGER NOT NULL);
CREATE TABLE email_tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, purpose TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE reports (id INTEGER PRIMARY KEY, target TEXT NOT NULL, host TEXT NOT NULL, category TEXT NOT NULL,
                      details TEXT NOT NULL DEFAULT '', user_id INTEGER, created_at INTEGER NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0);
"""
now = int(time.time())
path = Path(tempfile.mkdtemp()) / "old.db"
old = sqlite3.connect(path)
old.executescript(OLD_SCHEMA)
old.execute("INSERT INTO users VALUES (7, 'asha@example.com', ?, '{}', ?, 1, NULL)", (db.hash_password("a-long-password-1"), now))
old.execute("INSERT INTO sessions VALUES ('abc', 7, ?)", (now + 3600,))
old.execute("INSERT INTO scans VALUES (3, 7, 'github.com', 5, 'Low', 'Official GitHub domain', ?)", (now,))
old.execute("INSERT INTO reports VALUES (4, 'bad.example', 'bad.example', 'phishing', '', 7, ?, 0)", (now,))
old.commit()
old.close()

migrate_sqlite.main(str(path))
ok("password still works after copying", db.authenticate("asha@example.com", "a-long-password-1") is not None)
ok("history copied", [s["target"] for s in db.history(7)] == ["github.com"])
ok("report copied", db._one("SELECT COUNT(*) AS n FROM reports")["n"] == 1)
ok("new accounts get ids after the copied ones", db.create_user("new@example.com", "a-long-password-2") > 7)
try:
    migrate_sqlite.main(str(path))
    ok("refuses to copy twice", False)
except SystemExit:
    ok("refuses to copy twice", True)

# A database from before site reports existed has no reports table at all.
db.reset_for_tests()
early = Path(tempfile.mkdtemp()) / "early.db"
con = sqlite3.connect(early)
con.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                                         settings TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL);
                     CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL);""")
con.execute("INSERT INTO users VALUES (1, 'early@example.com', ?, '{}', ?)", (db.hash_password("a-long-password-3"), now))
con.commit()
con.close()
migrate_sqlite.main(str(early))
ok("an early database without some tables or columns copies what it has",
   db.authenticate("early@example.com", "a-long-password-3") is not None)
print(f"\n{sum(results)}/{len(results)} passed")
