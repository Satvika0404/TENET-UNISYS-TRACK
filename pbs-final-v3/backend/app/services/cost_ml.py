from __future__ import annotations

from pathlib import Path
import json
import joblib
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_PATH = MODEL_DIR / "cost_model.joblib"
META_PATH  = MODEL_DIR / "cost_model_metrics.json"

_MODEL = None
_META = None


def load_model():
    global _MODEL
    if _MODEL is None and MODEL_PATH.exists():
        _MODEL = joblib.load(MODEL_PATH)
    return _MODEL


def load_meta() -> dict:
    global _META
    if _META is None:
        _META = json.loads(META_PATH.read_text("utf-8")) if META_PATH.exists() else {}
    return _META


def model_version() -> str:
    return load_meta().get("model_version", "none")


def _base_cost(features: dict, latency_ms: float) -> float:
    rt = str(features.get("resource_type", "edge"))
    price = float(features.get("price_per_hour_usd", 0.0) or 0.0)
    if price <= 0.0:
        price = 0.01 if rt == "edge" else (0.08 if rt == "cloud" else 1.20)

    payload = float(features.get("payload_size_mb", 0.0) or 0.0)
    runtime_h = (float(latency_ms) / 1000.0) / 3600.0
    egress = 0.00002 * payload if rt == "cloud" else 0.0
    return price * runtime_h + egress


def predict_cost(features: dict) -> dict:
    """
    Uses: total_cost = base_cost(latency_pred_ms) + residual_model(features)
    """
    model = load_model()
    meta = load_meta()

    # Need latency prediction injected by scoring.py
    lat = float(features.get("latency_pred_ms", 0.0) or 0.0)
    if lat <= 0.0:
        lat = 800.0

    base = _base_cost(features, lat)

    # fallback: base only
    if model is None:
        mean = base
        return {"mean_usd": mean, "p90_usd": mean * 1.2, "used": "base_only"}

    X = pd.DataFrame([features])
    resid = float(model.predict(X)[0])
    mean = base + resid

    q90 = float(meta.get("conformal_q90_usd", 0.0) or 0.0)
    p90 = mean + q90 if q90 > 0 else mean * 1.2

    return {"mean_usd": mean, "p90_usd": p90, "used": model_version()}
