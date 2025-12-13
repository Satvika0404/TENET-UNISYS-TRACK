from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json

from .features import FeatureVector

MODEL_DIR = Path(__file__).resolve().parents[2] / "models_artifacts"
LAT_PATH = MODEL_DIR / "latency_model.json"
COST_PATH = MODEL_DIR / "cost_model.json"

def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _linpred(params: dict, x: dict) -> float:
    b0 = float(params.get("bias", 0.0))
    weights = params.get("weights", {})
    y = b0
    for k, w in weights.items():
        y += float(w) * float(x.get(k, 0.0))
    return y

def predict_latency_ms(f: FeatureVector) -> float:
    params = _load(LAT_PATH)
    x = asdict(f)
    if params:
        y = _linpred(params, x)
    else:
        y = 50.0 + 800.0 * f.congestion + 1.2 * f.net_rtt_ms + 0.9 * f.payload_size_mb + (400.0 if f.requires_gpu else 0.0)
    return max(5.0, float(y))

def predict_cost_usd(f: FeatureVector) -> float:
    params = _load(COST_PATH)
    x = asdict(f)
    if params:
        y = _linpred(params, x)
    else:
        est_seconds = 2.0 + 20.0 * f.congestion + 0.05 * f.payload_size_mb + (10.0 if f.requires_gpu else 0.0)
        y = (f.price_per_hour_usd / 3600.0) * est_seconds + 0.00001 * f.net_rtt_ms + 0.000002 * f.power_w
    return max(0.0, float(y))
