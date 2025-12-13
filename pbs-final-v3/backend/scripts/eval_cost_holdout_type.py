import json, sqlite3
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from app.core.config import settings
from app.services.cost_ml import predict_cost

con = sqlite3.connect(settings.db_path)
rows = con.execute("""
SELECT features_json, actual_cost_usd
FROM jobs
WHERE status='COMPLETED'
  AND features_json IS NOT NULL
  AND actual_cost_usd IS NOT NULL
""").fetchall()
con.close()

data=[]
for fjson, y in rows:
    d=json.loads(fjson)
    d["actual_cost_usd"]=float(y)
    data.append(d)

df=pd.DataFrame(data)
if "resource_type" not in df.columns:
    print("resource_type missing in features_json. Fix worker capture first.")
    raise SystemExit()

types=df["resource_type"].value_counts().to_dict()
print("counts_by_type:", types)

# Evaluate separately per type
for rt in sorted(df["resource_type"].unique()):
    sub=df[df["resource_type"]==rt].copy()
    y_true=sub["actual_cost_usd"].values
    preds=[]
    for _,row in sub.iterrows():
        d=row.drop(labels=["actual_cost_usd"]).to_dict()
        p=predict_cost(d)
        preds.append(float(p["mean_usd"]))
    y_pred=np.array(preds)
    print(rt, "n=", len(sub), "MAE=", mean_absolute_error(y_true,y_pred), "R2=", r2_score(y_true,y_pred))
