from __future__ import annotations

import json, math
from pathlib import Path
import sqlite3
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, median_absolute_error
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.compose import TransformedTargetRegressor

from app.core.config import settings

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "cost_model.joblib"
META_PATH  = MODEL_DIR / "cost_model_metrics.json"


def base_cost(features: dict, latency_ms: float) -> float:
    rt = str(features.get("resource_type", "edge"))
    price = float(features.get("price_per_hour_usd", 0.0) or 0.0)
    if price <= 0.0:
        price = 0.01 if rt == "edge" else (0.08 if rt == "cloud" else 1.20)

    payload = float(features.get("payload_size_mb", 0.0) or 0.0)
    runtime_h = (float(latency_ms) / 1000.0) / 3600.0

    egress = 0.00002 * payload if rt == "cloud" else 0.0
    return price * runtime_h + egress


def mape(y_true, y_pred) -> float:
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)
    denom = np.maximum(1e-12, np.abs(y_true))
    return float(np.mean(np.abs(y_true - y_pred) / denom))


def main():
    con = sqlite3.connect(settings.db_path)
    rows = con.execute(
        """
        SELECT features_json, actual_cost_usd, predicted_latency_ms
        FROM jobs
        WHERE status='COMPLETED'
          AND features_json IS NOT NULL
          AND actual_cost_usd IS NOT NULL
          AND predicted_latency_ms IS NOT NULL
        ORDER BY updated_at DESC
        """
    ).fetchall()
    con.close()

    if len(rows) < 60:
        print(f"[train_cost] Not enough rows. Have {len(rows)}; target >= 60 for stable model.")
        return

    feats, y_total, base_list = [], [], []
    for fjson, cost, lat in rows:
        try:
            d = json.loads(fjson)
            d["job_type"] = d.get("job_type", "unknown")
            d["resource_type"] = d.get("resource_type", "unknown")
            bc = base_cost(d, float(lat))
            feats.append(d)
            y_total.append(float(cost))
            base_list.append(bc)
        except Exception:
            continue

    df = pd.DataFrame(feats).fillna(0.0)
    y_total = np.array(y_total, dtype=float)
    base_list = np.array(base_list, dtype=float)

    # Residual target (what ML learns)
    y_resid = y_total - base_list

    X_train, X_val, y_train, y_val, base_tr, base_va, ytot_tr, ytot_va = train_test_split(
        df, y_resid, base_list, y_total, test_size=0.25, random_state=42
    )

    cat_cols = [c for c in ["job_type", "resource_type"] if c in df.columns]
    num_cols = [c for c in df.columns if c not in cat_cols]

    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
            ("num", "passthrough", num_cols),
        ]
    )

    # Stronger than RF for small noisy data
    reg = ExtraTreesRegressor(
        n_estimators=600,
        random_state=42,
        n_jobs=-1,
        min_samples_leaf=2,
    )

    # Residual can be +/-; no log transform
    model = Pipeline([("pre", pre), ("reg", reg)])
    model.fit(X_train, y_train)

    resid_pred = model.predict(X_val)
    total_pred = base_va + resid_pred

    mae = float(mean_absolute_error(ytot_va, total_pred))
    rmse = float(math.sqrt(mean_squared_error(ytot_va, total_pred)))
    r2 = float(r2_score(ytot_va, total_pred))
    medae = float(median_absolute_error(ytot_va, total_pred))
    rel_mape = mape(ytot_va, total_pred)

    # Baseline: base cost only
    base_mae = float(mean_absolute_error(ytot_va, base_va))
    base_r2 = float(r2_score(ytot_va, base_va))
    base_mape = mape(ytot_va, base_va)

    # Conformal q90 on TOTAL residuals
    abs_err = np.abs(ytot_va - total_pred)
    q90 = float(np.quantile(abs_err, 0.90))

    joblib.dump(model, MODEL_PATH)

    meta = {
        "model_version": "et_cost_resid_v1",
        "trained_at_utc": datetime.utcnow().isoformat(),
        "rows_total": int(len(df)),
        "rows_train": int(len(X_train)),
        "rows_val": int(len(X_val)),
        "features": list(df.columns),
        "metrics": {
            "mae_usd": mae,
            "rmse_usd": rmse,
            "r2": r2,
            "median_ae_usd": medae,
            "mape": rel_mape,
            "baseline_base_cost_mae_usd": base_mae,
            "baseline_base_cost_r2": base_r2,
            "baseline_base_cost_mape": base_mape,
        },
        "conformal_q90_usd": q90,
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("[train_cost] saved:", MODEL_PATH)
    print("[train_cost] metrics:", meta["metrics"])
    print("[train_cost] conformal_q90_usd:", q90)


if __name__ == "__main__":
    main()
