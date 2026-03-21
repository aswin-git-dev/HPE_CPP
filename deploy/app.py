from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import os

from src.inference import hybrid_predict

# -----------------------------
# Paths (IMPORTANT FIX)
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARTIFACTS_PATH = os.path.join(BASE_DIR, "artifacts")

# -----------------------------
# Load artifacts
# -----------------------------
model = joblib.load(os.path.join(ARTIFACTS_PATH, "modelhybrid.pkl"))
scaler = joblib.load(os.path.join(ARTIFACTS_PATH, "scalerhybrid.pkl"))
tfidf = joblib.load(os.path.join(ARTIFACTS_PATH, "tfidfhybrid.pkl"))
encoders = joblib.load(os.path.join(ARTIFACTS_PATH, "encodershybrid.pkl"))

# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title="Hybrid Log Analyzer API")

class LogEntry(BaseModel):
    message: str
    service_name: str
    event_type: str


@app.post("/predict")
def predict_log(log: LogEntry):
    result = hybrid_predict(log.dict(), model, scaler, tfidf, encoders)
    return result


@app.get("/")
def root():
    return {"message": "Hybrid Log Analyzer API is running 🚀"}