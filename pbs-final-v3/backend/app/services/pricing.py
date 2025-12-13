from __future__ import annotations
from datetime import datetime, timedelta
import httpx

from .storage import get_cached_price, set_cached_price

AZURE_URL = "https://prices.azure.com/api/retail/prices"

DEFAULT_REGION = "eastus"
DEFAULT_CURRENCY = "USD"
DEFAULT_CLOUD_SKU = "Standard_D4as_v5"
DEFAULT_GPU_SKU = "Standard_NC4as_T4_v3"

CACHE_TTL_HOURS = 6

def _cache_key(region: str, sku: str, currency: str) -> str:
    return f"azure:{region}:{sku}:{currency}"

def _is_fresh(updated_at_iso: str) -> bool:
    try:
        ts = datetime.fromisoformat(updated_at_iso)
        return datetime.utcnow() - ts < timedelta(hours=CACHE_TTL_HOURS)
    except Exception:
        return False

def fetch_azure_vm_price_per_hour_usd(region: str, sku: str, currency: str = "USD") -> float | None:
    key = _cache_key(region, sku, currency)
    cached = get_cached_price(key)
    if cached and _is_fresh(cached["updated_at"]):
        return cached["price_per_hour_usd"]

    flt = (
        f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' "
        f"and armSkuName eq '{sku}'"
    )
    params = {"$filter": flt}
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(AZURE_URL, params=params)
            r.raise_for_status()
            data = r.json()

        items = data.get("Items") or data.get("items") or []
        if not items:
            return None

        chosen = None
        for it in items:
            if "unitPrice" in it:
                chosen = it
                break
        if not chosen:
            return None

        price = float(chosen["unitPrice"])
        set_cached_price(key, price, datetime.utcnow().isoformat())
        return price
    except Exception:
        return None

def get_price_for_resource_type(resource_type: str) -> float | None:
    if resource_type == "cloud":
        return fetch_azure_vm_price_per_hour_usd(DEFAULT_REGION, DEFAULT_CLOUD_SKU, DEFAULT_CURRENCY)
    if resource_type == "gpu":
        return fetch_azure_vm_price_per_hour_usd(DEFAULT_REGION, DEFAULT_GPU_SKU, DEFAULT_CURRENCY)
    return None
