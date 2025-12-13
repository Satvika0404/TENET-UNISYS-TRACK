from fastapi import APIRouter, HTTPException
from ..models.schemas import TelemetryPoint, TelemetryBatch
from ..services.storage import insert_point, latest_point
from ..services.metrics_registry import TELEMETRY_INGEST_COUNTER, TELEMETRY_LAST_TIMESTAMP_SECONDS
from ..services.pricing import get_price_for_resource_type

router = APIRouter(prefix="/telemetry")

@router.post("", summary="Ingest a telemetry point")
def post_point(p: TelemetryPoint):
    # Auto-enrich pricing for cloud/gpu if missing or zero
    if p.resource_type in ("cloud", "gpu") and (p.price_per_hour_usd is None or float(p.price_per_hour_usd) <= 0.0):
        fetched = get_price_for_resource_type(p.resource_type)
        if fetched is not None:
            p.price_per_hour_usd = fetched
            p.extra["price_source"] = "azure_retail_prices"
        else:
            p.extra["price_source"] = "fallback_simulated_or_missing"

    insert_point(p)
    TELEMETRY_INGEST_COUNTER.labels(resource_type=p.resource_type).inc()
    TELEMETRY_LAST_TIMESTAMP_SECONDS.labels(resource_type=p.resource_type).set(p.ts.timestamp())
    return {"ok": True}

@router.post("/batch", summary="Ingest telemetry points (batch)")
def post_batch(b: TelemetryBatch):
    for p in b.points:
        # Auto-enrich pricing for cloud/gpu if missing or zero
        if p.resource_type in ("cloud", "gpu") and (p.price_per_hour_usd is None or float(p.price_per_hour_usd) <= 0.0):
            fetched = get_price_for_resource_type(p.resource_type)
            if fetched is not None:
                p.price_per_hour_usd = fetched
                p.extra["price_source"] = "azure_retail_prices"
            else:
                p.extra["price_source"] = "fallback_simulated_or_missing"

        insert_point(p)
        TELEMETRY_INGEST_COUNTER.labels(resource_type=p.resource_type).inc()
        TELEMETRY_LAST_TIMESTAMP_SECONDS.labels(resource_type=p.resource_type).set(p.ts.timestamp())
    return {"ok": True, "count": len(b.points)}

@router.get("/latest/{resource_id}", response_model=TelemetryPoint)
def get_latest(resource_id: str):
    p = latest_point(resource_id)
    if not p:
        raise HTTPException(status_code=404, detail="No telemetry for this resource_id")
    return p
