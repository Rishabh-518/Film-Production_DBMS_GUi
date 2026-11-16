import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from db_config import DB_SETTINGS

# Tests and screenshots set APP_DBNAME to use a copy of the database.
SETTINGS = {**DB_SETTINGS, "dbname": os.environ.get("APP_DBNAME", DB_SETTINGS["dbname"])}


@contextmanager
def transaction():
    """Yield a cursor. Commits if the block succeeds, rolls back if it raises."""
    conn = psycopg2.connect(**SETTINGS)
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        conn.close()
