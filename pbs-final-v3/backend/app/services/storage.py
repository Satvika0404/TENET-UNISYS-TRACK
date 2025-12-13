import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from ..core.config import settings
from ..models.schemas import TelemetryPoint, ResourceSnapshot

DDL = """CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  cpu_util REAL,
  mem_util REAL,
  gpu_util REAL,
  net_rtt_ms REAL,
  net_bw_mbps REAL,
  price_per_hour_usd REAL,
  reliability REAL,
  power_w REAL,
  extra_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_resource_ts ON telemetry(resource_id, ts);

-- Job lifecycle (queue + dispatch)
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  urgency REAL,
  payload_size_mb REAL,
  requires_gpu INTEGER,
  allow_sla_fallback INTEGER,

  sla_deadline_ms INTEGER,
  sla_max_cost_usd REAL,
  sla_min_reliability REAL,

  job_request_json TEXT,

  status TEXT NOT NULL, -- QUEUED | RUNNING | COMPLETED | FAILED | BLOCKED | CANCELLED
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 2,
  next_run_at TEXT, -- optional backoff timestamp ISO

  chosen_resource_id TEXT,
  chosen_resource_type TEXT,
  worker_id TEXT,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  predicted_latency_ms REAL,
  predicted_cost_usd REAL,
  final_score REAL,
  sla_ok INTEGER,
  sla_violations_json TEXT,

  actual_latency_ms REAL,
  actual_cost_usd REAL,
  output_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_updated ON jobs(status, updated_at);

-- Job events/logs for the UI
CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  job_id TEXT NOT NULL,
  event TEXT NOT NULL,
  message TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_events_job_ts ON job_events(job_id, ts);

-- Optional pricing cache (Layer 1 realism)
CREATE TABLE IF NOT EXISTS pricing_cache (
  key TEXT PRIMARY KEY,
  price_per_hour_usd REAL NOT NULL,
  updated_at TEXT NOT NULL
);
"""

def _conn() -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

CONN = _conn()

# Apply DDL safely
for stmt in DDL.strip().split(";"):
    s = stmt.strip()
    if s:
        CONN.execute(s)
CONN.commit()
def _safe_add_column(table: str, coldef: str) -> None:
    try:
        CONN.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        CONN.commit()
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "duplicate column name" in msg:
            return
        raise

# ML training fields
_safe_add_column("jobs", "features_json TEXT")
_safe_add_column("jobs", "latency_model_version TEXT")
_safe_add_column("jobs", "cost_model_version TEXT")

def _safe_add_column(table: str, coldef: str) -> None:
    try:
        CONN.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        CONN.commit()
    except sqlite3.OperationalError as e:
        # ok if column already exists
        if "duplicate column name" in str(e).lower():
            return
        raise

# store the feature vector used for training
_safe_add_column("jobs", "features_json TEXT")
_safe_add_column("jobs", "latency_model_version TEXT")

# ---- Telemetry ----

