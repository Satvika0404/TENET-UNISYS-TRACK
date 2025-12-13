import sqlite3
from app.core.config import settings

con = sqlite3.connect(settings.db_path)
rows = con.execute(
    "SELECT chosen_resource_type, actual_cost_usd "
    "FROM jobs "
    "WHERE status='COMPLETED' AND actual_cost_usd IS NOT NULL"
).fetchall()
con.close()

d = {}
for t, c in rows:
    d.setdefault(t, []).append(float(c))

out = {}
for k, v in d.items():
    v.sort()
    out[k] = {
        "n": len(v),
        "min": v[0],
        "mean": sum(v) / len(v),
        "max": v[-1],
    }

print(out)
