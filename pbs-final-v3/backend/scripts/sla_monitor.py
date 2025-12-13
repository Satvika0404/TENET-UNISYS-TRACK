"""
PBS SLA Monitor (Layer 7)

Run in a separate terminal.
- Scans QUEUED/RUNNING jobs
- Computes deadline_at = created_at + sla_deadline_ms
- Flags DEADLINE_RISK
- Optional: reroute queued jobs if deadline risk
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

from app.services.storage import list_jobs, add_job_event, update_job, get_job
from app.models.schemas import JobRequest
from app.services.routing import route

POLL_S = float(os.getenv("SLA_MONITOR_POLL_S", "1.0"))
QUEUE_MARGIN_MS = int(os.getenv("SLA_QUEUE_MARGIN_MS", "400"))  # safety buffer
REROUTE_ON_RISK = os.getenv("SLA_REROUTE_ON_RISK", "1") == "1"


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", ""))


def _deadline_at(job_row: dict) -> datetime | None:
    dl = job_row.get("sla_deadline_ms")
    if dl is None:
        return None
    created = job_row.get("created_at")
    if not created:
        return None
    return _parse_iso(created) + timedelta(milliseconds=int(dl))


def _reroute(job_row: dict) -> bool:
    try:
        jr = job_row.get("job_request_json")
        if not jr:
            return False
        job_req = JobRequest.model_validate_json(jr)

        # Exclude current resource so reroute actually changes
        hints = dict(job_req.hints or {})
        ex = list(hints.get("exclude_resource_ids") or [])
        cur = job_row.get("chosen_resource_id")
        if cur and cur != "none":
            ex.append(cur)
        hints["exclude_resource_ids"] = list(dict.fromkeys(ex))
        job_req.hints = hints

        decision = route(job_req)
        if decision.chosen_resource_id == "none":
            add_job_event(job_row["job_id"], "DEADLINE_REROUTE_FAILED", "No alternative resource found")
            return False

        update_job(
            job_row["job_id"],
            chosen_resource_id=decision.chosen_resource_id,
            chosen_resource_type=decision.chosen_resource_type,
        )
        add_job_event(job_row["job_id"], "DEADLINE_REROUTED", f"{cur} -> {decision.chosen_resource_id}")
        return True
    except Exception as e:
        add_job_event(job_row["job_id"], "DEADLINE_REROUTE_ERROR", str(e))
        return False


def main():
    print(f"[sla_monitor] started poll={POLL_S}s margin={QUEUE_MARGIN_MS}ms reroute={REROUTE_ON_RISK}")
    while True:
        try:
            jobs = list_jobs(limit=2000)
            now = datetime.utcnow()

            for j in jobs:
                status = j.get("status")
                if status not in ("QUEUED", "RUNNING"):
                    continue

                dl_at = _deadline_at(j)
                if not dl_at:
                    continue

                remaining_ms = (dl_at - now).total_seconds() * 1000.0

                # If queued and deadline risk
                if status == "QUEUED" and remaining_ms <= QUEUE_MARGIN_MS:
                    add_job_event(j["job_id"], "DEADLINE_RISK", f"remaining_ms={remaining_ms:.0f}")
                    if REROUTE_ON_RISK:
                        _reroute(j)

                # If already missed deadline
                if remaining_ms < 0:
                    add_job_event(j["job_id"], "SLA_BREACH_DEADLINE", f"missed_by_ms={-remaining_ms:.0f}")

            time.sleep(POLL_S)

        except KeyboardInterrupt:
            print("[sla_monitor] stopped by user")
            return
        except Exception as e:
            print("[sla_monitor] error:", e)
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
