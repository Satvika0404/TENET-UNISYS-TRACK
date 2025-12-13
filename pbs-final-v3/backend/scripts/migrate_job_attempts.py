import sqlite3
from app.core.config import settings

DDL = """
CREATE TABLE IF NOT EXISTS job_attempts (
  attempt_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL,
  status TEXT NOT NULL,              -- RUNNING / COMPLETED / FAILED
  started_at TEXT NOT NULL,
  finished_at TEXT,
  resource_id TEXT,
  resource_type TEXT,

  -- model predictions (store both mean + p90)
  latency_pred_mean_ms REAL,
  latency_pred_p90_ms REAL,
  cost_pred_mean_usd REAL,
  cost_pred_p90_usd REAL,

  -- actuals
  actual_latency_ms REAL,
  actual_cost_usd REAL,

  -- training payloads
  telemetry_json TEXT,
  features_json TEXT,

  -- model versioning
  latency_model_version TEXT,
  cost_model_version TEXT,

  -- debug / learning from failures
  error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_attempts_job ON job_attempts(job_id);
CREATE INDEX IF NOT EXISTS idx_job_attempts_started ON job_attempts(started_at);
"""

con = sqlite3.connect(settings.db_path)
for stmt in DDL.strip().split(";"):
    s = stmt.strip()
    if s:
        con.execute(s)
con.commit()

row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_attempts'").fetchone()
print("created job_attempts:", row)
con.close()
