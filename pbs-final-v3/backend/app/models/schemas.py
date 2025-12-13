from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any, List
from datetime import datetime

ResourceType = Literal["edge", "cloud", "gpu"]

class SLA(BaseModel):
    deadline_ms: Optional[int] = Field(default=None, description="Hard deadline for completion (ms).")
    max_cost_usd: Optional[float] = Field(default=None, description="Hard cost cap for job (USD).")
    min_reliability: Optional[float] = Field(default=None, description="Minimum acceptable reliability (0..1).")

class JobRequest(BaseModel):
    job_id: str
    job_type: Literal["batch", "inference", "training"]
    urgency: float = Field(ge=0.0, le=1.0, description="0=not urgent, 1=critical")
    payload_size_mb: float = Field(ge=0.0, description="Approx data size (MB)")
    requires_gpu: bool = False
    allow_sla_fallback: bool = True
    sla: SLA = Field(default_factory=SLA)
    hints: Dict[str, Any] = Field(default_factory=dict)

class TelemetryPoint(BaseModel):
    ts: datetime = Field(default_factory=datetime.utcnow)
    resource_id: str
    resource_type: ResourceType

    cpu_util: float = Field(ge=0.0, le=1.0, default=0.0)
    mem_util: float = Field(ge=0.0, le=1.0, default=0.0)
    gpu_util: float = Field(ge=0.0, le=1.0, default=0.0)

    net_rtt_ms: float = Field(ge=0.0, default=50.0)
    net_bw_mbps: float = Field(ge=0.0, default=100.0)

    price_per_hour_usd: float = Field(ge=0.0, default=0.0)
    reliability: float = Field(ge=0.0, le=1.0, default=0.98)

    power_w: float = Field(ge=0.0, default=50.0)

    extra: Dict[str, Any] = Field(default_factory=dict)

class TelemetryBatch(BaseModel):
    points: List[TelemetryPoint]

class ResourceSnapshot(BaseModel):
    resource_id: str
    resource_type: ResourceType
    last: TelemetryPoint

class ScoreBreakdown(BaseModel):
    latency_pred_ms: float
    cost_pred_usd: float
    reliability: float
    energy_w: float
    congestion: float
    normalized: Dict[str, float]
    weighted_components: Dict[str, float]
    final_score: float
    sla_ok: bool
    effective_score: float
    sla_violations: List[str] = Field(default_factory=list)

class RouteDecision(BaseModel):
    job_id: str
    chosen_resource_id: str
    chosen_resource_type: ResourceType
    considered: List[Dict[str, Any]]
    explanation: str
