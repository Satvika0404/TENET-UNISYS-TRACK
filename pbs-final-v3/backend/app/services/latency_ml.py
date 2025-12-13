from __future__ import annotations
from pathlib import Path
import json
import joblib
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_PATH = MODEL_DIR / "latency_model.joblib"
META_PATH  = MODEL_DIR / "latency_model_metrics.json"

_MODEL = None
_META = None

def model_version() -> str:
    meta = load_meta()
    return meta.get("model_version", "none")

def load_model():
    global _MODEL
    if _MODEL is None and MODEL_PATH.exists():
        _MODEL = joblib.load(MODEL_PATH)
    return _MODEL

def load_meta() -> dict:
    global _META
    if _META is None:
        if META_PATH.exists():
            _META = json.loads(META_PATH.read_text(encoding="utf-8"))
        else:
            _META = {}
    return _META

def predict_latency(features: dict) -> dict:
    """
    Returns:
      mean_ms: point estimate
      p90_ms: conservative estimate for SLA gating (mean + conformal_q90)
    """
    model = load_model()
    meta = load_meta()

    # Fallback if model missing
    if model is None:
        # simple baseline: RTT + payload factor + congestion factor
        mean = float(features.get("net_rtt_ms", 0.0)) + 20.0 * float(features.get("payload_size_mb", 0.0)) / max(1.0, float(features.get("net_bw_mbps", 100.0))) \
               + 500.0 * float(features.get("congestion", 0.0))
        return {"mean_ms": mean, "p90_ms": mean * 1.25, "used": "fallback"}

    X = pd.DataFrame([features])
    mean = float(model.predict(X)[0])

    q90 = float(meta.get("conformal_q90_ms", 0.0))
    p90 = mean + q90 if q90 > 0 else mean * 1.2

    return {"mean_ms": mean, "p90_ms": p90, "used": model_version()}
