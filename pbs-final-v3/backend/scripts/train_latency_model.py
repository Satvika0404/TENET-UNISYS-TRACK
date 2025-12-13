from __future__ import annotations
import sys, json, random
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# allow imports from backend/app
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from app.core.config import settings
import sqlite3

MODEL_DIR = BACKEND_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))

def mape(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.maximum(1e-6, np.abs(y_true))
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100.0)

def load_real_rows(min_rows: int = 50):
    con = sqlite3.connect(settings.db_path, check_same_thread=False)
    cur = con.execute("""
        SELECT features_json, actual_latency_ms
        FROM jobs
        WHERE status='COMPLETED'
          AND actual_latency_ms IS NOT NULL
          AND features_json IS NOT NULL
    """)
    rows = cur.fetchall()
    con.close()

    feats, ys = [], []
    for fjson, y in rows:
        try:
            feats.append(json.loads(fjson))
            ys.append(float(y))
        except Exception:
            continue

    return feats, ys

def generate_synthetic(n: int = 4000):
    # synthetic generator that looks realistic enough for demo + tuning
    feats, ys = [], []
    job_types = ["inference", "batch", "training"]
    resource_types = ["edge", "cloud", "gpu"]

    for _ in range(n):
        job_type = random.choice(job_types)
        rtype = random.choice(resource_types)

        payload = random.uniform(1, 500)  # MB
        urgency = random.random()
        requires_gpu = 1 if (job_type == "training" or random.random() < 0.2) else 0

        cpu = random.random()
        gpu = random.random() if rtype == "gpu" else random.random() * 0.4
        mem = random.random()
        rtt = random.uniform(5, 200) if rtype != "edge" else random.uniform(2, 60)
        bw  = random.uniform(50, 1000) if rtype != "edge" else random.uniform(10, 300)
        price = random.uniform(0.02, 1.8) if rtype != "edge" else random.uniform(0.0, 0.05)
        rel = random.uniform(0.93, 0.999)
        power = random.uniform(20, 250)

        congestion = 0.5 * cpu + 0.3 * gpu + 0.2 * mem

        f = {
            "job_type": job_type,
            "resource_type": rtype,
            "urgency": urgency,
            "payload_size_mb": payload,
            "requires_gpu": requires_gpu,
            "cpu_util": cpu,
            "gpu_util": gpu,
            "mem_util": mem,
            "net_rtt_ms": rtt,
            "net_bw_mbps": bw,
            "price_per_hour_usd": price,
            "reliability": rel,
            "power_w": power,
            "congestion": congestion,
        }

        # latency formula + noise (ms)
        base = rtt
        transfer = 20.0 * payload / max(1.0, bw)
        compute = 200.0 + 1200.0 * congestion
        if job_type == "training":
            compute *= 1.8
        if rtype == "edge":
            compute *= 0.85
        if rtype == "gpu":
            compute *= 0.7
        if requires_gpu and rtype != "gpu":
            compute *= 1.5

        y = base + transfer + compute
        y += np.random.normal(0, 60)  # noise
        y = max(1.0, y)

        feats.append(f)
        ys.append(float(y))

    return feats, ys

def main():
    real_X, real_y = load_real_rows(min_rows=50)

    # mix real + synthetic (best for “impressive” demo)
    syn_X, syn_y = generate_synthetic(n=5000)
    X = real_X + syn_X
    y = real_y + syn_y

    df = pd.DataFrame(X)
    target = np.array(y, dtype=float)

    cat_cols = ["job_type", "resource_type"]
    num_cols = [c for c in df.columns if c not in cat_cols]

    pre = ColumnTransformer(
        transformers=[
            ("num", Pipeline(steps=[
                ("imputer", SimpleImputer(strategy="median")),
            ]), num_cols),
            ("cat", Pipeline(steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("ohe", OneHotEncoder(handle_unknown="ignore")),
            ]), cat_cols),
        ]
    )

    model = RandomForestRegressor(
        n_estimators=400,
        random_state=42,
        n_jobs=-1
    )

    pipe = Pipeline(steps=[("pre", pre), ("rf", model)])

    # split: train / calib / test (calib used for conformal q90)
    X_train, X_tmp, y_train, y_tmp = train_test_split(df, target, test_size=0.30, random_state=42)
    X_cal, X_test, y_cal, y_test = train_test_split(X_tmp, y_tmp, test_size=0.50, random_state=42)

    # hyperparameter search (small but meaningful)
    params = {
        "rf__max_depth": [8, 12, 18, None],
        "rf__min_samples_split": [2, 5, 10],
        "rf__min_samples_leaf": [1, 2, 4],
        "rf__max_features": ["sqrt", 0.6, 0.9],
    }
    search = RandomizedSearchCV(
        pipe,
        params,
        n_iter=18,
        scoring="neg_mean_absolute_error",
        cv=3,
        random_state=42,
        n_jobs=-1,
        verbose=1,
    )
    search.fit(X_train, y_train)

    best = search.best_estimator_

    # evaluate
    pred_test = best.predict(X_test)
    metrics = {
        "model_version": "rf_latency_v1",
        "trained_at_utc": datetime.utcnow().isoformat(),
        "n_real_rows": len(real_y),
        "n_synthetic_rows": len(syn_y),
        "test_mae_ms": float(mean_absolute_error(y_test, pred_test)),
        "test_rmse_ms": rmse(y_test, pred_test),
        "test_r2": float(r2_score(y_test, pred_test)),
        "test_mape_pct": mape(y_test, pred_test),
        "best_params": search.best_params_,
    }

    # conformal (one-sided upper) on calibration set
    pred_cal = best.predict(X_cal)
    resid = (y_cal - pred_cal)  # positive means model underestimated
    q90 = float(np.quantile(resid, 0.90))
    q95 = float(np.quantile(resid, 0.95))
    metrics["conformal_q90_ms"] = max(0.0, q90)
    metrics["conformal_q95_ms"] = max(0.0, q95)

    # segment metrics: by resource_type + job_type
    seg = []
    for key in [("resource_type",), ("job_type",), ("resource_type","job_type")]:
        cols = list(key)
        tmp = X_test.copy()
        tmp["y"] = y_test
        tmp["pred"] = pred_test
        grp = tmp.groupby(cols)
        for name, g in grp:
            seg.append({
                "segment": str(name),
                "by": cols,
                "n": int(len(g)),
                "mae_ms": float(mean_absolute_error(g["y"], g["pred"])),
                "rmse_ms": rmse(g["y"], g["pred"]),
            })
    metrics["segment_metrics"] = seg

    # save
    model_path = MODEL_DIR / "latency_model.joblib"
    meta_path  = MODEL_DIR / "latency_model_metrics.json"
    joblib.dump(best, model_path)
    meta_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("\n✅ Latency model trained + saved")
    print(f"Model:   {model_path}")
    print(f"Metrics: {meta_path}")
    print(json.dumps({k: metrics[k] for k in ["test_mae_ms","test_rmse_ms","test_r2","test_mape_pct","conformal_q90_ms"]}, indent=2))

if __name__ == "__main__":
    main()
