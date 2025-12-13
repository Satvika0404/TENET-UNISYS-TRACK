from __future__ import annotations
from typing import Dict, Any

from pydantic import ValidationError
from .dispatch_adapters import DispatchResult, get_adapter_for


def dispatch(job_row: Dict[str, Any]) -> DispatchResult:
    from app.models.schemas import JobRequest

    # Force-fail for testing reroute/retry (only on first attempt)
    attempts = int(job_row.get("attempts") or 0)
    jr = job_row.get("job_request_json")

    req = None
    if jr:
        try:
            req = JobRequest.model_validate_json(jr)
        except ValidationError:
            req = None  # only swallow parsing errors

    # IMPORTANT: do NOT swallow forced failure
    if req:
        force_fail_first = bool((req.hints or {}).get("force_fail_first"))
        # claim_next_job() usually increments attempts to 1 on first run
        if force_fail_first and attempts == 1:
            raise RuntimeError("FORCED_FAIL_FIRST: testing reroute + retry")

    rtype = job_row.get("chosen_resource_type") or "edge"
    adapter = get_adapter_for(rtype)
    return adapter.run(job_row)
