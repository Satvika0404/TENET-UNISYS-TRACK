PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS job_attempts (
  attempt_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL,

  chosen_resource_id TEXT,
  chosen_resource_type TEXT,

  started_at TEXT NOT NULL,
  finished_at TEXT,

  status TEXT NOT NULL,                 -- RUNNING / COMPLETED / FAILED / RETRY

  predicted_latency_ms REAL,
  predicted_cost_usd REAL,
  final_score REAL,
  sla_ok INTEGER,
  sla_violations_json TEXT,

  features_json TEXT,

  actual_latency_ms REAL,
  actual_cost_usd REAL,
  output_ref TEXT,

  error_class TEXT,
  error_message TEXT,
  traceback TEXT,

  rerouted_from_resource_id TEXT,
  rerouted_to_resource_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_job_id ON job_attempts(job_id);
CREATE INDEX IF NOT EXISTS idx_attempts_status ON job_attempts(status);
CREATE INDEX IF NOT EXISTS idx_attempts_resource ON job_attempts(chosen_resource_type, chosen_resource_id);
