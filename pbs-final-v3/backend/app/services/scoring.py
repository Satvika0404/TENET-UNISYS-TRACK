from __future__ import annotations

from typing import Dict, List
import json

from ..core.config import load_yaml_config
from ..models.schemas import TelemetryPoint, JobRequest, ScoreBreakdown
from .features import build_features
from .cost_ml import predict_cost

from .normalization import normalize_scores
from .latency_ml import predict_latency  # ML latency (mean + p90)

CFG = load_yaml_config()

DEFAULT_WEIGHTS = {"latency": 0.45, "cost": 0.25, "reliability": 0.20, "energy": 0.10}


def _weights() -> Dict[str, float]:
    w = (CFG.get("scoring", {}) or {}).get("weights", {}) or {}
    out = DEFAULT_WEIGHTS.copy()
    out.update({k: float(v) for k, v in w.items() if k in out})
    s = sum(out.values())
    if s <= 0:
        return DEFAULT_WEIGHTS.copy()
    return {k: v / s for k, v in out.items()}


def _features_to_dict(f) -> dict:
    """Make feature object usable by pandas model inference."""
    # pydantic v2
    if hasattr(f, "model_dump"):
        return f.model_dump()
    # pydantic v1
    if hasattr(f, "dict"):
        return f.dict()
    # dataclass / plain object
    try:
        return dict(vars(f))
    except Exception:
        return json.loads(json.dumps(f))


def sla_check(job: JobRequest, latency_ms: float, cost_usd: float, reliability: float) -> List[str]:
    v = []
    if job.sla.deadline_ms is not None and latency_ms > job.sla.deadline_ms:
        v.append(f"deadline_ms violated: predicted {latency_ms:.0f} > {job.sla.deadline_ms}")
    if job.sla.max_cost_usd is not None and cost_usd > job.sla.max_cost_usd:
        v.append(f"max_cost_usd violated: predicted {cost_usd:.4f} > {job.sla.max_cost_usd}")
    if job.sla.min_reliability is not None and reliability < job.sla.min_reliability:
        v.append(f"min_reliability violated: {reliability:.3f} < {job.sla.min_reliability}")
    return v


def score_resource(t: TelemetryPoint, job: JobRequest) -> ScoreBreakdown:
    w = _weights()

    # Build your existing features object (keeps cost predictor compatible)
    f = build_features(t, job)
    features_dict = _features_to_dict(f)

    # ✅ REQUIRED: ensure ML pipeline categorical columns exist
    features_dict.setdefault("job_type", job.job_type)
    features_dict.setdefault("resource_type", t.resource_type)

    # ML latency prediction (mean + p90)
    lat_pred = predict_latency(features_dict)
    latency_mean_ms = float(lat_pred["mean_ms"])
    latency_p90_ms = float(lat_pred["p90_ms"])  # use ONLY for SLA checks (safer)
    features_dict["latency_pred_ms"] = latency_mean_ms
    lat_pred = predict_latency(features_dict)
    latency_mean_ms = float(lat_pred["mean_ms"])
    latency_p90_ms  = float(lat_pred["p90_ms"])

    features_dict["latency_pred_ms"] = latency_mean_ms   # <-- RIGHT HERE

    cost_pred = predict_cost(features_dict)

    # Cost stays as your current predictor for now
    cost_pred = predict_cost(features_dict)
    cost_mean_usd = float(cost_pred["mean_usd"])
    cost_p90_usd = float(cost_pred["p90_usd"])


    congestion = float(getattr(f, "congestion", features_dict.get("congestion", 0.0)))
    reliability = float(t.reliability or 0.98)
    energy_w = float(t.power_w or 50.0)

    # ranking uses MEAN
    norm = normalize_scores(latency_mean_ms, cost_mean_usd, reliability, energy_w, congestion)


    weighted_components = {
        "latency": w["latency"] * norm["latency"],
        "cost": w["cost"] * norm["cost"],
        "reliability": w["reliability"] * norm["reliability"],
        "energy": w["energy"] * norm["energy"],
    }
    final = sum(weighted_components.values())

    # SLA uses p90
    violations = sla_check(job, latency_p90_ms, cost_p90_usd, reliability)

    sla_ok = len(violations) == 0

    penalty = 0.35 * len(violations)
    effective = final - penalty

    return ScoreBreakdown(
        latency_pred_ms=latency_mean_ms,
        cost_pred_usd=cost_mean_usd,

        reliability=reliability,
        energy_w=energy_w,
        congestion=congestion,
        normalized=norm,
        weighted_components=weighted_components,
        final_score=final,
        sla_ok=sla_ok,
        effective_score=effective,
        sla_violations=violations,
    )

