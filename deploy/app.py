from fastapi import FastAPI
from src.predict import predict_log

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Hybrid Anomaly Model Running"}

@app.get("/predict")
def predict(message: str, service: str, event: str):
    severity, score = predict_log(message, service, event)
    return {
        "severity": severity,
        "anomaly_score": float(score)
    }