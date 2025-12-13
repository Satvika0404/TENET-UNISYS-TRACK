from prometheus_client import Counter, Gauge

# Telemetry ingest
TELEMETRY_INGEST_COUNTER = Counter(
    "pbs_telemetry_ingest_total",
    "Total telemetry points ingested",
    ["resource_type"],
)

TELEMETRY_LAST_TIMESTAMP_SECONDS = Gauge(
    "pbs_telemetry_last_timestamp_seconds",
    "Unix timestamp of latest telemetry by resource_type",
    ["resource_type"],
)

# Routing
ROUTE_DECISION_COUNTER = Counter(
    "pbs_route_decisions_total",
    "Total route decisions made",
    ["chosen_type"],
)

# Jobs / Dispatch (NOTE: worker updates DB directly; /metrics derives live status gauges)
JOB_SUBMITTED_COUNTER = Counter(
    "pbs_jobs_submitted_total",
    "Jobs submitted into the system",
    ["status"],  # QUEUED / BLOCKED
)

JOBS_BY_STATUS_GAUGE = Gauge(
    "pbs_jobs_by_status",
    "Current job counts by status",
    ["status"],
)

JOB_QUEUE_GAUGE = Gauge(
    "pbs_job_queue_depth",
    "Current number of queued jobs",
)

# Feedback
FEEDBACK_COUNTER = Counter(
    "pbs_feedback_total",
    "Feedback events received",
)
