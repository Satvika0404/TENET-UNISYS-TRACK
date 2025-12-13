import sqlite3
from app.core.config import settings

con = sqlite3.connect(settings.db_path)
rows = con.execute("SELECT actual_cost_usd FROM jobs WHERE status='COMPLETED' AND actual_cost_usd IS NOT NULL").fetchall()
con.close()

vals = sorted(float(r[0]) for r in rows)
print("n=", len(vals))
if not vals:
    print("No completed jobs with actual_cost_usd found.")
else:
    print("min=", vals[0], "median=", vals[len(vals)//2], "max=", vals[-1])
