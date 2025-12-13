from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from ..services.metrics_registry import JOB_QUEUE_GAUGE, JOBS_BY_STATUS_GAUGE
from ..services.storage import count_jobs

router = APIRouter(prefix="")

@router.get("/metrics")
def metrics():
    statuses = ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"]
    for st in statuses:
        JOBS_BY_STATUS_GAUGE.labels(status=st).set(count_jobs(st))
    JOB_QUEUE_GAUGE.set(count_jobs("QUEUED"))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
