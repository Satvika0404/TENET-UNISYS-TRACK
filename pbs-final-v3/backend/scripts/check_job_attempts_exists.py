import sqlite3
from app.core.config import settings

con = sqlite3.connect(settings.db_path)
row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_attempts'").fetchone()
print("db_path =", settings.db_path)
print("job_attempts =", row)
con.close()
