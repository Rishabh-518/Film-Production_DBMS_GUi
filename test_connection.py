from db import transaction

with transaction() as cur:
    cur.execute("SELECT version()")
    print(cur.fetchone()["version"])