def insert_point(p: TelemetryPoint) -> None:
    CONN.execute(
        """INSERT INTO telemetry (ts, resource_id, resource_type, cpu_util, mem_util, gpu_util,
            net_rtt_ms, net_bw_mbps, price_per_hour_usd, reliability, power_w, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            p.ts.isoformat(),
            p.resource_id,
            p.resource_type,
            float(p.cpu_util),
            float(p.mem_util),
            float(p.gpu_util),
            float(p.net_rtt_ms),
            float(p.net_bw_mbps),
            float(p.price_per_hour_usd),
            float(p.reliability),
            float(p.power_w),
            json.dumps(p.extra, ensure_ascii=False),
        ),
    )
    CONN.commit()

def latest_point(resource_id: str) -> Optional[TelemetryPoint]:
    cur = CONN.execute(
        """SELECT ts, resource_id, resource_type, cpu_util, mem_util, gpu_util, net_rtt_ms, net_bw_mbps,
                  price_per_hour_usd, reliability, power_w, extra_json
           FROM telemetry
           WHERE resource_id = ?
           ORDER BY ts DESC
           LIMIT 1""",
        (resource_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    extra = json.loads(row["extra_json"] or "{}")
    return TelemetryPoint(
        ts=datetime.fromisoformat(row["ts"]),
        resource_id=row["resource_id"],
        resource_type=row["resource_type"],
        cpu_util=row["cpu_util"] or 0.0,
        mem_util=row["mem_util"] or 0.0,
        gpu_util=row["gpu_util"] or 0.0,
        net_rtt_ms=row["net_rtt_ms"] or 0.0,
        net_bw_mbps=row["net_bw_mbps"] or 0.0,
        price_per_hour_usd=row["price_per_hour_usd"] or 0.0,
        reliability=row["reliability"] or 0.98,
        power_w=row["power_w"] or 50.0,
        extra=extra,
    )

def list_resources_latest(limit: int = 100) -> List[ResourceSnapshot]:
    cur = CONN.execute(
        """SELECT t1.ts, t1.resource_id, t1.resource_type, t1.cpu_util, t1.mem_util, t1.gpu_util, t1.net_rtt_ms, t1.net_bw_mbps,
                  t1.price_per_hour_usd, t1.reliability, t1.power_w, t1.extra_json
           FROM telemetry t1
           INNER JOIN (
              SELECT resource_id, MAX(ts) AS max_ts
              FROM telemetry
              GROUP BY resource_id
           ) t2
           ON t1.resource_id = t2.resource_id AND t1.ts = t2.max_ts
           ORDER BY t1.resource_type, t1.resource_id
           LIMIT ?""",
        (limit,),
    )
    out: List[ResourceSnapshot] = []
    for row in cur.fetchall():
        extra = json.loads(row["extra_json"] or "{}")
        p = TelemetryPoint(
            ts=datetime.fromisoformat(row["ts"]),
            resource_id=row["resource_id"],
            resource_type=row["resource_type"],
            cpu_util=row["cpu_util"] or 0.0,
            mem_util=row["mem_util"] or 0.0,
            gpu_util=row["gpu_util"] or 0.0,
            net_rtt_ms=row["net_rtt_ms"] or 0.0,
            net_bw_mbps=row["net_bw_mbps"] or 0.0,
            price_per_hour_usd=row["price_per_hour_usd"] or 0.0,
            reliability=row["reliability"] or 0.98,
            power_w=row["power_w"] or 50.0,
            extra=extra,
        )
        out.append(ResourceSnapshot(resource_id=p.resource_id, resource_type=p.resource_type, last=p))
    return out

# ---- Pricing cache ----

def get_cached_price(key: str) -> Optional[Dict[str, Any]]:
    cur = CONN.execute("SELECT price_per_hour_usd, updated_at FROM pricing_cache WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return None
    return {"price_per_hour_usd": float(row["price_per_hour_usd"]), "updated_at": row["updated_at"]}

def set_cached_price(key: str, price_per_hour_usd: float, updated_at: str) -> None:
    CONN.execute(
        """INSERT INTO pricing_cache(key, price_per_hour_usd, updated_at)
           VALUES(?,?,?)
           ON CONFLICT(key) DO UPDATE SET
             price_per_hour_usd=excluded.price_per_hour_usd,
             updated_at=excluded.updated_at""",
        (key, float(price_per_hour_usd), updated_at),
    )
    CONN.commit()

# ---- Jobs + Dispatch Queue ----

def upsert_job(job_row: Dict[str, Any]) -> None:
    cols = ",".join(job_row.keys())
    placeholders = ",".join(["?"] * len(job_row))
    updates = ",".join([f"{k}=excluded.{k}" for k in job_row.keys() if k != "job_id"])
    CONN.execute(
        f"INSERT INTO jobs ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(job_id) DO UPDATE SET {updates}",
        tuple(job_row.values()),
    )
    CONN.commit()

def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = fields.get("updated_at") or datetime.utcnow().isoformat()
    sets = ", ".join([f"{k}=?" for k in fields.keys()])
    vals = list(fields.values()) + [job_id]
    CONN.execute(f"UPDATE jobs SET {sets} WHERE job_id=?", vals)
    CONN.commit()

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    cur = CONN.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def list_jobs(limit: int = 200) -> List[Dict[str, Any]]:
    cur = CONN.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]

def add_job_event(job_id: str, event: str, message: str = "") -> None:
    CONN.execute(
        "INSERT INTO job_events(ts, job_id, event, message) VALUES(?,?,?,?)",
        (datetime.utcnow().isoformat(), job_id, event, message),
    )
    CONN.commit()

def list_job_events(job_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    cur = CONN.execute(
        "SELECT ts, job_id, event, message FROM job_events WHERE job_id=? ORDER BY ts DESC LIMIT ?",
        (job_id, limit),
    )
    return [dict(r) for r in cur.fetchall()]

def claim_next_job(worker_id: str) -> Optional[Dict[str, Any]]:
    """Atomically claim 1 QUEUED job for this worker."""
    now = datetime.utcnow().isoformat()
    CONN.execute("BEGIN IMMEDIATE")
    try:
        cur = CONN.execute(
            """SELECT * FROM jobs
               WHERE status='QUEUED'
                 AND (next_run_at IS NULL OR next_run_at <= ?)
               ORDER BY created_at ASC
               LIMIT 1""",
            (now,),
        )
        row = cur.fetchone()
        if not row:
            CONN.execute("COMMIT")
            return None

        job_id = row["job_id"]
        res = CONN.execute(
            """UPDATE jobs
               SET status='RUNNING', worker_id=?, updated_at=?, attempts=attempts+1, next_run_at=NULL
               WHERE job_id=? AND status='QUEUED'""",
            (worker_id, now, job_id),
        )
        if res.rowcount != 1:
            CONN.execute("COMMIT")
            return None
        CONN.execute("COMMIT")
        return dict(row)
    except Exception:
        CONN.execute("ROLLBACK")
        raise


def count_jobs(status: str) -> int:
    cur = CONN.execute("SELECT COUNT(*) AS n FROM jobs WHERE status=?", (status,))
    row = cur.fetchone()
    return int(row["n"]) if row else 0
def set_job_features(job_id: str, features: dict, latency_model_version: str | None = None) -> None:
    now = datetime.utcnow().isoformat()
    CONN.execute(
        "UPDATE jobs SET features_json=?, latency_model_version=?, updated_at=? WHERE job_id=?",
        (json.dumps(features, ensure_ascii=False), latency_model_version, now, job_id),
    )
    CONN.commit()
