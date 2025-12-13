"""
PBS Dispatch Worker (Layer 6 + Layer 7)

- Claims QUEUED jobs from SQLite
- Executes via adapter (simulated by default)
- Writes COMPLETED / FAILED back to DB
- Appends job_events for UI visibility
- Captures features_json for ML training
- Layer 7: reroute on retry (exclude failed resource)
- NEW: writes attempt-level truth into job_attempts
"""

from __future__ import annotations

import os
import time
import uuid
import json
import traceback
from datetime import datetime, timedelta

from app.services.storage import (
    claim_next_job,
    update_job,
    add_job_event,
    get_job,
    latest_point,
)
from app.services.dispatcher import dispatch
from app.models.schemas import JobRequest
from app.services.features import build_features
from app.ml.feature_codec import to_dict
from app.services.routing import route

from app.services.attempts import (
    create_attempt,
    update_attempt_features,
    mark_attempt_reroute,
    finish_attempt_success,
    finish_attempt_failure,
)

POLL_S = float(os.getenv("WORKER_POLL_S", "1.0"))
WORKER_ID = os.getenv("WORKER_ID", str(uuid.uuid4())[:8])
REROUTE_ON_RETRY = os.getenv("REROUTE_ON_RETRY", "1") == "1"


def _backoff_iso(attempts: int) -> str:
    delay = min(60, 2 ** max(1, attempts))
    return (datetime.utcnow() + timedelta(seconds=delay)).isoformat()


def _reroute_job(latest: dict, attempt_id: str) -> bool:
    """
    Reroute a job to a different resource after failure.
    Writes reroute info to both job_events and job_attempts.
    """
    try:
        jr = latest.get("job_request_json")
        if not jr:
            return False
        job_req = JobRequest.model_validate_json(jr)

        hints = dict(job_req.hints or {})
        ex = list(hints.get("exclude_resource_ids") or [])
        cur = latest.get("chosen_resource_id")
        if cur and cur != "none":
            ex.append(cur)
        hints["exclude_resource_ids"] = list(dict.fromkeys(ex))
        job_req.hints = hints

        decision = route(job_req)
        if decision.chosen_resource_id == "none":
            add_job_event(latest["job_id"], "REROUTE_FAILED", "No alternative resource found")
            return False

        # update job row with new chosen resource + predicted scores
        chosen_score = None
        for item in decision.considered:
            if item["resource_id"] == decision.chosen_resource_id:
                chosen_score = item["score"]
                break

        update_job(
            latest["job_id"],
            chosen_resource_id=decision.chosen_resource_id,
            chosen_resource_type=decision.chosen_resource_type,
            predicted_latency_ms=float(chosen_score["latency_pred_ms"]) if chosen_score else None,
            predicted_cost_usd=float(chosen_score["cost_pred_usd"]) if chosen_score else None,
            final_score=float(chosen_score["final_score"]) if chosen_score else None,
            sla_ok=int(chosen_score["sla_ok"]) if chosen_score else 0,
            sla_violations_json=json.dumps(chosen_score.get("sla_violations", []) if chosen_score else []),
        )

        add_job_event(
            latest["job_id"],
            "REROUTED",
            f"{cur} -> {decision.chosen_resource_id} ({decision.chosen_resource_type})",
        )

        # record in attempt row (this attempt failed and caused reroute)
        mark_attempt_reroute(attempt_id, cur, decision.chosen_resource_id)
        return True

    except Exception as e:
        add_job_event(latest["job_id"], "REROUTE_ERROR", f"{e}")
        return False


def main():
    print(f"[worker] started worker_id={WORKER_ID} poll={POLL_S}s reroute={REROUTE_ON_RETRY}")
    while True:
        try:
            job = claim_next_job(WORKER_ID)
            if not job:
                time.sleep(POLL_S)
                continue

            job_id = job["job_id"]
            latest = get_job(job_id) or job

            if latest.get("status") == "CANCELLED":
                add_job_event(job_id, "SKIPPED", "Job was cancelled before dispatch")
                continue

            # create attempt row NOW (attempt_no already incremented by claim_next_job)
            attempt_id = create_attempt(latest)

            add_job_event(job_id, "RUNNING", f"claimed by worker_id={WORKER_ID} attempts={latest.get('attempts')}")

            # capture features for ML training
            job_req = None
            try:
                jr = latest.get("job_request_json")
                if jr:
                    job_req = JobRequest.model_validate_json(jr)
            except Exception:
                job_req = None

            tel = None
            try:
                rid = latest.get("chosen_resource_id")
                if rid and rid != "none":
                    tel = latest_point(rid)
            except Exception:
                tel = None

            if job_req and tel:
                f = build_features(tel, job_req)
                feats = to_dict(f)
                # Force categorical + routing-critical fields into features_json
                feats["job_type"] = job_req.job_type
                feats["resource_type"] = tel.resource_type
                feats["requires_gpu"] = bool(job_req.requires_gpu)
                feats["allow_sla_fallback"] = bool(job_req.allow_sla_fallback)

                # Optional but useful for learning SLA behavior later
                if job_req.sla:
                    feats["sla_deadline_ms"] = job_req.sla.deadline_ms
                    feats["sla_max_cost_usd"] = job_req.sla.max_cost_usd
                    feats["sla_min_reliability"] = job_req.sla.min_reliability

                feats_json = json.dumps(feats, ensure_ascii=False)

                update_job(job_id, features_json=feats_json)
                update_attempt_features(attempt_id, feats_json)

                add_job_event(job_id, "FEATURES_CAPTURED", "Saved features_json for ML training")
            else:
                add_job_event(job_id, "FEATURES_SKIPPED", "Missing job_request_json or telemetry")

            try:
                res = dispatch(latest)

                update_job(
                    job_id,
                    status="COMPLETED",
                    actual_latency_ms=float(res.actual_latency_ms),
                    actual_cost_usd=float(res.actual_cost_usd),
                    output_ref=res.output_ref,
                    worker_id=WORKER_ID,
                )

                finish_attempt_success(
                    attempt_id,
                    actual_latency_ms=float(res.actual_latency_ms),
                    actual_cost_usd=float(res.actual_cost_usd),
                    output_ref=res.output_ref,
                )

                add_job_event(job_id, "COMPLETED", f"latency_ms={res.actual_latency_ms} cost_usd={res.actual_cost_usd} output={res.output_ref}")

            except Exception as e:
                tb = traceback.format_exc()

                finish_attempt_failure(
                    attempt_id,
                    error_class=type(e).__name__,
                    error_message=str(e),
                    traceback_str=tb,
                )

                latest2 = get_job(job_id) or latest
                attempts = int(latest2.get("attempts") or 1)
                max_attempts = int(latest2.get("max_attempts") or 2)

                # reroute before retry
                if REROUTE_ON_RETRY and attempts < max_attempts:
                    _reroute_job(latest2, attempt_id)

                if attempts < max_attempts:
                    nr = _backoff_iso(attempts)
                    update_job(job_id, status="QUEUED", next_run_at=nr, worker_id=None)
                    add_job_event(job_id, "RETRY", f"{e} | next_run_at={nr}")
                else:
                    update_job(job_id, status="FAILED", worker_id=WORKER_ID)
                    add_job_event(job_id, "FAILED", tb)

        except KeyboardInterrupt:
            print("[worker] stopped by user")
            return
        except Exception as e:
            print("[worker] LOOP ERROR:", e)
            print(traceback.format_exc())
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
