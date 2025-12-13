from fastapi import APIRouter
from ..services.pricing import get_price_for_resource_type

router = APIRouter(prefix="/pricing")

@router.get("/current", summary="Current cached prices from cloud pricing API (best-effort)")
def current():
    return {
        "cloud_price_per_hour_usd": get_price_for_resource_type("cloud"),
        "gpu_price_per_hour_usd": get_price_for_resource_type("gpu"),
    }
