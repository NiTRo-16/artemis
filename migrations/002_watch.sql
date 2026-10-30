-- Domain watch: suspect new domains seen in certificate logs, and how far each log has been read.

CREATE TABLE watch_domains (
    registrable TEXT PRIMARY KEY,
    brand       TEXT NOT NULL,
    reason      TEXT NOT NULL,
    host        TEXT NOT NULL,
    log         TEXT NOT NULL,
    first_seen  BIGINT NOT NULL,
    scan_job    TEXT,
    scan_time   BIGINT,
    outcome     TEXT
);
CREATE INDEX watch_domains_first_seen ON watch_domains (first_seen);
CREATE INDEX watch_domains_scan_time ON watch_domains (scan_time);

CREATE TABLE watch_logs (
    name         TEXT PRIMARY KEY,
    position     BIGINT NOT NULL,
    started      BIGINT NOT NULL,
    last_read    BIGINT NOT NULL,
    entries_read BIGINT NOT NULL DEFAULT 0,
    malformed    BIGINT NOT NULL DEFAULT 0,
    gaps         BIGINT NOT NULL DEFAULT 0,
    last_gap     BIGINT
);
