from __future__ import annotations
from typing import List, Dict, Any, Tuple, Set

from ..models.schemas import JobRequest, RouteDecision, TelemetryPoint
from .storage import list_resources_latest
from .scoring import score_resource


def _eligible(t: TelemetryPoint, job: JobRequest) -> bool:
    if job.requires_gpu and t.resource_type != "gpu":
        return False
    if (t.reliability or 0.0) < 0.85:
        return False
    return True


def route(job: JobRequest) -> RouteDecision:
    snapshots = list_resources_latest(limit=500)

    # Build candidates first (FIX)
    candidates: List[TelemetryPoint] = [s.last for s in snapshots if s and s.last]

    # Hints-based routing controls (testing + reroute)
    hints = job.hints or {}
    force_type = hints.get("force_resource_type")
    force_id = hints.get("force_resource_id")
    exclude_ids: Set[str] = set(hints.get("exclude_resource_ids") or [])

    if exclude_ids:
        candidates = [t for t in candidates if t.resource_id not in exclude_ids]

    if force_id:
        candidates = [t for t in candidates if t.resource_id == force_id]

    if force_type:
        candidates = [t for t in candidates if t.resource_type == force_type]

    considered: List[Dict[str, Any]] = []
    ok: List[Tuple[TelemetryPoint, Any]] = []
    bad: List[Tuple[TelemetryPoint, Any]] = []

    for t in candidates:
        if not _eligible(t, job):
            continue

        b = score_resource(t, job)
        considered.append({
            "resource_id": t.resource_id,
            "resource_type": t.resource_type,
            "score": b.model_dump(),
        })
        (ok if b.sla_ok else bad).append((t, b))

    considered_sorted = sorted(
        considered,
        key=lambda x: x["score"].get("effective_score", x["score"]["final_score"]),
        reverse=True
    )

    if ok:
        t, b = max(ok, key=lambda tb: tb[1].final_score)
        return RouteDecision(
            job_id=job.job_id,
            chosen_resource_id=t.resource_id,
            chosen_resource_type=t.resource_type,
            considered=considered_sorted,
            explanation=(
                f"[SLA OK] Chose {t.resource_id} ({t.resource_type}) score={b.final_score:.3f}. "
                f"Latency={b.latency_pred_ms:.0f}ms, Cost=${b.cost_pred_usd:.4f}, "
                f"Reliability={b.reliability:.3f}, Congestion={b.congestion:.2f}."
            ),
        )

    if not job.allow_sla_fallback:
        return RouteDecision(
            job_id=job.job_id,
            chosen_resource_id="none",
            chosen_resource_type="edge",
            considered=considered_sorted,
            explanation=(
                "No SLA-compliant resources found. Dispatch blocked because allow_sla_fallback=false. "
                "Relax SLA or enable fallback."
            ),
        )

    if bad:
        t, b = max(bad, key=lambda tb: tb[1].effective_score)
        return RouteDecision(
            job_id=job.job_id,
            chosen_resource_id=t.resource_id,
            chosen_resource_type=t.resource_type,
            considered=considered_sorted,
            explanation=(
                f"[SLA FALLBACK] No SLA-compliant resources. Chose best-available {t.resource_id} ({t.resource_type}) "
                f"effective_score={b.effective_score:.3f} (raw={b.final_score:.3f}). "
                f"SLA warnings: " + "; ".join(b.sla_violations)
            ),
        )

    return RouteDecision(
        job_id=job.job_id,
        chosen_resource_id="none",
        chosen_resource_type="edge",
        considered=considered_sorted,
        explanation="No eligible resources found (check telemetry + requires_gpu + reliability gates).",
    )
