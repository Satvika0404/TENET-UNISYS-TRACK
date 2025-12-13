# PBS Final v3 – Backend + Frontend (SLA-aware Routing + Dispatch Worker)

This version completes **Layer 6: Routing & Dispatch Engine** by adding a real **job queue + worker**.

What you get now:
- Telemetry ingestion + normalization
- Explainable SLA-aware routing (/route)
- Job submission that **queues** a dispatchable job (/jobs)
- A **worker process** that executes queued jobs (simulated by default, pluggable HTTP runners)
- Job lifecycle + event logs (for the Streamlit dashboard)

---

## 1) Setup (Windows)

From repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 2) Run Backend

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:
- API docs: `http://127.0.0.1:8000/docs`
- Metrics: `http://127.0.0.1:8000/metrics`

---

## 3) Seed Telemetry (required)

In a new terminal:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\simulate_telemetry.py --seconds 60
```

If `requests` is missing, you did not install requirements correctly.

---

## 4) Start the Dispatch Worker (Layer 6)

In another terminal:

```powershell
cd backend
..\.venv\Scripts\python.exe worker.py
```

This worker:
- claims `QUEUED` jobs from SQLite
- dispatches them using an adapter
- writes `COMPLETED/FAILED` and actuals back into the DB

---

## 5) Run Frontend (Streamlit)

From repo root:

```powershell
cd frontend
..\.venv\Scripts\python.exe -m streamlit run app.py
```

Dashboard:
- Resources
- Route tester (no queue)
- Submit & Dispatch (queues jobs)
- Jobs (status + event logs)
- SLA Events
- Model Metrics

---

## Optional: Real dispatch adapters (HTTP runners)

By default, the worker uses a **simulated adapter**.

If you have real runners, set these environment variables:

- `EDGE_AGENT_URL`
- `CLOUD_RUNNER_URL`
- `GPU_RUNNER_URL`

Worker will call:
- `POST {URL}/run` with the job payload

Expected JSON response:
```json
{
  "actual_latency_ms": 1234,
  "actual_cost_usd": 0.04,
  "output_ref": "runner://job-output/abc"
}
```
