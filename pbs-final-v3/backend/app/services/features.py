from __future__ import annotations
from dataclasses import dataclass
from ..models.schemas import TelemetryPoint, JobRequest

@dataclass
class FeatureVector:
    congestion: float
    cpu_util: float
    mem_util: float
    gpu_util: float
    net_rtt_ms: float
    net_bw_mbps: float
    price_per_hour_usd: float
    reliability: float
    power_w: float
    urgency: float
    payload_size_mb: float
    requires_gpu: bool

def compute_congestion(t: TelemetryPoint) -> float:
    base = (t.cpu_util + t.mem_util) / 2.0
    if t.resource_type == "gpu":
        base = (base + t.gpu_util) / 2.0
    return max(0.0, min(1.0, base))

def build_features(t: TelemetryPoint, job: JobRequest) -> FeatureVector:
    return FeatureVector(
        congestion=compute_congestion(t),
        cpu_util=t.cpu_util,
        mem_util=t.mem_util,
        gpu_util=t.gpu_util,
        net_rtt_ms=t.net_rtt_ms,
        net_bw_mbps=t.net_bw_mbps,
        price_per_hour_usd=t.price_per_hour_usd,
        reliability=t.reliability,
        power_w=t.power_w,
        urgency=job.urgency,
        payload_size_mb=job.payload_size_mb,
        requires_gpu=job.requires_gpu,
    )
