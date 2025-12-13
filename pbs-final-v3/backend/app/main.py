from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from .routers import telemetry, route, metrics, feedback, resources, jobs, pricing
from .core.config import settings

app = FastAPI(
    title="PBS Final v3 – Hybrid Workload Router",
    version="0.3.0",
    description="Telemetry ingestion, explainable scoring, SLA-aware routing, Prometheus metrics."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry.router, tags=["telemetry"])
app.include_router(resources.router, tags=["resources"])
app.include_router(route.router, tags=["routing"])
app.include_router(jobs.router, tags=["jobs"])
app.include_router(pricing.router, tags=["pricing"])
app.include_router(feedback.router, tags=["feedback"])
app.include_router(metrics.router, tags=["metrics"])

@app.get("/")
def root():
    return RedirectResponse(url="/docs")

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

@app.get("/health")
def health():
    return {"status": "ok", "service": "pbs-final-v3"}