from __future__ import annotations
from typing import Dict
from ..core.config import load_yaml_config

CFG = load_yaml_config()

DEFAULT_BOUNDS = {
    "latency_ms": (5.0, 4000.0),
    "cost_usd": (0.0001, 0.2),
    "reliability": (0.80, 0.999),
    "energy_w": (5.0, 400.0),
    "congestion": (0.0, 1.0),
}

def _bounds(name: str):
    b = CFG.get("normalization_bounds", {}).get(name)
    if b and "min" in b and "max" in b:
        return float(b["min"]), float(b["max"])
    return DEFAULT_BOUNDS[name]

def minmax01(x: float, min_v: float, max_v: float, invert: bool = False) -> float:
    if max_v <= min_v:
        return 0.0
    v = (x - min_v) / (max_v - min_v)
    if v < 0.0: v = 0.0
    if v > 1.0: v = 1.0
    return 1.0 - v if invert else v

def normalize_scores(latency_ms: float, cost_usd: float, reliability: float, energy_w: float, congestion: float) -> Dict[str, float]:
    lmin, lmax = _bounds("latency_ms")
    cmin, cmax = _bounds("cost_usd")
    rmin, rmax = _bounds("reliability")
    emin, emax = _bounds("energy_w")
    gmin, gmax = _bounds("congestion")

    return {
        "latency": minmax01(latency_ms, lmin, lmax, invert=True),
        "cost": minmax01(cost_usd, cmin, cmax, invert=True),
        "reliability": minmax01(reliability, rmin, rmax, invert=False),
        "energy": minmax01(energy_w, emin, emax, invert=True),
        "congestion": minmax01(congestion, gmin, gmax, invert=True),
    }
