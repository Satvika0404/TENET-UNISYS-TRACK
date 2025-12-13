from fastapi import APIRouter
from ..models.schemas import JobRequest, RouteDecision
from ..services.routing import route
from ..services.metrics_registry import ROUTE_DECISION_COUNTER

router = APIRouter(prefix="/route")

@router.post("", response_model=RouteDecision)
def route_job(job: JobRequest):
    decision = route(job)
    ROUTE_DECISION_COUNTER.labels(chosen_type=decision.chosen_resource_type).inc()
    return decision
