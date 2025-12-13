from __future__ import annotations

import sqlite3
import uuid
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings


def _now() -> str:
    return datetime.utcnow().isoformat()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(settings.db_path)
    con.row_factory = sqlite3.Row
    return con


def create_attempt(job_row: Dict[str, Any]) -> str:
    """
    Call this immediately after a worker claims a job and before dispatch().
    attempt_no should match jobs.attempts (which is incremented in claim_next_job).
    """
    attempt_id = str(uuid.uuid4())
    attempt_no = int(job_row.get("attempts") or 1)

    payload = (
        attempt_id,
        job_row.get("job_id"),
        attempt_no,
        job_row.get("chosen_resource_id"),
        job_row.get("chosen_resource_type"),
        _now(),
        None,  # finished_at
        "RUNNING",
        job_row.get("predicted_latency_ms"),
        job_row.get("predicted_cost_usd"),
        job_row.get("final_score"),
        int(job_row.get("sla_ok") or 0),
        job_row.get("sla_violations_json") or "[]",
        job_row.get("features_json"),
        None, None, None, None, None, None,
        None, None
    )

    with _conn() as con:
        con.execute(
            """
            INSERT INTO job_attempts (
              attempt_id, job_id, attempt_no,
              chosen_resource_id, chosen_resource_type,
              started_at, finished_at, status,
              predicted_latency_ms, predicted_cost_usd,
              final_score, sla_ok, sla_violations_json,
              features_json,
              actual_latency_ms, actual_cost_usd, output_ref,
              error_class, error_message, traceback,
              rerouted_from_resource_id, rerouted_to_resource_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )

    return attempt_id


def update_attempt_features(attempt_id: str, features_json: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE job_attempts SET features_json=? WHERE attempt_id=?",
            (features_json, attempt_id),
        )


def mark_attempt_reroute(attempt_id: str, from_id: Optional[str], to_id: Optional[str]) -> None:
    with _conn() as con:
        con.execute(
            """
            UPDATE job_attempts
            SET rerouted_from_resource_id=?, rerouted_to_resource_id=?
            WHERE attempt_id=?
            """,
            (from_id, to_id, attempt_id),
        )


def finish_attempt_success(
    attempt_id: str,
    actual_latency_ms: float,
    actual_cost_usd: float,
    output_ref: Optional[str],
) -> None:
    with _conn() as con:
        con.execute(
            """
            UPDATE job_attempts
            SET finished_at=?, status='COMPLETED',
                actual_latency_ms=?, actual_cost_usd=?, output_ref=?
            WHERE attempt_id=?
            """,
            (_now(), float(actual_latency_ms), float(actual_cost_usd), output_ref, attempt_id),
        )


def finish_attempt_failure(
    attempt_id: str,
    error_class: str,
    error_message: str,
    traceback_str: str,
) -> None:
    with _conn() as con:
        con.execute(
            """
            UPDATE job_attempts
            SET finished_at=?, status='FAILED',
                error_class=?, error_message=?, traceback=?
            WHERE attempt_id=?
            """,
            (_now(), error_class, error_message, traceback_str, attempt_id),
        )


def list_attempts_for_job(job_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            """
            SELECT *
            FROM job_attempts
            WHERE job_id=?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (job_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]
