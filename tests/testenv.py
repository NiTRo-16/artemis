"""Settings shared by the test suites: a throwaway Postgres database, emptied before each suite.

Import it first in every suite. Needs docker-compose.dev.yml running.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://artemis:artemis@127.0.0.1:5432/artemis_test")
os.environ.setdefault("REDIS_URL", "fake://")
os.environ.setdefault("RATE_LIMIT_SECRET", "test-secret")

import db  # noqa: E402

db.init()
db.reset_for_tests()
