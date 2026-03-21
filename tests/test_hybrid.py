import pandas as pd
import joblib
import os
from src.inference import hybrid_predict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARTIFACTS_PATH = os.path.join(BASE_DIR, "artifacts")
DATA_PATH = os.path.join(BASE_DIR, "data", "logs.csv")

# Load models
model = joblib.load(os.path.join(ARTIFACTS_PATH, "modelhybrid.pkl"))
scaler = joblib.load(os.path.join(ARTIFACTS_PATH, "scalerhybrid.pkl"))
tfidf = joblib.load(os.path.join(ARTIFACTS_PATH, "tfidfhybrid.pkl"))
encoders = joblib.load(os.path.join(ARTIFACTS_PATH, "encodershybrid.pkl"))

# Load data
df_test = pd.read_csv(DATA_PATH)
df_test.fillna("unknown", inplace=True)

results = []

for _, row in df_test.iterrows():
    log = {
        "message": row["message"],
        "service_name": row["service_name"],
        "event_type": row["event_type"]
    }

    pred = hybrid_predict(log, model, scaler, tfidf, encoders)
    results.append(pred)

df_test["prediction"] = [r["prediction"] for r in results]
df_test["source"] = [r["source"] for r in results]
df_test["risk"] = [r["risk"] for r in results]

df_test.to_csv(os.path.join(ARTIFACTS_PATH, "hybrid_test_results.csv"), index=False)

print(df_test.head(20))