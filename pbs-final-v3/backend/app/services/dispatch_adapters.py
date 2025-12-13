from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
import os
import time
import random
import httpx

@dataclass
class DispatchResult:
    actual_latency_ms: float
    actual_cost_usd: float
    output_ref: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

class BaseAdapter:
    name: str = "base"

    def run(self, job: Dict[str, Any]) -> DispatchResult:
        raise NotImplementedError

class SimulatedAdapter(BaseAdapter):
    def __init__(self, kind: str):
        self.name = f"simulated-{kind}"
        self.kind = kind

    def run(self, job: Dict[str, Any]) -> DispatchResult:
        # Use predicted as anchor, add noise.
        pred_lat = float(job.get("predicted_latency_ms") or 1000.0)
        pred_cost = float(job.get("predicted_cost_usd") or 0.01)

        # Simulate service time (cap so demo is fast)
        sleep_s = max(0.2, min(3.0, pred_lat / 1000.0 * random.uniform(0.25, 0.8)))
        time.sleep(sleep_s)

        # Actuals with noise
        actual_lat = pred_lat * random.uniform(0.85, 1.35)
        actual_cost = pred_cost * random.uniform(0.85, 1.35)

        # Edge is typically cheaper
        if self.kind == "edge":
            actual_cost *= 0.2
        return DispatchResult(
            actual_latency_ms=round(actual_lat, 3),
            actual_cost_usd=round(actual_cost, 6),
            output_ref=f"sim://{job.get('job_id')}",
            meta={"adapter": self.name, "sleep_s": sleep_s},
        )

class HttpAdapter(BaseAdapter):
    def __init__(self, base_url: str, name: str):
        self.base_url = base_url.rstrip("/")
        self.name = name

    def run(self, job: Dict[str, Any]) -> DispatchResult:
        # Contract: POST {base_url}/run with job payload, returns JSON with actual_latency_ms, actual_cost_usd, output_ref
        payload = {
            "job_id": job.get("job_id"),
            "job_type": job.get("job_type"),
            "payload_size_mb": job.get("payload_size_mb"),
            "requires_gpu": bool(job.get("requires_gpu")),
            "chosen_resource_id": job.get("chosen_resource_id"),
            "chosen_resource_type": job.get("chosen_resource_type"),
            "job_request": None,
        }
        # If stored, pass full job_request JSON to real runners
        try:
            if job.get("job_request_json"):
                payload["job_request"] = __import__("json").loads(job["job_request_json"])
        except Exception:
            pass
        timeout = float(os.getenv("DISPATCH_TIMEOUT_S", "20"))
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{self.base_url}/run", json=payload)
            r.raise_for_status()
            data = r.json()

        return DispatchResult(
            actual_latency_ms=float(data.get("actual_latency_ms", 0.0)),
            actual_cost_usd=float(data.get("actual_cost_usd", 0.0)),
            output_ref=data.get("output_ref"),
            meta={"adapter": self.name, "runner_url": self.base_url},
        )

def get_adapter_for(resource_type: str) -> BaseAdapter:
    # Optional real runners (pluggable)
    edge_url = os.getenv("EDGE_AGENT_URL")
    cloud_url = os.getenv("CLOUD_RUNNER_URL")
    gpu_url = os.getenv("GPU_RUNNER_URL")

    if resource_type == "edge":
        return HttpAdapter(edge_url, "edge-http") if edge_url else SimulatedAdapter("edge")
    if resource_type == "cloud":
        return HttpAdapter(cloud_url, "cloud-http") if cloud_url else SimulatedAdapter("cloud")
    if resource_type == "gpu":
        return HttpAdapter(gpu_url, "gpu-http") if gpu_url else SimulatedAdapter("gpu")
    return SimulatedAdapter("unknown")
