from fastapi import APIRouter
from pydantic import BaseModel, Field
from datetime import datetime

from ..services.metrics_registry import FEEDBACK_COUNTER

router = APIRouter(prefix="/feedback")

class Feedback(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    job_id: str
    resource_id: str
    actual_latency_ms: float
    actual_cost_usd: float

@router.post("", summary="Store feedback (placeholder)")
def post_feedback(f: Feedback):
    FEEDBACK_COUNTER.inc()
    return {"ok": True, "note": "Feedback received. Offline retraining can be added next."}
