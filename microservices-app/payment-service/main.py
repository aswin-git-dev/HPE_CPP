"""Payment Service — Stub
This service will handle payment processing.
Full implementation coming soon.
"""
from fastapi import FastAPI

app = FastAPI(
    title="Payment Service",
    description="Payment Handling Microservice — E-Commerce Platform (Stub)",
    version="0.1.0",
)

@app.get("/")
async def root():
    return {
        "service": "payment-service",
        "status": "stub",
        "message": "Payment Service — Coming Soon",
        "planned_endpoints": [
            "POST /payments/initiate",
            "GET  /payments/{id}/status",
            "POST /payments/{id}/refund",
        ]
    }

@app.get("/health")
async def health():
    return {"service": "payment-service", "status": "stub"}
