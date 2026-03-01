"""Notification Service — Stub
This service will handle Email/SMS alerts.
Full implementation coming soon.
"""
from fastapi import FastAPI

app = FastAPI(
    title="Notification Service",
    description="Email/SMS Notification Microservice — E-Commerce Platform (Stub)",
    version="0.1.0",
)

@app.get("/")
async def root():
    return {
        "service": "notification-service",
        "status": "stub",
        "message": "Notification Service — Coming Soon",
        "planned_endpoints": [
            "POST /notifications/email",
            "POST /notifications/sms",
            "GET  /notifications/{user_id}/history",
        ]
    }

@app.get("/health")
async def health():
    return {"service": "notification-service", "status": "stub"}
