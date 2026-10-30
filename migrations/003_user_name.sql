-- The name people give when they sign up. Empty for older accounts and Google accounts until they set one.

ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT '';
