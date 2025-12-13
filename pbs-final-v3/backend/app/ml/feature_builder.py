from __future__ import annotations
from typing import Dict
from ..models.schemas import JobRequest, TelemetryPoint

def build_latency_features(job: JobRequest, tel: TelemetryPoint) -> Dict:
    # Derived congestion score (simple but effective)
    cpu = float(tel.cpu_util or 0.0)
    gpu = float(tel.gpu_util or 0.0)
    mem = float(tel.mem_util or 0.0)
    congestion = 0.5 * cpu + 0.3 * gpu + 0.2 * mem

    # NOTE: keep keys stable forever; model depends on them
    return {
        # categorical
        "job_type": job.job_type,
        "resource_type": tel.resource_type,

        # job numeric
        "urgency": float(job.urgency),
        "payload_size_mb": float(job.payload_size_mb),
        "requires_gpu": int(job.requires_gpu),

        # telemetry numeric
        "cpu_util": cpu,
        "gpu_util": gpu,
        "mem_util": mem,
        "net_rtt_ms": float(tel.net_rtt_ms or 0.0),
        "net_bw_mbps": float(tel.net_bw_mbps or 0.0),
        "price_per_hour_usd": float(tel.price_per_hour_usd or 0.0),
        "reliability": float(tel.reliability or 0.98),
        "power_w": float(tel.power_w or 50.0),

        # derived
        "congestion": float(congestion),
    }
