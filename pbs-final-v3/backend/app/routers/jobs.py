from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import json

from ..models.schemas import JobRequest
from ..services.routing import route
from ..services.metrics_registry import JOB_SUBMITTED_COUNTER
from app.services.attempts import list_attempts_for_job

from ..services.storage import (
    upsert_job,
    update_job,
    get_job,
    list_jobs,
    add_job_event,
    list_job_events,
)

router = APIRouter(prefix="/jobs")
@router.get("/__whoami", summary="Debug: show which code is running")
def whoami():
    return {"whoami": "pbs-final-v3 jobs.py WITH sla-events BEFORE job_id", "ok": True}

class CompletePayload(BaseModel):
    actual_latency_ms: float
    actual_cost_usd: float
    output_ref: str | None = None

@router.post("", summary="Create + route + enqueue a job for dispatch")
def submit_job(job: JobRequest):
    decision = route(job)

    # Find chosen score (for predictions)
    chosen_score = None
    for item in decision.considered:
        if item["resource_id"] == decision.chosen_resource_id:
            chosen_score = item["score"]
            break

    now = datetime.utcnow().isoformat()
    status = "BLOCKED" if decision.chosen_resource_id == "none" else "QUEUED"

    row = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "urgency": float(job.urgency),
        "payload_size_mb": float(job.payload_size_mb),
        "requires_gpu": int(job.requires_gpu),
        "allow_sla_fallback": int(job.allow_sla_fallback),
        "sla_deadline_ms": job.sla.deadline_ms,
        "sla_max_cost_usd": job.sla.max_cost_usd,
        "sla_min_reliability": job.sla.min_reliability,
        "job_request_json": job.model_dump_json(),
        "status": status,
        "attempts": 0,
        "max_attempts": 2,
        "next_run_at": None,
        "chosen_resource_id": decision.chosen_resource_id,
        "chosen_resource_type": decision.chosen_resource_type,
        "worker_id": None,
        "created_at": now,
        "updated_at": now,
        "predicted_latency_ms": float(chosen_score["latency_pred_ms"]) if chosen_score else None,
        "predicted_cost_usd": float(chosen_score["cost_pred_usd"]) if chosen_score else None,
        "final_score": float(chosen_score["final_score"]) if chosen_score else None,
        "sla_ok": int(chosen_score["sla_ok"]) if chosen_score else 0,
        "sla_violations_json": json.dumps(chosen_score.get("sla_violations", []) if chosen_score else []),
        "actual_latency_ms": None,
        "actual_cost_usd": None,
        "output_ref": None,
    }
    upsert_job(row)
    add_job_event(
        job.job_id,
        "SUBMITTED",
        f"status={status} chosen={decision.chosen_resource_id} ({decision.chosen_resource_type})",
    )
    JOB_SUBMITTED_COUNTER.labels(status=status).inc()

    return {"ok": True, "status": status, "decision": decision}

@router.get("", summary="List jobs (latest first)")
def get_jobs(limit: int = 200):
    return list_jobs(limit=limit)


@router.post("/{job_id}/cancel", summary="Cancel a queued job")
def cancel_job(job_id: str):
    j = get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job_id not found")
    if j["status"] in ("COMPLETED", "FAILED"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel job in status={j['status']}")
    update_job(job_id, status="CANCELLED", worker_id=None)
    add_job_event(job_id, "CANCELLED", "Cancelled by user")
    return {"ok": True}

@router.post("/{job_id}/complete", summary="Manually mark job complete with actuals (optional)")
def complete_job(job_id: str, payload: CompletePayload):
    j = get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job_id not found")
    update_job(
        job_id,
        status="COMPLETED",
        actual_latency_ms=float(payload.actual_latency_ms),
        actual_cost_usd=float(payload.actual_cost_usd),
        output_ref=payload.output_ref,
    )
    add_job_event(job_id, "COMPLETED", "Manually completed (actuals provided)")
    return {"ok": True}

@router.get("/sla-events", summary="List SLA-related job events")
def sla_events(limit: int = 200):
    jobs = list_jobs(limit=2000)
    out = []
    for j in jobs:
        try:
            violations = json.loads(j.get("sla_violations_json") or "[]")
        except Exception:
            violations = []
        sla_ok = int(j.get("sla_ok") or 0)
        if j.get("status") == "BLOCKED" or (not sla_ok and len(violations) > 0):
            out.append({
                "job_id": j.get("job_id"),
                "status": j.get("status"),
                "chosen_resource_id": j.get("chosen_resource_id"),
                "chosen_resource_type": j.get("chosen_resource_type"),
                "predicted_latency_ms": j.get("predicted_latency_ms"),
                "predicted_cost_usd": j.get("predicted_cost_usd"),
                "violations": violations,
                "updated_at": j.get("updated_at"),
            })
    return out[:limit]

@router.get("/model-metrics", summary="Compute simple model performance metrics from completed jobs")
def model_metrics():
    jobs = list_jobs(limit=5000)
    completed = [
        j for j in jobs
        if j.get("status") == "COMPLETED"
        and j.get("actual_latency_ms") is not None
        and j.get("predicted_latency_ms") is not None
    ]
    if not completed:
        return {"note": "No completed jobs with actuals yet. Run the worker and submit jobs."}

    lat_err = [
        abs(float(j["actual_latency_ms"]) - float(j["predicted_latency_ms"]))
        for j in completed
    ]
    cost_completed = [
        j for j in completed
        if j.get("actual_cost_usd") is not None and j.get("predicted_cost_usd") is not None
    ]
    cost_err = [
        abs(float(j["actual_cost_usd"]) - float(j["predicted_cost_usd"]))
        for j in cost_completed
    ]

    def mean(xs): 
        return sum(xs) / len(xs) if xs else None

    return {
        "completed_jobs": len(completed),
        "latency_mae_ms": mean(lat_err),
        "cost_mae_usd": mean(cost_err),
    }
@router.get("/{job_id}", summary="Get a single job")
def get_job_by_id(job_id: str):
    j = get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job_id not found")
    # deserialize violations for convenience
    try:
        j["sla_violations"] = json.loads(j.get("sla_violations_json") or "[]")
    except Exception:
        j["sla_violations"] = []
    return j

@router.get("/{job_id}/events", summary="Job event log")
def job_events(job_id: str, limit: int = 200):
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="job_id not found")
    return list_job_events(job_id, limit=limit)
@router.get("/{job_id}/attempts", summary="Attempt-level execution history (for ML + debugging)")
def job_attempts(job_id: str, limit: int = 200):
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="job_id not found")
    return list_attempts_for_job(job_id, limit=limit)
