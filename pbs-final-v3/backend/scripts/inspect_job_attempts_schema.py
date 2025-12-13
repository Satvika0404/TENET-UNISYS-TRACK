import sqlite3
from app.core.config import settings

con = sqlite3.connect(settings.db_path)
cols = con.execute("PRAGMA table_info(job_attempts)").fetchall()
con.close()

print("job_attempts columns:")
for c in cols:
    # (cid, name, type, notnull, dflt_value, pk)
    print("-", c[1], c[2], "pk" if c[5] else "")
